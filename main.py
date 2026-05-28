"""
CLI entry point for the relocation scrapers.

Runs one or more source scrapers, fuzzy-matches findings against existing
companies, and writes new rows to the CRM Inbox (deduplicated).

Usage:
    python main.py                       # run all scrapers, write to Sheet
    python main.py --only oedit          # run just the OEDIT scraper
    python main.py --only news           # run just the news scraper
    python main.py --months 6            # OEDIT lookback window (default 3)
    python main.py --target 2026-04      # OEDIT: one specific month
    python main.py --dry-run             # parse and print, don't write
    python main.py --front-range-only    # OEDIT: skip non-Front-Range projects
    python main.py -v                    # verbose logging

Add future scrapers by writing a collector function that returns a list of
objects with a .to_inbox_row() method, then registering it in SCRAPERS.
"""

from __future__ import annotations

import argparse
import logging
import sys

from config import validate_config


def setup_logging(verbose: bool):
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args():
    p = argparse.ArgumentParser(description="Relocation CRM scrapers")
    p.add_argument("--only", choices=["oedit", "news"], default=None,
                   help="Run only one scraper (default: all)")
    p.add_argument("--months", type=int, default=3,
                   help="OEDIT: number of recent months to scrape (default 3)")
    p.add_argument("--target", type=str, default=None,
                   help="OEDIT: scrape a specific month YYYY-MM (overrides --months)")
    p.add_argument("--dry-run", action="store_true",
                   help="Don't write to Sheet; print what would be written")
    p.add_argument("--front-range-only", action="store_true",
                   help="OEDIT: skip projects outside the Front Range")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    return p.parse_args()


# ----------------------------------------------------------------------
# Collectors - each returns a list of objects exposing .to_inbox_row()
# ----------------------------------------------------------------------

def collect_oedit(args, log) -> list:
    from oedit_scraper import get_recent_months, scrape_month

    if args.target:
        try:
            y, m = args.target.split("-")
            months = [(int(y), int(m))]
        except (ValueError, IndexError):
            log.error("Invalid --target; use YYYY-MM (e.g., 2026-04)")
            sys.exit(2)
    else:
        months = get_recent_months(args.months)

    projects = []
    for y, m in months:
        projects.extend(scrape_month(y, m))
    log.info("OEDIT projects parsed: %d", len(projects))

    if args.front_range_only:
        before = len(projects)
        projects = [p for p in projects if p.is_front_range]
        log.info("  Filtered to Front Range: %d (was %d)", len(projects), before)
    return projects


def collect_news(args, log) -> list:
    from news_scraper import scrape_news
    items = scrape_news()
    log.info("News items collected: %d", len(items))
    return items


SCRAPERS = {
    "oedit": collect_oedit,
    "news": collect_news,
}


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main():
    args = parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("main")

    if not args.dry_run:
        validate_config()

    which = [args.only] if args.only else list(SCRAPERS.keys())

    all_findings = []
    for name in which:
        log.info("=== Running scraper: %s ===", name)
        findings = SCRAPERS[name](args, log)
        all_findings.extend(findings)

    log.info("Total findings across scrapers: %d", len(all_findings))
    if not all_findings:
        log.info("Nothing to write. Exiting.")
        return

    if args.dry_run:
        print_findings(all_findings)
        return

    # Write path - fuzzy match against existing companies, then append
    from sheets_client import SheetsClient
    from oedit_scraper import suggest_match

    sheets = SheetsClient()
    existing_companies = sheets.get_companies()
    log.info("Loaded %d existing companies for matching", len(existing_companies))

    # Pre-filter news findings against all known URLs (robust cross-run dedup
    # for unique-URL articles). OEDIT relies on the tuple dedup in the client.
    known_urls = sheets.get_all_known_urls()

    rows = []
    skipped_known = 0
    for f in all_findings:
        link = getattr(f, "link", None)
        if link and link in known_urls:
            skipped_known += 1
            continue
        name_for_match = (getattr(f, "display_name", None)
                          or getattr(f, "company_guess", "")
                          or getattr(f, "publisher", ""))
        match_id, confidence = suggest_match(name_for_match, existing_companies)
        rows.append(f.to_inbox_row(suggested_match=match_id, confidence=confidence))

    added = sheets.append_inbox_rows(rows)
    log.info(
        "Wrote %d new rows to Inbox (pre-skipped %d known URLs, client dedup skipped %d)",
        added, skipped_known, len(rows) - added,
    )


def print_findings(findings):
    """Pretty-print for --dry-run. Handles both OEDIT projects and news items."""
    for i, f in enumerate(findings, 1):
        row = f.to_inbox_row()
        print(f"\n=== #{i}: {row['extracted_company']} ===")
        print(f"  Source:      {row['source_name']}")
        print(f"  Description: {row['extracted_description']}")
        if row.get("extracted_county"):
            print(f"  County:      {row['extracted_county']}")
        if row.get("extracted_jobs"):
            print(f"  Jobs:        {row['extracted_jobs']}")
        print(f"  URL:         {row['source_url']}")
        if row.get("notes"):
            print(f"  Notes:       {row['notes']}")


if __name__ == "__main__":
    main()
