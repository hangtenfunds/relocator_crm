"""
Configuration for the relocation scrapers.

Loads credentials and settings from environment variables. For local
development, put values in a .env file (see .env.example).
"""

import json
import os
from pathlib import Path

# Load .env for local development. In production (GitHub Actions),
# environment variables are set directly by the runner.
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed, that's fine in production


# --- Required settings ---

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "").strip()

# Credentials can be provided two ways:
#   1. GOOGLE_SHEETS_CREDENTIALS_JSON: the full service account JSON as a string
#   2. GOOGLE_APPLICATION_CREDENTIALS: path to a JSON file on disk
def get_credentials_dict():
    """Returns the service account credentials as a dict, or None if missing."""
    json_str = os.environ.get("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
    if json_str:
        return json.loads(json_str)

    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path and Path(path).exists():
        with open(path) as f:
            return json.load(f)

    return None


def validate_config():
    """Raises a friendly error if config is missing."""
    errors = []
    if not SPREADSHEET_ID:
        errors.append("SPREADSHEET_ID is not set. Find it in your Sheet URL: "
                      "docs.google.com/spreadsheets/d/<THIS_PART>/edit")
    if not get_credentials_dict():
        errors.append("No Google credentials found. Set either "
                      "GOOGLE_SHEETS_CREDENTIALS_JSON (the JSON content) or "
                      "GOOGLE_APPLICATION_CREDENTIALS (path to a JSON file).")
    if errors:
        msg = "Configuration errors:\n  - " + "\n  - ".join(errors)
        msg += "\n\nSee README.md for setup instructions."
        raise RuntimeError(msg)
