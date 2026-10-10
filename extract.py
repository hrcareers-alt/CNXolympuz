#!/usr/bin/env python3
"""
extract.py – Extract candidates that still need CNX upload.
"""

import os
import json
import re
import argparse
from datetime import datetime
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# CONFIG
# =========================================================
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
    import json
    from google.oauth2.service_account import Credentials

    # Prefer JSON content from environment variable (best for Cloud Agents)
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if sa_json:
        info = json.loads(sa_json)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        # Fallback to file (for local testing)
        creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
        creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    
    return gspread.authorize(creds)


def load_ledger():
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"uploaded": []}


def normalize_phone(raw: str) -> tuple[str | None, str]:
    """
    Returns (normalized_phone, status)
    status: OK | COERCED | HOLD
    """
    if not raw:
        return None, "HOLD"

    digits = "".join(c for c in str(raw) if c.isdigit())

    if len(digits) < 7:
        return None, "HOLD"

    if len(digits) > 10:
        digits = digits[-10:]

    if len(digits) == 10 and digits.startswith("9"):
        return "0" + digits, "OK"

    # Coerce to 09 + last 9 digits
    coerced = "09" + digits[-9:]
    return coerced, "COERCED"


def is_clearly_non_ph(location: str) -> bool:
    if not location:
        return False
    loc = location.lower()
    non_ph = [
        "india", "usa", "united states", "china", "singapore", "malaysia",
        "dubai", "uae", "canada", "australia", "uk", "united kingdom",
        "japan", "korea", "vietnam", "thailand", "indonesia", "hong kong"
    ]
    return any(k in loc for k in non_ph)


def clean_email(email: str) -> str:
    if not email:
        return ""
    email = str(email).strip().lower()
    email = email.replace("gmail.con", "gmail.com")
    email = email.replace("gamil.com", "gmail.com")
    email = email.replace("g,ail.com", "gmail.com")
    email = email.replace(" ", "")
    if "/" in email:
        parts = [part for part in email.split("/") if "@" in part]
        email = parts[0] if parts else email.split("/")[0]
    return email


# Work-setup answers are not part of an applicant's name. "Personal Details" on the
# Modern Traction / Jobstreet form is the first name. "Full Name" on that form is a
# character reference, or the work-setup answer when the columns are shifted.
_WORK_SETUP_RE = re.compile(
    r"work\s*from\s*home|work\s*at\s*home|work[\s-]*at\b|any\s+available\s+work|home[\s-]*based|\bwfh\b",
    re.IGNORECASE,
)
_SETUP_ONLY = {
    "onsite", "on-site", "on site", "hybrid", "wfh",
    "home based", "home-based", "work from home", "work at home",
}
_SETUP_NOISE = {"set", "up", "setup", "available", "any", "the", "and", "or"}
_FIRST_KEYS = ["first name", "referral first name", "given name", "first", "personal details"]
_LAST_KEYS = ["last name", "referral last name", "surname", "last"]
_FULL_KEYS = ["full name", "candidate name", "applicant name", "your complete name"]


def clean_person_name(value: str) -> str:
    """Keep a person's name. Drop a work-setup answer such as Work From Home."""
    text = " ".join(str(value or "").replace("\n", " ").split())
    if not text:
        return ""
    if text.lower().strip(" ./-") in _SETUP_ONLY:
        return ""
    if not _WORK_SETUP_RE.search(text):
        return text
    remainder = _WORK_SETUP_RE.sub(" ", text)
    remainder = re.sub(r"[/|]+", " ", remainder)
    words = []
    for word in remainder.split():
        token = word.strip(" -.,")
        if token and token.lower() not in _SETUP_NOISE:
            words.append(token)
    return " ".join(words)


