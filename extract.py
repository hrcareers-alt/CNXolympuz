#!/usr/bin/env python3
"""
extract.py – Extract candidates that still need CNX upload.
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# -------------------------------------------------
# Config
# -------------------------------------------------
SHEET_IDS = [
    "1NoRX955F0dpxMReiC-6lcd3hgxFDccS3H9hzabTQghE",  # Apply or Refer & EARN
    "12B9N-5AGpWBT8R1ePXBZIwnFmBC7MadIPo5NESUbAuw",  # DIRECT SOURCING TRACTION
    "1PYPebwsRPiO8y7ogsMegRpSFmR3E84gGPnJohcjm04o",  # Apply For A Job Across All Partners
]

LEDGER_FILE = Path("uploaded.json")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def get_client():
    # Prefer service account if available, otherwise you can switch to oauth
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return gspread.authorize(creds)


def load_ledger():
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE) as f:
            return json.load(f)
    return {"uploaded": [], "last_run": None}


def normalize_phone(raw: str) -> tuple[str | None, str | None]:
    """
    Returns (normalized_phone, status)
    status can be: OK, COERCED, INVALID, HOLD
    """
    if not raw:
        return None, "HOLD"

    digits = "".join(c for c in str(raw) if c.isdigit())

    if len(digits) < 7:
        return None, "HOLD"

    # Take last 10 digits if longer
    if len(digits) > 10:
        digits = digits[-10:]

    if len(digits) == 10 and digits.startswith("9"):
        return "0" + digits, "OK"

    if len(digits) >= 7:
        # Coerce: 09 + last 9 digits
        coerced = "09" + digits[-9:]
        return coerced, "COERCED"

    return None, "HOLD"


def is_philippines(location: str) -> bool | None:
    """
    True  = clearly PH
    False = clearly not PH
    None  = ambiguous → treat as PH
    """
    if not location:
        return None

    loc = location.lower().strip()

    non_ph_keywords = [
        "india", "usa", "united states", "china", "singapore",
        "malaysia", "dubai", "uae", "canada", "australia",
        "uk", "united kingdom", "japan", "korea"
    ]
    for kw in non_ph_keywords:
        if kw in loc:
            return False

    return True  # ambiguous or clearly PH


def extract_candidates(read_plan: bool = False):
    client = get_client()
    ledger = load_ledger()
    already_done = {item["key"] for item in ledger.get("uploaded", [])}

    results = []

    for sheet_id in SHEET_IDS:
        spreadsheet = client.open_by_key(sheet_id)
        print(f"\n📄 Processing: {spreadsheet.title}")

        for worksheet in spreadsheet.worksheets():
            # Find CNX column
            headers = worksheet.row_values(1)
            try:
                cnx_col = headers.index("CNX") + 1  # 1-based
            except ValueError:
                continue  # no CNX column

            print(f"  → Tab: {worksheet.title} (CNX column {cnx_col})")

            # Get all values
            rows = worksheet.get_all_records()

            for idx, row in enumerate(rows, start=2):  # row 1 is header
                # Skip if already has remark
                cnx_value = str(row.get("CNX", "")).strip()
                if cnx_value:
                    continue

                # Build identity key
                email = str(row.get("Email") or row.get("email") or "").strip().lower()
                phone = str(row.get("Mobile") or row.get("Phone") or row.get("mobile") or "")
                first = str(row.get("First Name") or row.get("first_name") or "").strip()
                last = str(row.get("Last Name") or row.get("last_name") or "").strip()

                key = f"{email}|{phone}|{first}|{last}".lower()
                if key in already_done:
                    continue

                # Non-PH check
                location = str(row.get("Location") or row.get("City") or row.get("location") or "")
                ph_status = is_philippines(location)
                if ph_status is False:
                    results.append({
                        "sheet": spreadsheet.title,
                        "tab": worksheet.title,
                        "row": idx,
                        "status": "INVALID",
                        "reason": "Non-PH",
                        "data": row,
                    })
                    continue

                # Phone normalization
                norm_phone, phone_status = normalize_phone(phone)

                candidate = {
                    "sheet": spreadsheet.title,
                    "tab": worksheet.title,
                    "row": idx,
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "phone": norm_phone,
                    "phone_status": phone_status,
                    "location": location,
                    "raw": row,
                }

                if phone_status == "HOLD":
                    candidate["status"] = "HOLD"
                else:
                    candidate["status"] = "READY"

                results.append(candidate)

    if read_plan:
        print("\n📋 Extraction Plan:")
        ready = [r for r in results if r.get("status") == "READY"]
        hold = [r for r in results if r.get("status") == "HOLD"]
        invalid = [r for r in results if r.get("status") == "INVALID"]
        print(f"  READY   : {len(ready)}")
        print(f"  HOLD    : {len(hold)}")
        print(f"  INVALID : {len(invalid)}")
        return results

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-plan", action="store_true", help="Only show what would be processed")
    args = parser.parse_args()

    extract_candidates(read_plan=args.read_plan)
