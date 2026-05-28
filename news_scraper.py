"""
News scraper — aggregates Denver-area corporate relocation / expansion
signals from Google News RSS.

Why Google News RSS instead of scraping Bisnow/DBJ/BusinessDen directly:
  - One clean XML feed covers every publisher Google indexes at once.
  - No JS rendering, no cookie-consent walls, stable format.
  - Returns headline + link + date + publisher; we store only those and
    always link back to the original source (functions like a personal
    RSS reader / alert system for the user's own research).

Design philosophy: for unstructured news (unlike OEDIT's structured
project pages), this scraper FILTERS and FORWARDS. It surfaces relevant
headlines into the Inbox; the human triage step does the precision work
of confirming the company and deciding Create/Link/Ignore.

Feed URL format (confirmed working 2026):
  https://news.google.com/rss/search?q=QUERY&hl=en-US&gl=US&ceid=US:en
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import requests

try:
    import feedparser
except ImportError:  # pragma: no cover - tests stub this
    feedparser = None

# Reuse the industry classifier from the OEDIT scraper
from oedit_scraper import classify_industry

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (compatible; RelocationCRMBot/1.0; internal research)"
)
REQUEST_TIMEOUT = 30
DELAY_BETWEEN_FEEDS = 2.0  # seconds, be polite

GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"

# ----------------------------------------------------------------------
# Query set — each is a separate RSS fetch.
# "when:30d" limits to the last 30 days (good for monthly runs; the weekly
# GitHub schedule + dedup means overlap is harmless). Phrase queries in
# quotes are high-precision; broader queries get Python-side filtering.
# ----------------------------------------------------------------------

QUERIES = [
    # High-precision relocation phrases (little filtering needed)
    '"relocating to Denver" OR "relocate to Denver" OR "relocates to Denver" when:30d',
    '"moving to Denver" (headquarters OR office OR jobs) when:30d',
    '"new headquarters" (Denver OR Boulder OR Aurora) when:30d',
    # Office / lease expansion signals
    '(Denver OR Boulder OR Aurora) "office" (lease OR expansion OR "square feet") when:30d',
    '(Denver OR Boulder OR Aurora) company expansion jobs when:30d',
    # Bisnow's recurring transactions column (catches the Deal Sheet)
    '"Denver Deal Sheet" when:30d',
    # Aerospace/defense cluster (our highest-value niche)
    '(Aurora OR Colorado) (aerospace OR defense) (expansion OR jobs OR facility) when:30d',
]

# Geographic relevance — Front Range place names
DENVER_GEO_TERMS = [
    "denver", "boulder", "aurora", "colorado", "lakewood", "centennial",
    "englewood", "littleton", "broomfield", "thornton", "westminster",
    "arvada", "golden", "longmont", "loveland", "fort collins", "parker",
    "castle rock", "douglas county", "jefferson county", "arapahoe",
    "adams county", "lone tree", "louisville", "superior", "wheat ridge",
    "commerce city", "greenwood village", "dtc", "rino", "cherry creek",
]

# Relevance — relocation / expansion / hiring signal terms
SIGNAL_TERMS = [
    "relocat", "expand", "expansion", "headquarters", "hq", "new office",
    "office lease", "lease", "square feet", "sq ft", "sqft", "opening",
    "opens", "moving", "relocation", "jobs", "hiring", "footprint",
    "new facility", "campus", "sign lease", "signs lease", "leases",
]

# Words that, if they're the leading token, signal "not a company name"
NON_COMPANY_LEADERS = {
    "the", "a", "an", "how", "why", "what", "new", "more", "two", "three",
    "denver", "boulder", "aurora", "colorado", "report", "report:",
    "this", "these", "here", "meet", "inside", "first", "after", "as",
}

# Headline verbs/actions that typically follow the company (subject) name.
# In a Title-Case headline everything is capitalized, so we can't use case to
# find the proper noun — instead we treat the company as the tokens BEFORE the
# first action word. Matched case-insensitively.
HEADLINE_VERBS = {
    "doubles", "double", "expands", "expand", "expanding", "expansion",
    "relocating", "relocates", "relocate", "opens", "opening", "open",
    "signs", "sign", "inks", "plans", "plan", "moves", "moving", "move",
    "adds", "add", "launches", "launch", "brings", "bring", "eyes", "eye",
    "picks", "pick", "chooses", "choose", "lands", "land", "leases", "lease",
    "leased", "buys", "buy", "acquires", "acquire", "acquired", "to", "will",
    "sets", "set", "taps", "tap", "names", "name", "hires", "hire", "grows",
    "grow", "invests", "invest", "breaks", "build", "builds", "building",
    "considers", "consider", "weighs", "weigh", "mulls", "mull", "announces",
    "announce", "completes", "complete", "secures", "secure", "is", "are",
    "gets", "get", "takes", "take", "picked", "chosen", "boosts", "boost",
    "scoops", "snags", "snag", "wins", "win", "reveals", "reveal", "unveils",
}


@dataclass
class NewsItem:
    title: str
    link: str
    published: Optional[str]   # YYYY-MM-DD if parseable
    publisher: str
    summary: str
    company_guess: str = ""
    industry: Optional[str] = None
    query: str = ""

    def to_inbox_row(self, suggested_match: str = "", confidence: int = 0) -> dict:
        ind = f" [{self.industry}]" if self.industry else ""
        date_part = f", {self.published}" if self.published else ""
        description = f"{self.title} — {self.publisher}{date_part}{ind}"
        notes = f"News signal via Google News. Query: {self.query}"
        return {
            "source_name": f"News: {self.publisher}"[:80],
            "source_url": self.link,
            "extracted_company": self.company_guess or self.publisher,
            "extracted_description": description,
            "extracted_jobs": "",
            "extracted_county": "",
            "suggested_match": suggested_match,
            "match_confidence": confidence if confidence else "",
            "notes": notes,
        }


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------

def build_feed_url(query: str) -> str:
    q = urllib.parse.quote(query)
    return f"{GOOGLE_NEWS_BASE}?q={q}&hl=en-US&gl=US&ceid=US:en"


def fetch_feed(query: str) -> list:
    """Fetch and parse one Google News RSS query. Returns list of entries."""
    if feedparser is None:
        raise RuntimeError("feedparser not installed; run pip install -r requirements.txt")
    url = build_feed_url(query)
    log.info("Fetching feed: %s", query)
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning("Feed fetch failed for %r: %s", query, e)
        return []
    parsed = feedparser.parse(resp.content)
    return parsed.entries or []


# ----------------------------------------------------------------------
# Parsing & relevance
# ----------------------------------------------------------------------

def parse_entry(entry, query: str) -> Optional[NewsItem]:
    """Convert a feedparser entry into a NewsItem."""
    title = getattr(entry, "title", "").strip()
    link = getattr(entry, "link", "").strip()
    if not title or not link:
        return None

    # Google News appends ' - Publisher' to the title; also exposes source
    publisher = ""
    if hasattr(entry, "source") and getattr(entry.source, "title", ""):
        publisher = entry.source.title.strip()
    # Strip the trailing ' - Publisher' from the displayed title if present
    clean_title = title
    if publisher and title.endswith(f" - {publisher}"):
        clean_title = title[: -(len(publisher) + 3)].strip()
    elif " - " in title:
        # Fall back: last ' - ' chunk is usually the publisher
        head, _, tail = title.rpartition(" - ")
        if head and len(tail) < 40:
            clean_title, publisher = head.strip(), tail.strip()

    published = _parse_date(entry)
    summary = re.sub(r"<[^>]+>", " ", getattr(entry, "summary", "") or "")
    summary = re.sub(r"\s+", " ", summary).strip()

    item = NewsItem(
        title=clean_title,
        link=link,
        published=published,
        publisher=publisher or "Unknown",
        summary=summary,
        query=query,
    )
    item.company_guess = guess_company(clean_title)
    item.industry = classify_industry(f"{clean_title} {summary}")
    return item


def _parse_date(entry) -> Optional[str]:
    t = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if t:
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"
    return None


def is_relevant(item: NewsItem) -> bool:
    """An item is relevant if it references the Front Range AND a signal term."""
    haystack = f"{item.title} {item.summary}".lower()
    has_geo = any(term in haystack for term in DENVER_GEO_TERMS)
    has_signal = any(term in haystack for term in SIGNAL_TERMS)
    return has_geo and has_signal


def guess_company(title: str) -> str:
    """
    Best-effort company name from a headline. Imperfect by design — the
    human triage step corrects it.

    Headlines are Title Case, so capitalization can't distinguish a proper
    noun from an ordinary word. Instead we treat the company as the tokens
    BEFORE the first 'headline verb' (Doubles, Relocates, Opens, ...).
    Returns '' when the headline starts with a non-company word, a number,
    or has no clear verb delimiter within the first few tokens.
    """
    title = title.strip()
    if not title or re.match(r"^[\$\d]", title):
        return ""

    tokens = title.split()
    first_bare = tokens[0].strip(",.:;").lower()
    if first_bare in NON_COMPANY_LEADERS:
        return ""

    name_tokens = []
    found_verb = False
    for tok in tokens:
        bare = tok.strip(",.:;")
        low = bare.lower()

        # Stop at a colon (e.g., "Denver Deal Sheet:") — everything before is
        # a column label, not a company.
        if tok.endswith(":"):
            return ""

        if low in HEADLINE_VERBS:
            found_verb = True
            break

        name_tokens.append(bare)
        # Stop right after a true terminal legal suffix
        if bare.rstrip(".").lower() in {"inc", "llc", "corp", "ltd"}:
            found_verb = True  # treat suffix as a valid delimiter
            break
        if len(name_tokens) >= 5:
            break

    # If we never hit a verb/suffix delimiter, the headline is too ambiguous
    if not found_verb:
        return ""

    name = " ".join(name_tokens).strip(" &,")
    if len(name) < 2 or name.lower() in NON_COMPANY_LEADERS:
        return ""
    return name


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

def scrape_news(queries: Optional[list[str]] = None) -> list[NewsItem]:
    """Run all queries, parse, filter for relevance, dedup within-run by title."""
    queries = queries or QUERIES
    seen_titles: set[str] = set()
    items: list[NewsItem] = []

    for q in queries:
        entries = fetch_feed(q)
        log.info("  %d raw entries", len(entries))
        for entry in entries:
            item = parse_entry(entry, q)
            if not item:
                continue
            if not is_relevant(item):
                continue
            norm = re.sub(r"\W+", "", item.title.lower())
            if norm in seen_titles:
                continue
            seen_titles.add(norm)
            items.append(item)
        time.sleep(DELAY_BETWEEN_FEEDS)

    log.info("Relevant, de-duplicated news items: %d", len(items))
    return items