def _row_value(row: dict, choices: list[str]) -> str:
    normalized = {}
    for key, value in row.items():
        name = " ".join(str(key or "").replace("\n", " ").split()).lower().rstrip(":").strip()
        if name and name not in normalized:
            normalized[name] = value
    for choice in choices:
        value = normalized.get(choice)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def applicant_names(row: dict) -> tuple[str, str]:
    """Applicant first and last name. Never a work setup or a reference name."""
    first = clean_person_name(_row_value(row, _FIRST_KEYS))
    last = clean_person_name(_row_value(row, _LAST_KEYS))
    if first and last:
        return first, last
    full = clean_person_name(_row_value(row, _FULL_KEYS))
    bits = full.split()
    if len(bits) >= 2:
        first = first or " ".join(bits[:-1])
        last = last or bits[-1]
    return first, last


def extract_candidates(read_plan: bool = False):
    client = get_client()
    ledger = load_ledger()
    already_done = {item["key"] for item in ledger.get("uploaded", [])}

    results = []

    for sheet_id in SHEET_IDS:
        try:
            spreadsheet = client.open_by_key(sheet_id)
        except Exception as e:
            print(f"❌ Cannot open sheet {sheet_id}: {e}")
            continue

        print(f"\n📄 {spreadsheet.title}")

        for ws in spreadsheet.worksheets():
            try:
                headers = [h.strip() if h else "" for h in ws.row_values(1)]
                if "CNX" not in headers:
                    continue

                cnx_col = headers.index("CNX") + 1
                print(f"  → {ws.title} (CNX col {cnx_col})")

                records = ws.get_all_records()

                for idx, row in enumerate(records, start=2):
                    cnx_value = str(row.get("CNX", "")).strip()
                    if cnx_value:
                        continue

                    first, last = applicant_names(row)
                    email = clean_email(
                        row.get("Email") or row.get("email") or row.get("Email Address") or ""
                    )
                    phone_raw = str(
                        row.get("Mobile") or row.get("Phone") or row.get("mobile") or
                        row.get("Contact Number") or row.get("Contact") or ""
                    )
                    location = str(
                        row.get("Location") or row.get("City") or row.get("location") or
                        row.get("City/Municipality") or row.get("Address") or ""
                    )

                    if not any([first, last, email]):
                        continue

                    key = f"{email}|{phone_raw}|{first}|{last}".lower()
                    if key in already_done:
                        continue

                    # Non-PH check
                    if is_clearly_non_ph(location):
                        results.append({
                            "sheet_id": sheet_id,
                            "sheet_title": spreadsheet.title,
                            "tab": ws.title,
                            "row": idx,
                            "cnx_col": cnx_col,
                            "status": "INVALID",
                            "first_name": first,
                            "last_name": last,
                            "email": email,
                            "phone": None,
                            "location": location,
                            "key": key,
                            "raw": row,
                        })
                        continue

                    phone, phone_status = normalize_phone(phone_raw)

                    item = {
                        "sheet_id": sheet_id,
                        "sheet_title": spreadsheet.title,
                        "tab": ws.title,
                        "row": idx,
                        "cnx_col": cnx_col,
                        "first_name": first,
                        "last_name": last,
                        "email": email,
                        "phone": phone,
                        "phone_status": phone_status,
                        "location": location,
                        "key": key,
                        "status": "READY" if phone else "HOLD",
                        "raw": row,
                    }
                    results.append(item)

            except Exception as e:
                print(f"  ⚠️  Error on tab {ws.title}: {e}")

    if read_plan:
        ready = [r for r in results if r["status"] == "READY"]
        hold = [r for r in results if r["status"] == "HOLD"]
        invalid = [r for r in results if r["status"] == "INVALID"]
        print(f"\n📋 Plan Summary")
        print(f"  READY   : {len(ready)}")
        print(f"  HOLD    : {len(hold)}")
        print(f"  INVALID : {len(invalid)}")
        return results

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-plan", action="store_true", help="Only show plan, do not process")
    args = parser.parse_args()

    extract_candidates(read_plan=args.read_plan)
