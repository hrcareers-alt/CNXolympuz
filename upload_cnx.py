#!/usr/bin/env python3
"""
upload_cnx.py – Upload candidates to Talkpush CNX portal + write remarks.
"""

import os
import json
import time
import fcntl
import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

from extract import extract_candidates, get_client, load_ledger, save_ledger

load_dotenv()

# =========================================================
# CONFIG
# =========================================================
PORTAL_URL = "https://agencyportaltalkpush.replit.app/candidates"
LOGIN_EMAIL = "nickisabelo@olympuz-org.com"
PASSWORD = os.getenv("TALKPUSH_PASSWORD")

LOCK_FILE = Path(".upload.lock")
PROGRESS_LOG = Path("progress.log")


def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(PROGRESS_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def acquire_lock():
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
            LOCK_FILE.unlink(missing_ok=True)


def write_remark(client, item: dict, remark: str) -> bool:
    """Write remark only if the CNX cell is still blank."""
    if not remark:
        return False
    try:
        spreadsheet = client.open_by_key(item["sheet_id"])
        ws = spreadsheet.worksheet(item["tab"])
        current = ws.cell(item["row"], item["cnx_col"]).value
        if str(current or "").strip():
            log(f"  ⚠️  Cell already has value, skipped: {item['email']}")
            return False
        ws.update_cell(item["row"], item["cnx_col"], remark)
        return True
    except Exception as e:
        log(f"  ❌ Failed to write remark for {item['email']}: {e}")
        return False


def upload_one(page, item: dict) -> str:
    """
    Returns one of:
    EXECUTIVE TEAM | Under EDWD | Existing App | (empty string on error)
    """
    try:
        page.click("text=Add Candidate", timeout=10000)
        time.sleep(0.8)

        # Flexible selectors – adjust after inspecting real page
        page.fill('input[name="firstName"], input[placeholder*="First" i]', item["first_name"])
        page.fill('input[name="lastName"], input[placeholder*="Last" i]', item["last_name"])
        page.fill('input[type="email"]', item["email"])
        page.fill('input[type="tel"], input[name="phone"], input[placeholder*="Phone" i]', item["phone"].lstrip("0"))

        # TODO: Add campaign/site selection here
        # page.click("text=Select campaign") ...

        page.click('button:has-text("Submit"), button:has-text("Save"), button:has-text("Add")')
        page.wait_for_timeout(2500)

        content = page.content().lower()

        if "you’ve already submitted this candidate" in content or "already submitted this candidate" in content:
            return "Under EDWD"
        if "already exists" in content or "already in the system" in content:
            return "Existing App"

        return "EXECUTIVE TEAM"

    except PlaywrightTimeout:
        log(f"  ⏰ Timeout: {item['email']}")
        return ""
    except Exception as e:
        log(f"  ❌ Upload error ({item['email']}): {e}")
        return ""


def main(dry_run: bool = False):
    if not PASSWORD:
        raise ValueError("TALKPUSH_PASSWORD is not set in environment")

    lock_fp = acquire_lock()
    if not lock_fp:
        print("Another CNX run is in progress. Skipping quietly.")
        return

    try:
        log("=== CNX Upload started ===")

        candidates = extract_candidates(read_plan=False)

        ready = [c for c in candidates if c["status"] == "READY"]
        hold = [c for c in candidates if c["status"] == "HOLD"]
        invalid = [c for c in candidates if c["status"] == "INVALID"]

        log(f"Found → READY: {len(ready)} | HOLD: {len(hold)} | INVALID: {len(invalid)}")

        if dry_run:
            log("Dry-run mode. Exiting without upload.")
            return

        if not ready and not invalid:
            log("Nothing to process.")
            return

        client = get_client()
        ledger = load_ledger()
        stats = {
            "EXECUTIVE TEAM": 0,
            "Under EDWD": 0,
            "Existing App": 0,
            "INVALID": 0,
            "ERROR": 0,
        }

        # Handle INVALID first
        for item in invalid:
            if write_remark(client, item, "INVALID"):
                stats["INVALID"] += 1
                ledger["uploaded"].append({
                    "key": item["key"],
                    "email": item["email"],
                    "remark": "INVALID",
                    "timestamp": datetime.now().isoformat(),
                    "sheet": item["sheet_title"],
                    "tab": item["tab"],
                    "row": item["row"],
                })

        if not ready:
            save_ledger(ledger)
            log("Only INVALID rows processed.")
            return

        # Upload READY candidates
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            log("Logging into Talkpush portal...")
            page.goto(PORTAL_URL)
            page.fill('input[type="email"]', LOGIN_EMAIL)
            page.fill('input[type="password"]', PASSWORD)
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")
            time.sleep(2)
            log("Login successful")

            for item in ready:
                log(f"Uploading: {item['first_name']} {item['last_name']} <{item['email']}>")

                remark = upload_one(page, item)

                if remark:
                    if write_remark(client, item, remark):
                        stats[remark] = stats.get(remark, 0) + 1
                        ledger["uploaded"].append({
                            "key": item["key"],
                            "email": item["email"],
                            "remark": remark,
                            "timestamp": datetime.now().isoformat(),
                            "sheet": item["sheet_title"],
                            "tab": item["tab"],
                            "row": item["row"],
                        })
                        log(f"  → {remark}")
                    else:
                        stats["ERROR"] += 1
                else:
                    stats["ERROR"] += 1

                time.sleep(1.8)  # polite pacing

            browser.close()

        save_ledger(ledger)

        # Final report
        total = sum(stats.values())
        if total > 0:
            log("=== Summary ===")
            for k, v in stats.items():
                if v > 0:
                    log(f"  {k}: {v}")
        else:
            log("No changes made.")

    finally:
        release_lock(lock_fp)
        log("=== CNX Upload finished ===\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Extract only, do not upload")
    args = parser.parse_args()

    main(dry_run=args.dry_run)
