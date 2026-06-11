"""
ATS job-board collector (Greenhouse + Lever public APIs).

This is the robust alternative to scraping Built In Colorado / Indeed.
Instead of scraping a JS-rendered aggregator, we hit the official, public,
auth-free JSON APIs that companies' applicant-tracking systems expose --
the same source those aggregators pull from.

  Greenhouse: https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
  Lever:      https://api.lever.co/v0/postings/{token}?mode=json

What it produces:
  - COMPANY boards  -> one Inbox row per Front-Range posting that mentions
    employer-provided relocation. These are discrete, high-value, naturally
    deduplicated signals (each job has a unique, stable URL).
  - RECRUITER boards -> one summary Inbox row per firm that is actively
    posting Front-Range roles, prioritized by relocation mentions. (Most
    retained executive-search firms won't appear here -- see the separate
    recruiter starter list for those.)

The watch-list of boards lives in ats_watchlist.py. Seed it from the
companies already in your CRM; the tool skips unknown/invalid tokens.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; RelocationCRMBot/1.0; internal research)"
REQUEST_TIMEOUT = 30
DELAY_BETWEEN_BOARDS = 1.0

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
LEVER_URL = "https://api.lever.co/v0/postings/{token}?mode=json"

# Front Range location terms (matched against the structured location string,
# falling back to the description). Note: bare "CO" is risky, so we match
# ", co" / "colorado" / specific metro place names instead.
CO_LOCATION_TERMS = [
    "colorado", ", co", " co ", "denver", "boulder", "aurora", "lakewood",
    "centennial", "englewood", "littleton", "broomfield", "thornton",
    "westminster", "arvada", "golden", "longmont", "loveland", "fort collins",
    "parker", "castle rock", "lone tree", "louisville", "superior",
    "wheat ridge", "commerce city", "greenwood village", "highlands ranch",
    "colorado springs",
]

# Employer-PROVIDED relocation language. Deliberately excludes candidate-side
# phrasing like "willing to relocate", which does not indicate an employer
# benefit.
RELOCATION_RE = re.compile(
    r"relocation\s+(assistance|package|benefit|benefits|support|reimbursement|"
    r"bonus|stipend|allowance|offered|available|provided|provision)"
    r"|(offer|offers|offering|provide|provides|providing|including|includes)\s+"
    r"(a\s+)?relocation"
    r"|relo\s+(package|assistance|benefits)"
    r"|will\s+relocate\s+(the\s+)?(right|qualified|selected)\s+candidate",
    re.IGNORECASE,
)


@dataclass
class ATSJob:
    """A single relocation-mentioning Front-Range job posting (company board)."""
    org_name: str
    title: str
    location: str
    url: str
    ats: str
    posted_at: Optional[str] = None

    @property
    def link(self) -> str:
        return self.url

    @property
    def display_name(self) -> str:
        return self.org_name

    def to_inbox_row(self, suggested_match: str = "", confidence: int = 0) -> dict:
        date_part = f", {self.posted_at}" if self.posted_at else ""
        return {
            "source_name": f"ATS: {self.org_name}"[:80],
            "source_url": self.url,
            "extracted_company": self.org_name,
            "extracted_description": (
                f"Hiring ({self.ats}): \"{self.title}\" in {self.location}{date_part} "
                f"— posting mentions employer relocation assistance"
            ),
            "extracted_jobs": "",
            "extracted_county": "",
            "suggested_match": suggested_match,
            "match_confidence": confidence if confidence else "",
            "notes": (
                "Hiring signal: a Front-Range role at this company explicitly "
                "offers relocation — strong indicator they move people in. "
                "Corroborates / raises priority."
            ),
        }


@dataclass
class RecruiterActivity:
    """Board-level summary for a recruiting/staffing firm (recruiter board)."""
    org_name: str
    board_url: str
    ats: str
    front_range_count: int
    relocation_count: int
    sample_titles: list[str] = field(default_factory=list)

    @property
    def link(self) -> str:
        return self.board_url

    @property
    def display_name(self) -> str:
        return self.org_name

    def to_inbox_row(self, suggested_match: str = "", confidence: int = 0) -> dict:
        titles = "; ".join(self.sample_titles[:4])
        relo = (f"{self.relocation_count} mention relocation"
                if self.relocation_count else "none mention relocation")
        return {
            "source_name": f"Recruiter (ATS): {self.org_name}"[:80],
            "source_url": self.board_url,
            "extracted_company": self.org_name,
            "extracted_description": (
                f"RECRUITER actively posting {self.front_range_count} Front-Range "
                f"role(s) ({relo}). Sample: {titles}"
            ),
            "extracted_jobs": self.front_range_count,
            "extracted_county": "",
            "suggested_match": suggested_match,
            "match_confidence": confidence if confidence else "",
            "notes": (
                "PARTNER TARGET, not a relocation client. A recruiting firm "
                "placing Front-Range roles = potential referral partner. "
                "Triage into a Recruiters tab rather than Companies."
            ),
        }


# ----------------------------------------------------------------------
# Fetching + normalizing
# ----------------------------------------------------------------------

def _get(url: str) -> Optional[dict]:
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 404:
            log.info("  404 (invalid/unknown board token): %s", url)
            return None
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("  fetch failed: %s (%s)", url, e)
        return None


def normalize_greenhouse(payload: dict) -> list[dict]:
    jobs = []
    for j in (payload or {}).get("jobs", []):
        loc = ((j.get("location") or {}).get("name")) or ""
        jobs.append({
            "title": j.get("title", ""),
            "location": loc,
            "url": j.get("absolute_url", ""),
            "content": j.get("content", "") or "",  # HTML-escaped
            "posted_at": (j.get("updated_at") or j.get("first_published") or "")[:10],
        })
    return jobs


def normalize_lever(payload: list) -> list[dict]:
    jobs = []
    for p in (payload or []):
        cats = p.get("categories") or {}
        jobs.append({
            "title": p.get("text", ""),
            "location": cats.get("location", "") or "",
            "url": p.get("hostedUrl", ""),
            "content": p.get("descriptionPlain", "") or p.get("description", "") or "",
            "posted_at": _epoch_to_date(p.get("createdAt")),
        })
    return jobs


def _epoch_to_date(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def fetch_board(ats: str, token: str,
                _raw=None) -> list[dict]:
    """Fetch + normalize one board. `_raw` injects payload for tests."""
    ats = ats.lower()
    if ats == "greenhouse":
        payload = _raw if _raw is not None else _get(GREENHOUSE_URL.format(token=token))
        return normalize_greenhouse(payload) if payload is not None else []
    if ats == "lever":
        payload = _raw if _raw is not None else _get(LEVER_URL.format(token=token))
        return normalize_lever(payload) if payload is not None else []
    log.warning("  unknown ATS type %r for token %r (supported: greenhouse, lever)", ats, token)
    return []


# ----------------------------------------------------------------------
# Filters
# ----------------------------------------------------------------------

def is_front_range(job: dict) -> bool:
    loc = (job.get("location") or "").lower()
    if any(t in loc for t in CO_LOCATION_TERMS):
        return True
    # Remote roles only count if the text ties them to Colorado specifically
    if "remote" in loc:
        content = (job.get("content") or "").lower()
        return "colorado" in content or "denver" in content
    return False


def mentions_relocation(job: dict) -> bool:
    return bool(RELOCATION_RE.search(job.get("content") or ""))


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------

def scrape_ats(watchlist: Optional[list[dict]] = None) -> list:
    """
    Walk the watch-list, fetch each board, and emit findings:
      - company boards -> ATSJob per relocation-mentioning Front-Range role
      - recruiter boards -> one RecruiterActivity summary if actively posting
    """
    if watchlist is None:
        from ats_watchlist import WATCHLIST
        watchlist = WATCHLIST

    findings: list = []

    for entry in watchlist:
        name = entry.get("name", entry.get("token", "?"))
        ats = entry.get("ats", "")
        token = entry.get("token", "")
        org_type = entry.get("type", "company").lower()
        if not token or not ats:
            continue

        log.info("Fetching %s board: %s (%s)", ats, name, token)
        jobs = fetch_board(ats, token)
        if not jobs:
            time.sleep(DELAY_BETWEEN_BOARDS)
            continue

        fr_jobs = [j for j in jobs if is_front_range(j)]
        relo_jobs = [j for j in fr_jobs if mentions_relocation(j)]
        log.info("  %d total, %d Front-Range, %d mention relocation",
                 len(jobs), len(fr_jobs), len(relo_jobs))

        if org_type == "recruiter":
            if fr_jobs:
                findings.append(RecruiterActivity(
                    org_name=name,
                    board_url=entry.get("board_url", "")
                              or (GREENHOUSE_URL.format(token=token) if ats == "greenhouse"
                                  else LEVER_URL.format(token=token)),
                    ats=ats,
                    front_range_count=len(fr_jobs),
                    relocation_count=len(relo_jobs),
                    sample_titles=[j["title"] for j in fr_jobs[:4]],
                ))
        else:  # company
            for j in relo_jobs:
                if not j.get("url"):
                    continue
                findings.append(ATSJob(
                    org_name=name,
                    title=j["title"],
                    location=j["location"] or "Front Range",
                    url=j["url"],
                    ats=ats,
                    posted_at=j.get("posted_at") or None,
                ))

        time.sleep(DELAY_BETWEEN_BOARDS)

    # Sort so relocation company-signals lead, recruiters after
    findings.sort(key=lambda f: 0 if isinstance(f, ATSJob) else 1)
    log.info("ATS findings: %d", len(findings))
    return findings
