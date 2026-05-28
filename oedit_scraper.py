"""
OEDIT (Colorado Office of Economic Development & International Trade) scraper.

Fetches monthly "EDC Approved Job Growth Incentive Tax Credit and Strategic
Fund Projects" pages and extracts each approved project into a structured
record suitable for the CRM Inbox.

URL pattern (confirmed manually):
  https://oedit.colorado.gov/news/{month}-{year}-edc-approved-job-growth-
  incentive-tax-credit-and-strategic-fund-projects

Page structure (as of 2026):
  - <h1> with page title
  - One or more <h2> blocks labeled "Project Name: X" (or sometimes the
    real company name with no "Project Name:" prefix)
  - Each project has <h3> subsections: Summary, Jobs, Incentive,
    Consideration
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import requests
from bs4 import BeautifulSoup
from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

# Counties in the Denver metro / Front Range core that fit our service area
DENVER_METRO_COUNTIES = {
    "Denver", "Adams", "Arapahoe", "Boulder", "Broomfield",
    "Douglas", "Jefferson",
}
EXTENDED_FRONT_RANGE = DENVER_METRO_COUNTIES | {"Larimer", "Weld", "El Paso"}

# Keyword → industry classification (matched against the Summary text)
INDUSTRY_KEYWORDS = [
    (r"\b(aerospace|missile|hypersonic|satellite|spaceflight|space\s+launch|"
     r"space\s+systems|orbital|rocket|launch\s+vehicle|defense\s+contractor|"
     r"national\s+defense|defense\s+sector|defense\s+and\s+aerospace)\b",
     "Aerospace/Defense"),
    (r"\b(biotech|life sciences|pharmaceutical|pharma|therapeutics|"
     r"medical device|diagnostics)\b", "Biotech/Life Sciences"),
    (r"\b(quantum|semiconductor|chip|chips)\b", "AI/ML"),
    (r"\b(artificial intelligence|AI |machine learning|ML |data center)\b",
     "AI/ML"),
    (r"\b(fintech|financial technology|payments|banking)\b", "Fintech"),
    (r"\b(financial services|investment|insurance)\b", "Financial Services"),
    (r"\b(clean ?tech|renewable|solar|wind|battery|climate)\b",
     "Cleantech/Energy"),
    (r"\b(outdoor|recreation|cycling|apparel)\b", "Outdoor/Recreation"),
    (r"\b(manufactur|fabrication|assembly)\b", "Manufacturing"),
    (r"\b(healthcare|hospital|clinic|health system)\b", "Healthcare"),
    (r"\b(SaaS|software|cloud|platform|enterprise software)\b", "Tech/SaaS"),
]

USER_AGENT = (
    "Mozilla/5.0 (compatible; RelocationCRMBot/1.0; "
    "+research/CRM intel pipeline)"
)
REQUEST_TIMEOUT = 30


@dataclass
class OEDITProject:
    """A single approved project from an OEDIT monthly page."""
    project_name: str
    company_name: Optional[str]   # None if confidential ("Project X")
    summary: str
    jobs_text: str
    incentive_text: str
    job_count: Optional[int]
    incentive_amount: Optional[int]
    counties: list[str] = field(default_factory=list)
    competing_states: list[str] = field(default_factory=list)
    industry: Optional[str] = None
    source_url: str = ""
    meeting_date: Optional[str] = None  # YYYY-MM-DD

    @property
    def is_denver_metro(self) -> bool:
        return bool(set(self.counties) & DENVER_METRO_COUNTIES)

    @property
    def is_front_range(self) -> bool:
        return bool(set(self.counties) & EXTENDED_FRONT_RANGE)

    @property
    def display_name(self) -> str:
        return self.company_name or self.project_name

    def to_inbox_row(self, suggested_match: str = "", confidence: int = 0) -> dict:
        """Convert to a dict suitable for SheetsClient.append_inbox_rows."""
        jobs_part = f"{self.job_count:,} jobs" if self.job_count else "jobs TBD"
        counties_part = f", {'/'.join(self.counties)}" if self.counties else ""
        states_part = (f" (vs {', '.join(self.competing_states)})"
                       if self.competing_states else "")
        ind = self.industry or "industry unclear"

        description = (
            f"OEDIT EDC approved: {jobs_part} in {ind}{counties_part}{states_part}. "
            f"{self._truncate(self.summary, 280)}"
        ).strip()

        notes_parts = []
        if self.incentive_amount:
            notes_parts.append(f"Incentive: ${self.incentive_amount:,}")
        if self.meeting_date:
            notes_parts.append(f"EDC meeting: {self.meeting_date}")
        if not self.is_front_range and self.counties:
            notes_parts.append("⚠ Outside Front Range — likely low fit")

        return {
            "source_name": "OEDIT EDC",
            "source_url": self.source_url,
            "extracted_company": self.display_name,
            "extracted_description": description,
            "extracted_jobs": self.job_count or "",
            "extracted_county": ", ".join(self.counties),
            "suggested_match": suggested_match,
            "match_confidence": confidence if confidence else "",
            "notes": " | ".join(notes_parts),
        }

    @staticmethod
    def _truncate(s: str, n: int) -> str:
        s = re.sub(r"\s+", " ", s or "").strip()
        return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------

MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


def build_url(year: int, month: int) -> str:
    return (
        f"https://oedit.colorado.gov/news/"
        f"{MONTHS[month - 1]}-{year}-edc-approved-job-growth-incentive-"
        f"tax-credit-and-strategic-fund-projects"
    )


def fetch_page(url: str) -> Optional[str]:
    """Fetch a page, returning HTML or None if not found / error."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code == 404:
            log.info("404 (not yet posted): %s", url)
            return None
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        log.warning("Fetch failed for %s: %s", url, e)
        return None


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------

