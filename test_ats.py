"""
ATS scraper test — synthetic Greenhouse/Lever payloads, no network.
Verifies normalization, Front-Range filtering, relocation detection, and
company-vs-recruiter routing/inbox rows.
"""

import sys
sys.path.insert(0, ".")

from ats_scraper import (
    normalize_greenhouse, normalize_lever, is_front_range,
    mentions_relocation, fetch_board, scrape_ats,
    CompanyHiringActivity, RecruiterActivity,
)

# --- Synthetic Greenhouse payload (company) ---
GH = {
    "jobs": [
        {
            "title": "Senior Systems Engineer",
            "location": {"name": "Aurora, CO"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
            "content": "Great role. We offer relocation assistance for the right candidate.",
            "updated_at": "2026-05-20T12:00:00Z",
        },
        {
            "title": "Marketing Manager",
            "location": {"name": "Denver, CO"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
            "content": "Local hire. No relocation mentioned here.",
            "updated_at": "2026-05-18T12:00:00Z",
        },
        {
            "title": "Sales Rep",
            "location": {"name": "Austin, TX"},
            "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
            "content": "Includes relocation package.",  # relo but not Front Range
            "updated_at": "2026-05-10T12:00:00Z",
        },
    ]
}

# --- Synthetic Lever payload (recruiter) ---
LEVER = [
    {
        "text": "VP Engineering (Confidential Client)",
        "categories": {"location": "Denver, Colorado"},
        "hostedUrl": "https://jobs.lever.co/recruitco/abc",
        "descriptionPlain": "Our client offers a generous relocation package.",
        "createdAt": 1747000000000,
    },
    {
        "text": "Controller",
        "categories": {"location": "Boulder, CO"},
        "hostedUrl": "https://jobs.lever.co/recruitco/def",
        "descriptionPlain": "Local search.",
        "createdAt": 1747000000000,
    },
    {
        "text": "Remote SWE",
        "categories": {"location": "Remote - US"},
        "hostedUrl": "https://jobs.lever.co/recruitco/ghi",
        "descriptionPlain": "Anywhere in the US.",  # remote, no CO tie -> excluded
        "createdAt": 1747000000000,
    },
]


def test_normalize_and_filters():
    gh = normalize_greenhouse(GH)
    assert len(gh) == 3
    assert gh[0]["title"] == "Senior Systems Engineer"
    assert gh[0]["posted_at"] == "2026-05-20"

    # Front Range filtering
    assert is_front_range(gh[0]) is True       # Aurora, CO
    assert is_front_range(gh[1]) is True        # Denver, CO
    assert is_front_range(gh[2]) is False       # Austin, TX

    # Relocation detection
    assert mentions_relocation(gh[0]) is True
    assert mentions_relocation(gh[1]) is False
    assert mentions_relocation(gh[2]) is True   # has relo, but not FR

    lev = normalize_lever(LEVER)
    assert len(lev) == 3
    assert is_front_range(lev[0]) is True        # Denver, Colorado
    assert is_front_range(lev[2]) is False       # Remote - US, no CO tie
    assert mentions_relocation(lev[0]) is True
    print("✓ normalize + Front-Range + relocation filters")


def test_fetch_board_injection():
    gh = fetch_board("greenhouse", "acme", _raw=GH)
    assert len(gh) == 3
    lev = fetch_board("lever", "recruitco", _raw=LEVER)
    assert len(lev) == 3
    # Unknown ATS returns empty, doesn't crash
    assert fetch_board("workday", "x", _raw=[]) == []
    print("✓ fetch_board payload injection + unknown-ATS safety")


def test_company_inbox_row_with_relo():
    activity = CompanyHiringActivity(
        org_name="Acme Corp",
        board_url="https://boards.greenhouse.io/acme",
        ats="greenhouse",
        front_range_count=12,
        relocation_count=8,
        sample_relo_titles=["Staff Engineer", "Director, RevOps", "Senior PM"],
        sample_fr_titles=["Staff Engineer", "Director, RevOps", "Senior PM", "Marketing Manager"],
    )
    row = activity.to_inbox_row(suggested_match="CO-0009", confidence=95)
    assert row["extracted_company"] == "Acme Corp"
    assert "12 Front-Range" in row["extracted_description"]
    assert "8 explicitly offer relocation" in row["extracted_description"]
    assert row["extracted_jobs"] == 12
    assert row["suggested_match"] == "CO-0009"
    assert "Tier 1" in row["notes"]
    print("✓ company hiring summary -> inbox row (with relocation)")


def test_company_inbox_row_no_relo():
    activity = CompanyHiringActivity(
        org_name="Beta LLC",
        board_url="https://boards.greenhouse.io/beta",
        ats="greenhouse",
        front_range_count=3,
        relocation_count=0,
        sample_relo_titles=[],
        sample_fr_titles=["Local Sales Rep", "Office Manager"],
    )
    row = activity.to_inbox_row()
    assert "no relocation language detected" in row["extracted_description"]
    assert "Lower priority" in row["notes"]
    print("✓ company hiring summary -> inbox row (no relocation)")


def test_one_row_per_company_end_to_end():
    """The full pipeline should emit ONE row per company, regardless of how
    many roles match — the fix for the 22-Checkr-rows issue."""
    watchlist = [
        {"name": "Acme", "ats": "greenhouse", "token": "acme", "type": "company"},
    ]
    # Inject 22 matching jobs to mirror the real Checkr scenario
    big_payload = {
        "jobs": [
            {
                "title": f"Role {i}",
                "location": {"name": "Denver, Colorado, United States"},
                "absolute_url": f"https://x/{i}",
                "content": "We offer relocation assistance.",
                "updated_at": "2026-06-04T00:00:00Z",
            }
            for i in range(22)
        ]
    }
    # Monkey-patch fetch_board to return our payload
    import ats_scraper
    orig = ats_scraper.fetch_board
    ats_scraper.fetch_board = lambda ats, tok: ats_scraper.normalize_greenhouse(big_payload)
    try:
        out = scrape_ats(watchlist=watchlist)
    finally:
        ats_scraper.fetch_board = orig

    assert len(out) == 1, f"Expected 1 collapsed row, got {len(out)}"
    activity = out[0]
    assert isinstance(activity, CompanyHiringActivity)
    assert activity.front_range_count == 22
    assert activity.relocation_count == 22
    print("✓ end-to-end: 22 matching jobs collapse to 1 Inbox row")


def test_recruiter_inbox_row():
    rec = RecruiterActivity(
        org_name="RecruitCo", board_url="https://jobs.lever.co/recruitco",
        ats="lever", front_range_count=5, relocation_count=2,
        sample_titles=["VP Engineering", "Controller", "Data Lead"],
    )
    row = rec.to_inbox_row()
    assert "RECRUITER" in row["extracted_description"]
    assert "2 mention relocation" in row["extracted_description"]
    assert row["source_name"].startswith("Recruiter (ATS):")
    assert "Recruiters tab" in row["notes"]
    print("✓ recruiter RecruiterActivity -> inbox row")


if __name__ == "__main__":
    test_normalize_and_filters()
    test_fetch_board_injection()
    test_company_inbox_row_with_relo()
    test_company_inbox_row_no_relo()
    test_recruiter_inbox_row()
    test_one_row_per_company_end_to_end()
    print("\n✓ All ATS scraper tests passed.")
