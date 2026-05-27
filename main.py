"""
CLI entry point for the relocation scrapers.

Usage:
    python main.py                       # scrape last 3 months, write to Sheet
    python main.py --months 6            # scrape last 6 months
    python main.py --target 2026-04      # scrape one specific month
    python main.py --dry-run             # parse and print, but don't write
    python main.py --front-range-only    # skip projects outside Front Range

Add new scrapers in the future by calling them from here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from config import validate_config
from oedit_scraper import (
    get_recent_months,
    scrape_month,
    suggest_match,
)


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args():
    p = argparse.ArgumentParser(description="Relocation CRM scrapers")
    p.add_argument(
        "--months", type=int, default=3,
        help="Number of recent months to scrape (default: 3)",
    )
    p.add_argument(
        "--target", type=str, default=None,
        help="Scrape a specific month: YYYY-MM (overrides --months)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Don't write to Sheet; print what would be written",
    )
    p.add_argument(
        "--front-range-only", action="store_true",
        help="Skip projects outside the Front Range counties",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose logging",
    )
    return p.parse_args()


def main():
    args = parse_args()
    setup_logging(args.verbose)
    log = logging.getLogger("main")

    # Validate config early unless dry-running without Sheet access needed
    if not args.dry_run:
        validate_config()

    # Determine which months to scrape
    if args.target:
        try:
            y, m = args.target.split("-")
            months_to_scrape = [(int(y), int(m))]
        except (ValueError, IndexError):
            log.error("Invalid --target format; use YYYY-MM (e.g., 2026-04)")
            sys.exit(2)
    else:
        months_to_scrape = get_recent_months(args.months)

    # Scrape all months
    all_projects = []
    for y, m in months_to_scrape:
        projects = scrape_month(y, m)
        all_projects.extend(projects)

    log.info("Total projects parsed: %d", len(all_projects))

    if args.front_range_only:
        before = len(all_projects)
        all_projects = [p for p in all_projects if p.is_front_range]
        log.info("Filtered to Front Range: %d (was %d)", len(all_projects), before)

    if not all_projects:
        log.info("Nothing to write. Exiting.")
        return

    # Build inbox rows. If we have Sheet access (not dry-run), fuzzy match.
    if args.dry_run:
        print_projects(all_projects)
        return

    # Lazy import so dry-run doesn't require credentials
    from sheets_client import SheetsClient
    sheets = SheetsClient()
    existing_companies = sheets.get_companies()
    log.info("Loaded %d existing companies for matching", len(existing_companies))

    rows = []
    for project in all_projects:
        match_id, confidence = suggest_match(project.display_name, existing_companies)
        rows.append(project.to_inbox_row(suggested_match=match_id, confidence=confidence))

    added = sheets.append_inbox_rows(rows)
    log.info("Wrote %d new rows to Inbox (dedup skipped %d)", added, len(rows) - added)


def print_projects(projects):
    """Pretty-print parsed projects for --dry-run."""
    for i, p in enumerate(projects, 1):
        print(f"\n=== #{i}: {p.display_name} ===")
        print(f"  Meeting date:   {p.meeting_date or 'unknown'}")
        print(f"  Confidential:   {'yes' if not p.company_name else 'no'}")
        print(f"  Jobs:           {p.job_count or 'unknown'}")
        print(f"  Incentive:      ${p.incentive_amount:,}" if p.incentive_amount else "  Incentive:      unknown")
        print(f"  Counties:       {', '.join(p.counties) or 'unknown'}")
        print(f"  Competing:      {', '.join(p.competing_states) or 'none mentioned'}")
        print(f"  Industry:       {p.industry or 'unclassified'}")
        print(f"  Front Range:    {'yes' if p.is_front_range else 'no'}")
        print(f"  Source:         {p.source_url}")
        print(f"  Summary:        {p.summary[:200]}{'…' if len(p.summary) > 200 else ''}")


if __name__ == "__main__":
    main()
