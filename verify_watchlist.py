"""
Watchlist verifier.

Pings every board in ats_watchlist.WATCHLIST and reports:
  - whether the token resolves at all (200 vs 404)
  - total job count
  - Front-Range job count
  - count of postings mentioning employer relocation language

Run:
    python verify_watchlist.py

Output is a clean table you can use to prune broken tokens and judge
which boards are actually worth keeping.
"""

from __future__ import annotations

import logging
import sys
import time

from ats_scraper import (
    GREENHOUSE_URL, LEVER_URL,
    fetch_board, is_front_range, mentions_relocation,
    DELAY_BETWEEN_BOARDS,
)
from ats_watchlist import WATCHLIST

logging.basicConfig(level=logging.WARNING, format="%(message)s")


def board_url(ats: str, token: str) -> str:
    return (GREENHOUSE_URL if ats == "greenhouse" else LEVER_URL).format(token=token)


def main():
    print(f"{'Name':<22} {'ATS':<11} {'Token':<22} {'Status':<8} {'Total':>6} {'FR':>5} {'Relo':>5}")
    print("-" * 86)

    ok, broken, no_fr = [], [], []

    for entry in WATCHLIST:
        name = entry.get("name", "?")
        ats = entry.get("ats", "")
        token = entry.get("token", "")
        if not token or not ats:
            print(f"{name:<22} {ats:<11} {token:<22} {'SKIP':<8} (missing ats/token)")
            continue

        jobs = fetch_board(ats, token)
        status = "OK" if jobs else "404/empty"
        total = len(jobs)
        fr = sum(1 for j in jobs if is_front_range(j))
        relo = sum(1 for j in jobs if is_front_range(j) and mentions_relocation(j))
        print(f"{name:<22} {ats:<11} {token:<22} {status:<8} {total:>6} {fr:>5} {relo:>5}")

        if not jobs:
            broken.append(f"{name} ({ats}/{token})")
        elif fr == 0:
            no_fr.append(name)
        else:
            ok.append((name, fr, relo))

        time.sleep(DELAY_BETWEEN_BOARDS)

    print("\nSummary")
    print("-------")
    print(f"  Working with Front-Range hits: {len(ok)}")
    for name, fr, relo in sorted(ok, key=lambda x: -x[2]):
        print(f"    • {name}: {fr} FR, {relo} relo")
    if no_fr:
        print(f"  Resolves but no Front-Range jobs ({len(no_fr)}):  {', '.join(no_fr)}")
    if broken:
        print(f"  Broken tokens (404 / empty) ({len(broken)}):  {', '.join(broken)}")
        print("\n  -> Visit each company's careers page, find the URL like")
        print("     boards.greenhouse.io/TOKEN or jobs.lever.co/TOKEN, and")
        print("     update ats_watchlist.py with the real token (or remove).")


if __name__ == "__main__":
    main()