PROJECT_NAME_RE = re.compile(r"Project Name:\s*(.+)", re.IGNORECASE)
JOBS_RE = re.compile(
    r"(?:up to\s+)?(?:approximately\s+)?([\d,]+)\s+(?:net[\s-]new\s+)?(?:full[\s-]time\s+)?jobs",
    re.IGNORECASE,
)
INCENTIVE_RE = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
COUNTY_RE = re.compile(r"([A-Z][a-zA-Z]+)\s+Count(?:y|ies)", re.IGNORECASE)
COMPETING_STATES_RE = re.compile(
    r"considering\s+([A-Z][a-zA-Z ,]+?)(?=\.|;|Within Colorado|$)",
    re.IGNORECASE,
)


def parse_meeting_date(soup: BeautifulSoup) -> Optional[str]:
    """Extract the meeting date string (e.g., 'Thursday, April 16, 2026')."""
    # The date appears as plain text near the top, usually right after title
    body_text = soup.get_text("\n")
    m = re.search(
        r"(?:Monday|Tuesday|Wednesday|Thursday|Friday),\s+"
        r"(January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+(\d{1,2}),\s+(\d{4})",
        body_text,
    )
    if not m:
        return None
    month_name, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    month_num = MONTHS.index(month_name.lower()) + 1
    return f"{year:04d}-{month_num:02d}-{day:02d}"


def classify_industry(text: str) -> Optional[str]:
    for pattern, industry in INDUSTRY_KEYWORDS:
        if re.search(pattern, text, re.IGNORECASE):
            return industry
    return None


def extract_counties(text: str) -> list[str]:
    """
    Pull county names from a chunk of text. Looks for patterns like
    'Douglas County', 'Douglas County and/or Jefferson County',
    'Douglas and Jefferson Counties'.
    """
    counties = set()
    for m in COUNTY_RE.finditer(text):
        # Filter to known Colorado counties to avoid false positives
        # like "Florida County" (there isn't one, but safer)
        name = m.group(1).strip()
        if name in EXTENDED_FRONT_RANGE or _is_known_colorado_county(name):
            counties.add(name)

    # Also handle "X and Y Counties" pattern: County regex catches only
    # the second name, so additionally scan for paired county references.
    for m in re.finditer(
        r"([A-Z][a-zA-Z]+)\s+and(?:/or)?\s+([A-Z][a-zA-Z]+)\s+Count(?:y|ies)",
        text,
    ):
        for name in (m.group(1), m.group(2)):
            if _is_known_colorado_county(name):
                counties.add(name)

    return sorted(counties)


