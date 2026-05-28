"""
Test the news scraper's parsing, company-extraction, relevance filtering,
and inbox-row generation. Uses synthetic feedparser-like entries; no network.
"""

import sys
import types

sys.path.insert(0, ".")

# Stub rapidfuzz (imported transitively via oedit_scraper)
fake_rf = types.ModuleType("rapidfuzz")
fake_rf.fuzz = types.SimpleNamespace(WRatio=lambda a, b: 0)
fake_rf.process = types.SimpleNamespace(extractOne=lambda *a, **k: None)
sys.modules["rapidfuzz"] = fake_rf

# Stub feedparser (we feed entries directly, so we don't need the real one)
sys.modules.setdefault("feedparser", types.ModuleType("feedparser"))

from news_scraper import (
    parse_entry, is_relevant, guess_company, NewsItem,
)


class FakeSource:
    def __init__(self, title):
        self.title = title


class FakeEntry:
    def __init__(self, title, link, summary="", source_title=None, date=None):
        self.title = title
        self.link = link
        self.summary = summary
        if source_title:
            self.source = FakeSource(source_title)
        if date:
            self.published_parsed = date  # time.struct_time-like


import time


def st(y, m, d):
    return time.struct_time((y, m, d, 0, 0, 0, 0, 0, 0))


def test_company_guess():
    assert guess_company("Snowflake Doubles Denver Office Footprint") == "Snowflake"
    assert guess_company("Giant Group USA Relocating Headquarters To Boulder") == "Giant Group USA"
    # Leading $ or number -> no guess
    assert guess_company("$200M Brighton Facility Will Make Modular Data Centers") == ""
    # Generic leader -> no guess
    assert guess_company("New Office Tower Opens In Downtown Denver") == ""
    assert guess_company("The Denver Deal Sheet: Contractor Expands") == ""
    print("✓ company guessing")


def test_relevance():
    relevant = NewsItem(
        title="Snowflake Expands Denver Office With New Lease",
        link="x", published="2026-05-01", publisher="Bisnow", summary="",
    )
    assert is_relevant(relevant)

    no_geo = NewsItem(
        title="Acme Corp Expands Office With New Lease",
        link="x", published=None, publisher="X", summary="",
    )
    assert not is_relevant(no_geo)  # no Front Range geo term

    no_signal = NewsItem(
        title="Denver Weather Forecast For The Weekend",
        link="x", published=None, publisher="X", summary="",
    )
    assert not is_relevant(no_signal)  # geo but no signal term
    print("✓ relevance filtering")


def test_parse_entry():
    entry = FakeEntry(
        title="Snowflake Doubles Denver Office Footprint - Bisnow",
        link="https://news.google.com/rss/articles/ABC123",
        summary="<p>The cloud company signed a new lease in <b>Denver</b>.</p>",
        source_title="Bisnow",
        date=st(2026, 5, 12),
    )
    item = parse_entry(entry, query="test-query")
    assert item is not None
    print(f"  Title:     {item.title}")
    print(f"  Publisher: {item.publisher}")
    print(f"  Date:      {item.published}")
    print(f"  Company:   {item.company_guess}")
    print(f"  Industry:  {item.industry}")

    assert item.title == "Snowflake Doubles Denver Office Footprint"
    assert item.publisher == "Bisnow"
    assert item.published == "2026-05-12"
    assert item.company_guess == "Snowflake"
    assert "<" not in item.summary  # HTML stripped

    row = item.to_inbox_row(suggested_match="CO-0003", confidence=88)
    print(f"\n  Inbox row:")
    for k, v in row.items():
        print(f"    {k}: {v}")
    assert row["source_name"] == "News: Bisnow"
    assert row["extracted_company"] == "Snowflake"
    assert row["suggested_match"] == "CO-0003"
    assert "Bisnow" in row["extracted_description"]
    assert "2026-05-12" in row["extracted_description"]
    print("\n✓ entry parsing + inbox row")


def test_publisher_fallback():
    # No source element; publisher inferred from ' - ' suffix
    entry = FakeEntry(
        title="Giant Group USA Relocating To Boulder - Denver Business Journal",
        link="https://news.google.com/rss/articles/XYZ",
        date=st(2026, 4, 2),
    )
    item = parse_entry(entry, query="q")
    assert item.publisher == "Denver Business Journal", item.publisher
    assert item.title == "Giant Group USA Relocating To Boulder"
    assert item.company_guess == "Giant Group USA"
    print("✓ publisher fallback via ' - ' suffix")


def test_negative_filtering():
    # Sports headlines rejected even though they match geo + a signal term
    sports = NewsItem(
        title="Schedule for Colorado Avalanche's Western Conference final games released",
        link="x", published=None, publisher="CBS", summary="",
    )
    assert not is_relevant(sports), "Avalanche/sports should be rejected"

    nwsl = NewsItem(
        title="Denver Summit and Boston Legacy show reward of NWSL expansion",
        link="x", published=None, publisher="ESPN", summary="",
    )
    assert not is_relevant(nwsl), "NWSL expansion should be rejected"

    # Restaurant / retail rejected
    deli = NewsItem(
        title="Call Your Mother Deli Plans Expansion in Denver",
        link="x", published=None, publisher="WhatNow", summary="",
    )
    assert not is_relevant(deli), "Deli should be rejected"

    # Aurora Innovation (trucking company) rejected despite 'Aurora' + 'expand'
    aurora_co = NewsItem(
        title="Aurora and Hirschbach Expand Driver As A Service Freight Ambitions",
        link="x", published=None, publisher="Yahoo Finance", summary="",
    )
    assert not is_relevant(aurora_co), "Aurora Innovation/Hirschbach should be rejected"

    # Residential rejected
    resi = NewsItem(
        title="Denver's Apiary Residences opens hotel-style rental community",
        link="x", published=None, publisher="ColoradoBiz", summary="",
    )
    assert not is_relevant(resi), "Residential should be rejected"

    # A genuine office relocation still passes
    good = NewsItem(
        title="Ramon.Space Expands U.S. Engineering Operations with New Denver-Area Office",
        link="x", published=None, publisher="SpaceWatch", summary="",
    )
    assert is_relevant(good), "Genuine office expansion should pass"

    # City-of-Aurora aerospace signal still passes (must not be harmed)
    aurora_city = NewsItem(
        title="Defense contractor leases new Aurora facility, adds 200 jobs",
        link="x", published=None, publisher="DBJ", summary="",
    )
    assert is_relevant(aurora_city), "City-of-Aurora aerospace signal must survive"
    print("✓ negative filtering (sports/food/residential/Aurora-collision)")


def test_industry_not_overgreedy():
    # 'office space' must NOT classify as Aerospace/Defense anymore
    from oedit_scraper import classify_industry
    assert classify_industry("leases Boulder space for new HQ") != "Aerospace/Defense"
    # genuine aerospace still classifies
    assert classify_industry("rocket engine company") == "Aerospace/Defense"
    assert classify_industry("aerospace and defense sector") == "Aerospace/Defense"
    print("✓ industry classifier no longer over-greedy on 'space'")


if __name__ == "__main__":
    test_company_guess()
    test_relevance()
    test_negative_filtering()
    test_industry_not_overgreedy()
    test_parse_entry()
    test_publisher_fallback()
    print("\n✓ All news scraper tests passed.")
