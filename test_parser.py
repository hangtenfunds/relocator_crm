"""
Parser test: feed synthetic HTML that mirrors real OEDIT page structure
and verify each field is extracted correctly. Doesn't need network or
rapidfuzz (just the parsing functions).
"""

import sys
sys.path.insert(0, ".")

# Stub rapidfuzz so oedit_scraper imports work even without it installed
import types
fake_rapidfuzz = types.ModuleType("rapidfuzz")
fake_rapidfuzz.fuzz = types.SimpleNamespace(WRatio=lambda a, b: 0)
fake_rapidfuzz.process = types.SimpleNamespace(extractOne=lambda *a, **k: None)
sys.modules["rapidfuzz"] = fake_rapidfuzz

from oedit_scraper import parse_projects, parse_meeting_date
from bs4 import BeautifulSoup

# Synthetic HTML modeled on the real April 2026 page structure
SAMPLE_HTML = """
<html><body>
<h1>April 2026: EDC Approved Job Growth Incentive Tax Credit Projects</h1>
<p>Thursday, April 16, 2026</p>
<p>The following projects were approved at the April 2026 meeting.</p>

<h2>Project Name: Hera</h2>
<h3>Summary</h3>
<p>The company behind Project Hera is focused on researching, designing, developing,
manufacturing, and maintaining cutting-edge technology systems for the aerospace
and defense sector. Due to the nature of the company, further identification would
jeopardize confidentiality.</p>
<p>These growth opportunities could potentially lead to the creation of up to
approximately 1,250 net-new jobs over the next four years. In addition to Colorado,
the company is considering Alabama, Florida, and Pennsylvania. Within Colorado, the
company is considering Douglas County and/or Jefferson County.</p>
<h3>Jobs</h3>
<p>Project Hera, should it occur in Colorado, expects to create 1,250 net new jobs
at an average annual wage of $122,043.08, which is 108% of the average annual wage
in Broomfield County. The jobs include Cybersecurity Engineers, Software Engineers,
Technicians, and Administrative Services.</p>
<h3>Incentive</h3>
<p>Up to $26,593,422 in performance-based Job Growth Incentive Tax Credits over an
8-year period, 96 months, is requested from the EDC.</p>

<h2>Project Name: Quantum Spark</h2>
<h3>Summary</h3>
<p>The company behind Project Quantum Spark builds quantum computing infrastructure.
Considering Boulder County.</p>
<h3>Jobs</h3>
<p>The creation of up to 150 net new full-time jobs at a minimum average annual
wage of $97,721 (100% of Boulder County).</p>
<h3>Incentive</h3>
<p>Up to $2,760,641 in performance-based Job Growth Incentive Tax Credits.</p>

<h2>Recent</h2>
<p>This is a sidebar that should NOT be parsed as a project.</p>
</body></html>
"""


def test():
    soup = BeautifulSoup(SAMPLE_HTML, "html.parser")
    meeting_date = parse_meeting_date(soup)
    print(f"Meeting date parsed: {meeting_date}")
    assert meeting_date == "2026-04-16", f"Expected 2026-04-16, got {meeting_date}"

    projects = parse_projects(SAMPLE_HTML, "https://example.test/oedit-april-2026")
    print(f"\nProjects parsed: {len(projects)}")
    assert len(projects) == 2, f"Expected 2 projects, got {len(projects)}"

    # Project 1: Hera
    p = projects[0]
    print(f"\n--- Project 1 ---")
    print(f"  Display name: {p.display_name}")
    print(f"  Company name: {p.company_name}")
    print(f"  Job count:    {p.job_count}")
    print(f"  Incentive:    ${p.incentive_amount:,}" if p.incentive_amount else "  Incentive: None")
    print(f"  Counties:     {p.counties}")
    print(f"  Competing:    {p.competing_states}")
    print(f"  Industry:     {p.industry}")
    print(f"  Front Range:  {p.is_front_range}")
    print(f"  Denver Metro: {p.is_denver_metro}")

    assert p.display_name == "Project Hera", f"Got {p.display_name!r}"
    assert p.company_name is None, "Hera should be confidential"
    assert p.job_count == 1250, f"Expected 1250, got {p.job_count}"
    assert p.incentive_amount == 26593422, f"Expected 26593422, got {p.incentive_amount}"
    assert set(p.counties) == {"Douglas", "Jefferson"}, f"Got {p.counties}"
    assert "Alabama" in p.competing_states, f"Got {p.competing_states}"
    assert "Florida" in p.competing_states
    assert "Pennsylvania" in p.competing_states
    assert p.industry == "Aerospace/Defense", f"Got {p.industry}"
    assert p.is_denver_metro, "Douglas/Jefferson should be Denver Metro"

    # Project 2: Quantum Spark
    p2 = projects[1]
    print(f"\n--- Project 2 ---")
    print(f"  Display name: {p2.display_name}")
    print(f"  Job count:    {p2.job_count}")
    print(f"  Counties:     {p2.counties}")
    print(f"  Industry:     {p2.industry}")

    assert p2.display_name == "Project Quantum Spark", f"Got {p2.display_name!r}"
    assert p2.job_count == 150, f"Expected 150, got {p2.job_count}"
    assert "Boulder" in p2.counties, f"Got {p2.counties}"
    assert p2.industry == "AI/ML", f"Got {p2.industry}"  # 'quantum' matches

    # Inbox row generation
    row = projects[0].to_inbox_row(suggested_match="CO-0007", confidence=92)
    print(f"\n--- Inbox row (Hera) ---")
    for k, v in row.items():
        print(f"  {k}: {v}")

    assert row["source_name"] == "OEDIT EDC"
    assert row["extracted_company"] == "Project Hera"
    assert row["extracted_jobs"] == 1250
    assert row["suggested_match"] == "CO-0007"
    assert row["match_confidence"] == 92
    assert "Aerospace/Defense" in row["extracted_description"]
    assert "Incentive: $26,593,422" in row["notes"]

    print("\n✓ All parser tests passed.")


if __name__ == "__main__":
    test()