# Comprehensive list of Colorado counties for filter validation
COLORADO_COUNTIES = {
    "Adams", "Alamosa", "Arapahoe", "Archuleta", "Baca", "Bent", "Boulder",
    "Broomfield", "Chaffee", "Cheyenne", "Clear Creek", "Conejos", "Costilla",
    "Crowley", "Custer", "Delta", "Denver", "Dolores", "Douglas", "Eagle",
    "Elbert", "El Paso", "Fremont", "Garfield", "Gilpin", "Grand", "Gunnison",
    "Hinsdale", "Huerfano", "Jackson", "Jefferson", "Kiowa", "Kit Carson",
    "Lake", "La Plata", "Larimer", "Las Animas", "Lincoln", "Logan", "Mesa",
    "Mineral", "Moffat", "Montezuma", "Montrose", "Morgan", "Otero", "Ouray",
    "Park", "Phillips", "Pitkin", "Prowers", "Pueblo", "Rio Blanco", "Rio Grande",
    "Routt", "Saguache", "San Juan", "San Miguel", "Sedgwick", "Summit",
    "Teller", "Washington", "Weld", "Yuma",
}


def _is_known_colorado_county(name: str) -> bool:
    return name in COLORADO_COUNTIES


def extract_competing_states(text: str) -> list[str]:
    """
    Pull state names listed as alternatives. Patterns like:
      'considering Alabama, Florida, and Pennsylvania'
      'considering Texas and Arizona'
    """
    m = COMPETING_STATES_RE.search(text)
    if not m:
        return []
    chunk = m.group(1)
    # Split on commas and 'and'
    pieces = re.split(r",|\band\b", chunk)
    return [p.strip().rstrip(".") for p in pieces if p.strip()]


def extract_int(pattern_match) -> Optional[int]:
    if not pattern_match:
        return None
    try:
        return int(pattern_match.group(1).replace(",", "").split(".")[0])
    except (ValueError, IndexError):
        return None


def parse_projects(html: str, source_url: str) -> list[OEDITProject]:
    """Parse all projects on a monthly OEDIT page."""
    soup = BeautifulSoup(html, "html.parser")
    meeting_date = parse_meeting_date(soup)

    # Each project starts at an h2 whose text begins with "Project Name:"
    # or that contains a known sponsor pattern. We slice page content by h2.
    h2s = soup.find_all("h2")
    projects: list[OEDITProject] = []

    for h2 in h2s:
        h2_text = h2.get_text(strip=True)
        name_match = PROJECT_NAME_RE.match(h2_text)
        if not name_match:
            # Skip h2s that aren't project headers (navigation, "Recent", etc.)
            continue

        project_name = name_match.group(1).strip().rstrip(":")

        # Confidential code-named projects start with "Project " (e.g., "Project Hera").
        # Disclosed companies just have a company name in the h2.
        is_confidential = bool(
            re.match(r"^[A-Z][a-zA-Z]+$", project_name)
            and project_name[0].isupper()
            and not _looks_like_real_company_name(project_name)
        )
        # Heuristic refinement: if "Project Name: Hera" and the summary
        # explicitly says "company behind Project X", it's confidential.
        company_name = None if _is_codename_only(project_name) else project_name
        if not company_name:
            full_name = f"Project {project_name}"
        else:
            full_name = company_name

        # Gather all content from this h2 until the next h2
        summary_text, jobs_text, incentive_text = _collect_subsections(h2)

        # Compose full body for keyword scanning
        body = " ".join(filter(None, [summary_text, jobs_text, incentive_text]))

        # Extract numeric fields. Jobs and incentive amounts can appear
        # in multiple places; prefer the dedicated subsection if present.
        job_count = extract_int(JOBS_RE.search(jobs_text or body))
        incentive_amount = extract_int(INCENTIVE_RE.search(incentive_text or body))

        counties = extract_counties(summary_text or body)
        competing_states = extract_competing_states(summary_text or body)
        industry = classify_industry(body)

        projects.append(OEDITProject(
            project_name=full_name,
            company_name=company_name,
            summary=summary_text or body[:500],
            jobs_text=jobs_text or "",
            incentive_text=incentive_text or "",
            job_count=job_count,
            incentive_amount=incentive_amount,
            counties=counties,
            competing_states=competing_states,
            industry=industry,
            source_url=source_url,
            meeting_date=meeting_date,
        ))

    return projects


