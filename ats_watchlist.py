"""
ATS watch-list — the boards the ATS collector monitors.

HOW TO ADD A BOARD
------------------
Find a company's careers page. If the URL looks like:
  boards.greenhouse.io/acmecorp   -> ats="greenhouse", token="acmecorp"
  jobs.lever.co/acmecorp          -> ats="lever",      token="acmecorp"
...then add an entry below. The token is the last path segment.

If you're not sure a token is valid, run:
  python main.py --only ats --dry-run -v
Invalid tokens just log a 404 and are skipped — they won't break the run.

TYPES
-----
  "company"  -> a potential relocation client. Emits an Inbox row for each
                Front-Range posting that mentions employer relocation.
  "recruiter"-> a potential referral PARTNER. Emits a summary row when the
                firm is actively posting Front-Range roles.

SEEDING STRATEGY
----------------
The highest-value seed is the companies already in your CRM. When you add a
company to the Companies tab, check their careers page and add their board
here too — then the ATS collector starts watching their hiring automatically.

The entries below are STARTER EXAMPLES of well-known Colorado-presence tech
employers. TOKENS ARE BEST-GUESSES AND MUST BE VERIFIED — run a dry run and
prune whatever 404s. They're here to give you a working starting point, not a
vetted list.
"""

WATCHLIST = [
    # --- Company boards (verify tokens via a dry run; prune 404s) ---
    {"name": "Gusto",            "ats": "greenhouse", "token": "gusto",          "type": "company"},
    {"name": "Guild",            "ats": "greenhouse", "token": "guild",          "type": "company"},
    {"name": "Ibotta",           "ats": "greenhouse", "token": "ibotta",         "type": "company"},
    {"name": "Pax8",             "ats": "greenhouse", "token": "pax8",           "type": "company"},
    {"name": "JumpCloud",        "ats": "greenhouse", "token": "jumpcloud",      "type": "company"},
    {"name": "Checkr",           "ats": "greenhouse", "token": "checkr",         "type": "company"},
    {"name": "Quantum Metric",   "ats": "lever",      "token": "quantummetric",  "type": "company"},
    {"name": "SonderMind",       "ats": "greenhouse", "token": "sondermind",     "type": "company"},
    {"name": "Ping Identity",    "ats": "greenhouse", "token": "pingidentity",   "type": "company"},
    {"name": "Maxar",            "ats": "greenhouse", "token": "maxar",          "type": "company"},

    # --- Recruiter / staffing boards (examples; most retained-search firms
    #     are NOT on these APIs — see the recruiter starter list for those) ---
    # {"name": "Example Staffing", "ats": "lever",     "token": "examplestaffing", "type": "recruiter"},
]
