#!/usr/bin/env python3
"""
CNX Uploader for Olympuz
- Reads the 3 Google Sheets
- Finds blank CNX rows
- Cleans phone/email
- Uploads to Talkpush agency portal
- Writes remarks back
- Has proper locking + logging
"""

import os
import sys
import json
import time
import fcntl
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
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

PORTAL_URL = "https://agencyportaltalkpush.replit.app/candidates"
LOGIN_EMAIL = "nickisabelo@olympuz-org.com"
PASSWORD = os.getenv("TALKPUSH_PASSWORD")

LOCK_FILE = Path(".upload.lock")
LEDGER_FILE = Path("uploaded.json")
PROGRESS_LOG = Path("progress.log")
FIXES_LOG = Path("fixes.log")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# =========================================================
# HELPERS
# =========================================================
def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def log_fix(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(FIXES_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


def acquire_lock():
    """Return lock file object if we got the lock, else None"""
    LOCK_FILE.parent.mkdir(exist_ok=True)
    lock_fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fp.write(str(os.getpid()))
        lock_fp.flush()
        return lock_fp
    except BlockingIOError:
        lock_fp.close()
        return None


def release_lock(lock_fp):
    if lock_fp:
        fcntl.flock(lock_fp, fcntl.LOCK_UN)
        lock_fp.close()
        if LOCK_FILE.exists():
            LOCK_FILE.unlink()


def get_gspread_client():
    creds_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
    return gspread.authorize(creds)


def load_ledger():
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"uploaded": []}


def save_ledger(ledger):
    with open(LEDGER_FILE, "w", encoding="utf-8") as f:
        json.dump(ledger, f, indent=2, ensure_ascii=False)


def normalize_phone(raw: str):
    """Returns (phone_09x, status)  status = OK | COERCED | HOLD"""
    if not raw:
        return None, "HOLD"

    digits = "".join(c for c in str(raw) if c.isdigit())
    if len(digits) < 7:
        return None, "HOLD"

    if len(digits) > 10:
        digits = digits[-10:]

    if len(digits) == 10 and digits.startswith("9"):
        return "0" + digits, "OK"

    # Coerce
    coerced = "09" + digits[-9:]
    return coerced, "COERCED"


def is_clearly_non_ph(location: str) -> bool:
    if not location:
        return False
    loc = location.lower()
    keywords = [
        "india", "usa", "united states", "china", "singapore", "malaysia",
        "dubai", "uae", "canada", "australia", "uk", "united kingdom",
        "japan", "korea", "vietnam", "thailand", "indonesia"
    ]
    return any(k in loc for k in keywords)


def clean_email(email: str) -> str:
    if not email:
        return ""
    email = email.strip().lower()
    # Common fixes
    email = email.replace("gmail.con", "gmail.com").replace("gamil.com", "gmail.com")
    email = email.replace("g,ail.com", "gmail.com").replace(" ", "")
    return email


# =========================================================
# MAIN LOGIC
# =========================================================
def extract_ready_candidates(client):
    ledger = load_ledger()
    already = {item["key"] for item in ledger.get("uploaded", [])}
    ready = []

    for sheet_id in SHEET_IDS:
        try:
            spreadsheet = client.open_by_key(sheet_id)
        except Exception as e:
            log(f"ERROR opening sheet {sheet_id}: {e}")
            continue

        log(f"Scanning: {spreadsheet.title}")

        for ws in spreadsheet.worksheets():
            try:
                headers = [h.strip() for h in ws.row_values(1)]
                if "CNX" not in headers:
                    continue

                cnx_col = headers.index("CNX") + 1
                records = ws.get_all_records()

                for i, row in enumerate(records, start=2):
                    cnx_val = str(row.get("CNX", "")).strip()
                    if cnx_val:
                        continue

                    first = str(row.get("First Name") or row.get("first_name") or row.get("First") or "").strip()
                    last  = str(row.get("Last Name") or row.get("last_name") or row.get("Last") or "").strip()
                    email = clean_email(str(row.get("Email") or row.get("email") or ""))
                    phone_raw = str(row.get("Mobile") or row.get("Phone") or row.get("mobile") or row.get("Contact Number") or "")
                    location = str(row.get("Location") or row.get("City") or row.get("location") or row.get("City/Municipality") or "")

                    if not first and not last and not email:
                        continue

                    key = f"{email}|{phone_raw}|{first}|{last}".lower()
                    if key in already:
                        continue

                    # Non-PH check
                    if is_clearly_non_ph(location):
                        ready.append({
                            "sheet_id": sheet_id,
                            "sheet_title": spreadsheet.title,
                            "tab": ws.title,
                            "row": i,
                            "cnx_col": cnx_col,
                            "status": "INVALID",
                            "first_name": first,
                            "last_name": last,
                            "email": email,
                            "phone": None,
                            "location": location,
                            "key": key,
                        })
                        continue

                    phone, phone_status = normalize_phone(phone_raw)

                    item = {
                        "sheet_id": sheet_id,
                        "sheet_title": spreadsheet.title,
                        "tab": ws.title,
                        "row": i,
                        "cnx_col": cnx_col,
                        "first_name": first,
                        "last_name": last,
                        "email": email,
                        "phone": phone,
                        "phone_status": phone_status,
                        "location": location,
                        "key": key,
                        "status": "READY" if phone else "HOLD",
                    }
                    ready.append(item)

            except Exception as e:
                log(f"  Error on tab {ws.title}: {e}")

    return ready


def write_remark(client, item, remark: str):
    """Write remark only if the cell is still blank"""
    if not remark:
        return False
    try:
        spreadsheet = client.open_by_key(item["sheet_id"])
        ws = spreadsheet.worksheet(item["tab"])
        cell = ws.cell(item["row"], item["cnx_col"])
        if str(cell.value or "").strip():
            log(f"  Skipped write (already has value): {item['email']}")
            return False
        ws.update_cell(item["row"], item["cnx_col"], remark)
        return True
    except Exception as e:
        log(f"  Failed to write remark for {item['email']}: {e}")
        return False


def upload_to_portal(candidates):
    if not PASSWORD:
        raise ValueError("TALKPUSH_PASSWORD is not set")

    results = {"EXECUTIVE TEAM": 0, "Under EDWD": 0, "Existing App": 0, "INVALID": 0, "HOLD": 0, "ERROR": 0}
    ledger = load_ledger()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Login
        log("Logging into Talkpush...")
        page.goto(PORTAL_URL)
        page.fill('input[type="email"]', LOGIN_EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        for item in candidates:
            if item["status"] == "INVALID":
                write_remark(get_gspread_client(), item, "INVALID")
                results["INVALID"] += 1
                continue

            if item["status"] == "HOLD" or not item["phone"]:
                results["HOLD"] += 1
                continue

            log(f"Uploading {item['first_name']} {item['last_name']} <{item['email']}>")

            try:
                # --- Adjust these selectors after you inspect the real page ---
                page.click("text=Add Candidate", timeout=8000)
                page.fill('input[name="firstName"], input[placeholder*="First"]', item["first_name"])
                page.fill('input[name="lastName"], input[placeholder*="Last"]', item["last_name"])
                page.fill('input[type="email"]', item["email"])
                page.fill('input[type="tel"], input[name="phone"]', item["phone"].lstrip("0"))

                # Campaign selection – you will need to improve this
                # page.click("text=Select campaign") ...

                page.click('button:has-text("Submit"), button:has-text("Save")')
                page.wait_for_timeout(2500)

                content = page.content().lower()

                if "already submitted this candidate" in content:
                    remark = "Under EDWD"
                elif "already" in content and "exist" in content:
                    remark = "Existing App"
                else:
                    remark = "EXECUTIVE TEAM"

                # Write remark back
                client = get_gspread_client()
                if write_remark(client, item, remark):
                    results[remark] = results.get(remark, 0) + 1

                # Save to ledger
                ledger["uploaded"].append({
                    "key": item["key"],
                    "email": item["email"],
                    "remark": remark,
                    "timestamp": datetime.now().isoformat(),
                    "sheet": item["sheet_title"],
                    "tab": item["tab"],
                    "row": item["row"],
                })
                save_ledger(ledger)

            except Exception as e:
                log(f"  Upload error: {e}")
                results["ERROR"] += 1

            time.sleep(1.8)  # polite pacing

        browser.close()

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Only extract, do not upload")
    args = parser.parse_args()

    # Lock
    lock_fp = acquire_lock()
    if not lock_fp:
        print("Another CNX run is in progress. Skipping.")
        return

    try:
        log("=== CNX Run started ===")
        client = get_gspread_client()
        candidates = extract_ready_candidates(client)

        ready_count = sum(1 for c in candidates if c["status"] == "READY")
        hold_count = sum(1 for c in candidates if c["status"] == "HOLD")
        invalid_count = sum(1 for c in candidates if c["status"] == "INVALID")

        log(f"Found → READY: {ready_count} | HOLD: {hold_count} | INVALID: {invalid_count}")

        if args.dry_run or ready_count == 0:
            log("Dry run or nothing to upload. Done.")
            return

        results = upload_to_portal(candidates)

        # Final report
        total_uploaded = results.get("EXECUTIVE TEAM", 0)
        if total_uploaded or any(v > 0 for k, v in results.items() if k != "HOLD"):
            log("=== Summary ===")
            for k, v in results.items():
                if v > 0:
                    log(f"  {k}: {v}")
        else:
            log("Nothing new uploaded.")

    finally:
        release_lock(lock_fp)
        log("=== CNX Run finished ===\n")


if __name__ == "__main__":
    main()