def _is_codename_only(name: str) -> bool:
    """
    True if the name is likely an OEDIT codename (single capitalized word
    like Hera, Neptune, Ladybug, Short Circuit) rather than a real company.
    """
    # A real company name often has Inc., LLC, Corp, multiple words with
    # mixed case, etc. Codenames tend to be 1-2 mythological/whimsical words.
    if any(suffix in name for suffix in ("Inc", "LLC", "Corp", "Ltd", "Co.", "GmbH")):
        return False
    word_count = len(name.split())
    if word_count > 2:
        return False  # Likely a real multi-word company name
    return True  # Default to assuming codename when in doubt


def _looks_like_real_company_name(name: str) -> bool:
    return not _is_codename_only(name)


def _collect_subsections(h2_tag) -> tuple[str, str, str]:
    """
    Walk siblings after the project h2 until the next h2, collecting text
    grouped by the h3 subsections: Summary, Jobs, Incentive.
    """
    sections = {"summary": [], "jobs": [], "incentive": []}
    current = None

    for sibling in h2_tag.find_all_next():
        if sibling.name == "h2":
            break
        if sibling.name == "h3":
            label = sibling.get_text(strip=True).lower()
            if "summary" in label:
                current = "summary"
            elif "job" in label:
                current = "jobs"
            elif "incentive" in label:
                current = "incentive"
            else:
                current = None
            continue
        if current and sibling.name in ("p", "ul", "ol", "li", "div"):
            text = sibling.get_text(" ", strip=True)
            if text:
                sections[current].append(text)

    return (
        " ".join(sections["summary"]),
        " ".join(sections["jobs"]),
        " ".join(sections["incentive"]),
    )


# ----------------------------------------------------------------------
# Fuzzy matching against existing companies
# ----------------------------------------------------------------------

def suggest_match(
    project_name: str,
    existing_companies: list[dict],
    threshold: int = 85,
) -> tuple[str, int]:
    """
    Returns (company_id, confidence) for the best fuzzy match against
    existing companies. Returns ('', 0) if no good match.
    """
    if not existing_companies:
        return "", 0
    names = {c["name"]: c["company_id"] for c in existing_companies if c["name"]}
    if not names:
        return "", 0
    result = process.extractOne(
        project_name,
        list(names.keys()),
        scorer=fuzz.WRatio,
    )
    if not result:
        return "", 0
    matched_name, score, _ = result
    if score >= threshold:
        return names[matched_name], int(score)
    return "", 0


# ----------------------------------------------------------------------
# High-level orchestration
# ----------------------------------------------------------------------

def scrape_month(year: int, month: int) -> list[OEDITProject]:
    """Fetch and parse one OEDIT monthly page. Returns [] if not posted yet."""
    url = build_url(year, month)
    log.info("Fetching %s", url)
    html = fetch_page(url)
    if html is None:
        return []
    projects = parse_projects(html, url)
    log.info("  Parsed %d projects from %s %d", len(projects), MONTHS[month - 1], year)
    return projects


def get_recent_months(n: int, today: Optional[date] = None) -> list[tuple[int, int]]:
    """Returns the last n (year, month) tuples, most recent first."""
    today = today or date.today()
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m < 1:
            m = 12
            y -= 1
    return out
