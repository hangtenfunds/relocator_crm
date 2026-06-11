"""
ATS watch-list — the boards the ATS collector monitors.

HOW TO ADD A BOARD
------------------
On a company's careers page, click into any individual job posting and look
at the URL of the job detail page:
  boards.greenhouse.io/X/jobs/...         -> ats="greenhouse", token="X"
  job-boards.greenhouse.io/X/jobs/...     -> ats="greenhouse", token="X"
  jobs.lever.co/X/...                     -> ats="lever",      token="X"
  X.wd1.myworkdayjobs.com/...             -> Workday (NOT SUPPORTED — skip)
  X.ashbyhq.com/...                       -> Ashby (NOT SUPPORTED — skip)
  Custom URL on the company's domain      -> in-house ATS (NOT SUPPORTED — skip)

If you're not sure a token resolves, run the verifier:
  python verify_watchlist.py

It pings every board and prints a clean table of which work, which return
no Front-Range jobs, and which 404. Use that to prune broken entries.

TYPES
-----
  "company"   -> potential relocation client. One summary Inbox row per run.
  "recruiter" -> potential referral PARTNER (not a relocation client).

WHAT TO EXPECT
--------------
This tool covers the Greenhouse + Lever universe — primarily growth-stage
tech and startups. The 1,000+ employee established companies (Gusto, Pax8,
Ibotta, JumpCloud, Quantum Metric, SonderMind, Ping Identity, Maxar, and
the defense primes like Lockheed/Northrop/Raytheon) are on Workday, which
this tool doesn't cover. For those, rely on OEDIT decisions, news signals,
and direct outreach instead.

SEEDING STRATEGY
----------------
The highest-value seed is the companies already in your CRM. When you add
a company to the Companies tab, do the 30-second URL check above. If they
land on Greenhouse or Lever, add them here. If they land on Workday or
an in-house system, note that in the company's CRM record and skip.
"""

WATCHLIST = [
    # --- Verified Greenhouse/Lever boards (from the first dry run) ---
    # These resolved with Front-Range relocation-language postings. Add more
    # as you verify additional companies via the workflow described above.
    {"name": "Checkr", "ats": "greenhouse", "token": "checkr", "type": "company"},
    {"name": "Guild",  "ats": "greenhouse", "token": "guild",  "type": "company"},

    # --- Add more verified entries here, one per line. Examples of the shape:
    # {"name": "Acme Corp",     "ats": "greenhouse", "token": "acmecorp",    "type": "company"},
    # {"name": "Beta Labs",     "ats": "lever",      "token": "betalabs",    "type": "company"},

    # --- Recruiter / staffing boards (most retained-search firms are NOT on
    #     these APIs — see recruiter_starter_list.csv for those).
    # {"name": "Example Staffing", "ats": "lever", "token": "examplestaffing", "type": "recruiter"},
]
