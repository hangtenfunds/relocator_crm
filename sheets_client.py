"""
Reusable Sheets client for the relocation CRM.

Exposes high-level operations on the Companies, Signals, Inbox, and
Inbox_Archive tabs. Future scrapers (Bisnow, BusinessDen, etc.) should
import from here rather than talking to gspread directly.
"""

from __future__ import annotations

import logging
from typing import Optional

import gspread
from google.oauth2.service_account import Credentials

from config import SPREADSHEET_ID, get_credentials_dict

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient:
    """Wrapper around gspread with CRM-specific helpers."""

    def __init__(self):
        creds_dict = get_credentials_dict()
        if not creds_dict:
            raise RuntimeError("No credentials available; check config.")
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(SPREADSHEET_ID)
        self._tab_cache = {}

    def _tab(self, name: str):
        if name not in self._tab_cache:
            self._tab_cache[name] = self._spreadsheet.worksheet(name)
        return self._tab_cache[name]

    # ----- Reads ---------------------------------------------------------

    def get_companies(self) -> list[dict]:
        """Returns all companies as [{company_id, name}, ...]."""
        tab = self._tab("Companies")
        all_values = tab.get_all_values()
        if len(all_values) < 2:
            return []
        # Columns: A=company_id, B=name
        return [
            {"company_id": row[0], "name": row[1]}
            for row in all_values[1:]
            if len(row) >= 2 and row[0]
        ]

    def get_signal_source_urls(self) -> set[str]:
        """Returns set of source URLs already in Signals (for dedup)."""
        tab = self._tab("Signals")
        all_values = tab.get_all_values()
        if len(all_values) < 2:
            return set()
        # Column G (index 6) = source_url
        return {row[6] for row in all_values[1:] if len(row) >= 7 and row[6]}

    def get_inbox_keys(self) -> set[tuple[str, str]]:
        """Returns set of (source_url, extracted_company) tuples already in Inbox."""
        tab = self._tab("Inbox")
        all_values = tab.get_all_values()
        if len(all_values) < 2:
            return set()
        # D=source_url (idx 3), E=extracted_company (idx 4)
        return {
            (row[3], row[4])
            for row in all_values[1:]
            if len(row) >= 5 and row[3] and row[4]
        }

    def get_archive_keys(self) -> set[tuple[str, str]]:
        """Returns set of (source_url, extracted_company) tuples in Inbox_Archive."""
        try:
            tab = self._tab("Inbox_Archive")
        except gspread.WorksheetNotFound:
            return set()
        all_values = tab.get_all_values()
        if len(all_values) < 2:
            return set()
        return {
            (row[3], row[4])
            for row in all_values[1:]
            if len(row) >= 5 and row[3] and row[4]
        }

    # ----- Writes --------------------------------------------------------

    def append_inbox_rows(self, rows: list[dict]) -> int:
        """
        Append rows to the Inbox tab. Each row is a dict with keys matching
        the Inbox columns: source_name, source_url, extracted_company,
        extracted_description, extracted_jobs, extracted_county,
        suggested_match, match_confidence.

        Returns the number of rows actually appended (after dedup).
        """
        if not rows:
            return 0

        existing_inbox = self.get_inbox_keys()
        existing_archive = self.get_archive_keys()
        existing_urls = self.get_signal_source_urls()

        new_rows = []
        for r in rows:
            url = r.get("source_url", "")
            company = r.get("extracted_company", "")
            key = (url, company)
            # Dedup: skip if URL already in Signals (already processed manually),
            # or if (URL, company) already in Inbox or Archive
            if url and url in existing_urls:
                log.info("Skip (already in Signals): %s", company)
                continue
            if key in existing_inbox:
                log.info("Skip (already in Inbox): %s", company)
                continue
            if key in existing_archive:
                log.info("Skip (already in Archive): %s", company)
                continue
            new_rows.append(self._inbox_row_to_list(r))

        if not new_rows:
            return 0

        tab = self._tab("Inbox")
        # Use USER_ENTERED so dates and URLs render natively
        tab.append_rows(new_rows, value_input_option="USER_ENTERED")
        return len(new_rows)

    @staticmethod
    def _inbox_row_to_list(r: dict) -> list:
        """
        Convert a row dict into the column order the Inbox tab expects.
        Columns:
          A: inbox_id (left blank — Apps Script onEdit will fill)
          B: found_at (left blank — Apps Script will fill)
          C: source_name
          D: source_url
          E: extracted_company
          F: extracted_description
          G: extracted_jobs
          H: extracted_county
          I: suggested_match
          J: match_confidence
          K: action (default Pending)
          L: linked_company_id (blank)
          M: notes
        """
        return [
            "",  # A inbox_id
            "",  # B found_at
            r.get("source_name", ""),
            r.get("source_url", ""),
            r.get("extracted_company", ""),
            r.get("extracted_description", ""),
            r.get("extracted_jobs", "") or "",
            r.get("extracted_county", ""),
            r.get("suggested_match", ""),
            r.get("match_confidence", "") or "",
            "Pending",
            "",  # L linked_company_id
            r.get("notes", ""),
        ]
