#!/usr/bin/env python3
"""
upload_cnx.py – Upload candidates to Talkpush CNX portal and write remarks.
"""

import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()

PORTAL_URL = "https://agencyportaltalkpush.replit.app/candidates"
EMAIL = "nickisabelo@olympuz-org.com"
PASSWORD = os.getenv("TALKPUSH_PASSWORD")

LEDGER_FILE = Path("uploaded.json")
PROGRESS_LOG = Path("progress.log")


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(PROGRESS_LOG, "a") as f:
        f.write(line + "\n")


def load_ledger():
    if LEDGER_FILE.exists():
        with open(LEDGER_FILE) as f:
            return json.load(f)
    return {"uploaded": []}


def save_ledger(ledger):
    with open(LEDGER_FILE, "w") as f:
        json.dump(ledger, f, indent=2)


def login(page):
    log("Logging in to Talkpush portal...")
    page.goto(PORTAL_URL)
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")
    log("Login successful")


def upload_one(page, candidate: dict) -> str:
    """
    Returns the remark to write:
    - EXECUTIVE TEAM
    - Under EDWD
    - Existing App
    - Duplicate
    - INVALID
    - (empty string if held/error)
    """
    try:
        # Click "Add Candidate" or similar button
        page.click("text=Add Candidate", timeout=10000)

        # Fill form
        page.fill('input[name="first_name"]', candidate["first_name"])
        page.fill('input[name="last_name"]', candidate["last_name"])
        page.fill('input[name="email"]', candidate["email"])

        # Phone (country code +63 is usually already selected)
        page.fill('input[name="phone"]', candidate["phone"].lstrip("0"))

        # Campaign / Site – you will need to adjust the selector
        # page.select_option('select[name="campaign"]', label=candidate.get("campaign"))

        # Submit
        page.click('button:has-text("Submit")')

        # Wait for response
        page.wait_for_timeout(2000)

        content = page.content().lower()

        if "successfully" in content or "created" in content:
            return "EXECUTIVE TEAM"
        if "you’ve already submitted this candidate" in content or "already submitted" in content:
            return "Under EDWD"
        if "already" in content:
            return "Existing App"

        return "EXECUTIVE TEAM"  # fallback

    except PlaywrightTimeout:
        log(f"Timeout while uploading {candidate['email']}")
        return ""
    except Exception as e:
        log(f"Error uploading {candidate['email']}: {e}")
        return ""


def main(candidates: list):
    if not PASSWORD:
        raise ValueError("TALKPUSH_PASSWORD not set")

    ledger = load_ledger()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        login(page)

        for cand in candidates:
            if cand.get("status") != "READY":
                continue

            log(f"Uploading: {cand['first_name']} {cand['last_name']} <{cand['email']}>")

            remark = upload_one(page, cand)

            # Record in ledger
            ledger["uploaded"].append({
                "key": f"{cand['email']}|{cand['phone']}|{cand['first_name']}|{cand['last_name']}".lower(),
                "email": cand["email"],
                "remark": remark,
                "timestamp": datetime.now().isoformat(),
                "sheet": cand["sheet"],
                "tab": cand["tab"],
                "row": cand["row"],
            })
            save_ledger(ledger)

            log(f"  → Remark: {remark or '(blank)'}")

            # Be polite
            time.sleep(1.5)

        browser.close()

    log("Upload run finished")


if __name__ == "__main__":
    # Example usage – in real use you will pass the result from extract.py
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("This is a skeleton. Call main(candidates) with the list from extract.py")
