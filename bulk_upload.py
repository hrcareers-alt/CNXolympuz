#!/usr/bin/env python3
"""Upload candidates whose CNX cell is blank. Country code is always +63.

Campaign is the nearest Concentrix site based on Address, City Of Residence, or Location.
"""

import json
import os
import re
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from extract import SHEET_IDS, clean_email, get_client, normalize_phone
from ph_locations import nearest_site

PORTAL = "https://agencyportaltalkpush.replit.app/candidates"
LOGIN_EMAIL = "nickisabelo@olympuz-org.com"
MANILA = ZoneInfo("Asia/Manila")
LOCK_TAB = "CNX RUN"
LOCK_HOURS = 2
RESULT_PATH = Path("/tmp/cnx-check/bulk-results.jsonl")

# Campaigns come from ph_locations, using the PSGC province, city, and barangay lists.

EMAIL_HEADERS = ["email", "email address", "referral email address"]
PHONE_HEADERS = [
    "active mobile number", "mobile number", "contact number", "contact num",
    "contact no", "phone number", "referral contact number", "cellphone",
    "cell phone", "cp number", "mobile", "phone",
]
LOCATION_HINTS = ("address", "residence", "location", "municipality")
# "Personal Details" is the applicant's first name on the Modern Traction / Jobstreet
# form. That form's "Full Name" column is a character reference, or — when the
# columns are shifted — the work-setup answer ("Work From Home / Work At Home").
FIRST_HEADERS = ["first name", "referral first name", "given name", "first", "personal details"]
LAST_HEADERS = ["last name", "referral last name", "surname", "last"]
WORK_SETUP_RE = re.compile(
    r"work\s*from\s*home|work\s*at\s*home|work[\s-]*at\b|any\s+available\s+work|home[\s-]*based|\bwfh\b",
    re.IGNORECASE,
)
SETUP_ONLY = {
    "onsite", "on-site", "on site", "hybrid", "wfh",
    "home based", "home-based", "work from home", "work at home",
}
SETUP_NOISE = {"set", "up", "setup", "available", "any", "the", "and", "or"}


def norm_header(value: str) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split()).lower()
    return text.rstrip(":").strip()


def header_index(headers: list[str], choices: list[str], contains: str | None = None) -> int | None:
    normalized = [norm_header(h) for h in headers]
    for choice in choices:
        if choice in normalized:
            return normalized.index(choice)
    if contains:
        for i, header in enumerate(normalized):
            if contains in header:
                return i
    return None


def location_indexes(headers: list[str]) -> list[int]:
    indexes = []
    for i, header in enumerate(headers):
        name = norm_header(header)
        if not name or "email" in name or name == "cnx":
            continue
        if any(hint in name for hint in LOCATION_HINTS):
            indexes.append(i)
    return indexes


def joined_location(row: list[str], indexes: list[int]) -> str:
    parts = []
    for index in indexes:
        value = cell(row, index)
        if value and value not in parts:
            parts.append(value)
    return " | ".join(parts)


def col_letter(n: int) -> str:
    letters = ""
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def norm_location(value: str) -> str:
    text = str(value or "").lower().replace("ñ", "n").replace("\u5e3d", "n").replace("ã±", "n")
    for char in ",./()-":
        text = text.replace(char, " ")
    return " ".join(text.split())


NON_PH_WORDS = [
    "india", "usa", "united states", "china", "singapore", "malaysia",
    "dubai", "uae", "canada", "australia", "united kingdom", "uk",
    "japan", "korea", "vietnam", "thailand", "indonesia", "hong kong",
]


def clearly_non_ph(location: str) -> bool:
    """Match country names as whole words so Agusan, Bukidnon, and Jerusalem stay Philippine."""
    padded = f" {norm_location(location)} "
    return any(f" {norm_location(word)} " in padded for word in NON_PH_WORDS)


def cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row):
        return ""
    return str(row[index] or "").strip()


def clean_person_name(value: str) -> str:
    """Keep a person's name. Drop a work-setup answer such as Work From Home."""
    text = " ".join(str(value or "").replace("\n", " ").split())
    if not text:
        return ""
    if text.lower().strip(" ./-") in SETUP_ONLY:
        return ""
    if not WORK_SETUP_RE.search(text):
        return text
    remainder = WORK_SETUP_RE.sub(" ", text)
    remainder = re.sub(r"[/|]+", " ", remainder)
    words = []
    for word in remainder.split():
        token = word.strip(" -.,")
        if token and token.lower() not in SETUP_NOISE:
            words.append(token)
    return " ".join(words)


def applicant_names(headers: list[str], row: list[str]) -> tuple[str, str]:
    """First and last name of the applicant, never the work setup or a reference."""
    first = clean_person_name(cell(row, header_index(headers, FIRST_HEADERS)))
    last = clean_person_name(cell(row, header_index(headers, LAST_HEADERS)))
    if first and last:
        return first, last
    full = clean_person_name(cell(row, header_index(
        headers, ["full name", "candidate name", "applicant name", "name", "your complete name"]
    )))
    bits = full.split()
    if len(bits) >= 2:
        first = first or " ".join(bits[:-1])
        last = last or bits[-1]
    return first, last


def extract_backlog(client):
    items = []
    for sheet_id in SHEET_IDS:
        spreadsheet = client.open_by_key(sheet_id)
        meta = spreadsheet.fetch_sheet_metadata()
        titles = [sheet["properties"]["title"] for sheet in meta["sheets"]]
        ranges = [f"'{title}'!A:AZ" for title in titles]
        batch = None
        for attempt in range(6):
            try:
                batch = spreadsheet.values_batch_get(ranges)
                break
            except Exception as exc:
                if "429" not in str(exc) or attempt == 5:
                    raise
                wait = 20 * (attempt + 1)
                print(f"QUOTA wait {wait}s", flush=True)
                time.sleep(wait)
        for value_range in batch.get("valueRanges", []):
            values = value_range.get("values") or []
            if not values:
                continue
            headers = values[0]
            if "CNX" not in [h.strip() for h in headers if h]:
                continue
            cnx_idx = [h.strip() for h in headers].index("CNX")
            tab = value_range["range"].split("!")[0].strip("'")
            email_i = header_index(headers, EMAIL_HEADERS, "email")
            phone_i = header_index(headers, PHONE_HEADERS) or header_index(headers, [], "mobile") or header_index(headers, [], "phone") or header_index(headers, [], "contact")
            loc_indexes = location_indexes(headers)
            for row_num, row in enumerate(values[1:], start=2):
                if cell(row, cnx_idx):
                    continue
                first, last = applicant_names(headers, row)
                email = clean_email(cell(row, email_i))
                phone_raw = cell(row, phone_i)
                location = joined_location(row, loc_indexes)
                if not any([first, last, email, phone_raw]):
                    continue
                item = {
                    "sheet_id": sheet_id,
                    "sheet_title": spreadsheet.title,
                    "tab": tab,
                    "row": row_num,
                    "cnx_col": cnx_idx + 1,
                    "first_name": first,
                    "last_name": last,
                    "email": email,
                    "location": location,
                }
                if clearly_non_ph(location):
                    item["status"] = "INVALID"
                    items.append(item)
                    continue
                phone, phone_status = normalize_phone(phone_raw)
                if not (first and last and email and "@" in email and phone):
                    item["status"] = "HOLD"
                    items.append(item)
                    continue
                campaign, campaign_id = nearest_site(location)
                item.update({
                    "status": "READY",
                    "phone": phone,
                    "phone_status": phone_status,
                    "campaign": campaign,
                    "campaign_id": campaign_id,
                })
                items.append(item)
    return items


def remark_for(status: int, body: str) -> str:
    text = body.lower()
    if status in (200, 201) and "error" not in text:
        return "EXECUTIVE TEAM"
    # Portal saved the candidate and flagged Talkpush confirmation for review.
    if status == 202 and ("submission saved" in text or "candidateid" in text):
        return "EXECUTIVE TEAM"
    if "already submitted" in text or "same_agency" in text:
        return "Under EDWD"
    if "already in the system" in text or "blockkind\":\"crm" in text or '"crm"' in text:
        return "Existing App"
    if "duplicate" in text or "different agency" in text:
        return "Duplicate"
    return ""


def flush_remarks(client, pending: list[dict]):
    if not pending:
        return
    grouped: dict[tuple[str, str], list[dict]] = {}
    for item in pending:
        grouped.setdefault((item["sheet_id"], item["tab"]), []).append(item)
    for (sheet_id, tab), rows in grouped.items():
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(tab)
        data = []
        for item in rows:
            letter = col_letter(item["cnx_col"])
            data.append({"range": f"{letter}{item['row']}", "values": [[item["remark"]]]})
        worksheet.batch_update(data, value_input_option="RAW")
        print(f"WROTE {len(data)} remarks on {tab}", flush=True)
    pending.clear()


def load_logged_remarks() -> dict[tuple[str, str, int], str]:
    found = {}
    if not RESULT_PATH.exists():
        return found
    for line in RESULT_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        remark = rec.get("remark") or ""
        if remark and rec.get("sheet_id") and rec.get("tab") and rec.get("row"):
            found[(rec["sheet_id"], rec["tab"], int(rec["row"]))] = remark
    return found


def name_problem(item: dict) -> str:
    """Return why this name must not be posted. Empty string means the name is safe."""
    first = clean_person_name(item.get("first_name", ""))
    last = clean_person_name(item.get("last_name", ""))
    raw = f"{item.get('first_name', '')} {item.get('last_name', '')}"
    if not first or not last:
        return "missing name"
    if first != item.get("first_name") or last != item.get("last_name"):
        return "work-setup text in name"
    if WORK_SETUP_RE.search(raw):
        return "work-setup text in name"
    return ""


def upload_all(items: list[dict], limit: int | None):
    ready = [item for item in items if item["status"] == "READY"]
    blocked = [item for item in ready if name_problem(item)]
    if blocked:
        print(f"REFUSING UPLOAD {len(blocked)} names are still work-setup text", flush=True)
        for item in blocked[:30]:
            print(
                f"  {item['tab']} r{item['row']} {item.get('first_name')!r} {item.get('last_name')!r} {item.get('email')}",
                flush=True,
            )
        raise SystemExit(2)
    invalid = [item for item in items if item["status"] == "INVALID"]
    if limit is not None:
        ready = ready[:limit]
        invalid = []
    already = load_logged_remarks()
    client = get_client()
    pending = []
    stats = Counter()
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RESULT_PATH.open("a", encoding="utf-8") as log, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def login():
            page.goto("https://agencyportaltalkpush.replit.app/login", wait_until="domcontentloaded", timeout=60000)
            page.fill('input[type="email"]', LOGIN_EMAIL)
            page.fill('input[type="password"]', os.environ["TALKPUSH_PASSWORD"])
            page.click('button[type="submit"]')
            page.wait_for_url("**/candidates", timeout=30000)

        login()

        def queue(item, remark):
            item["remark"] = remark
            pending.append(item)
            stats[remark] += 1
            log.write(json.dumps({
                "sheet_id": item["sheet_id"], "row": item["row"], "tab": item["tab"],
                "email": item["email"], "first_name": item.get("first_name", ""),
                "last_name": item.get("last_name", ""),
                "campaign": item.get("campaign", ""),
                "location": item.get("location", ""), "remark": remark,
            }) + "\n")
            log.flush()
            if len(pending) >= 40:
                flush_remarks(client, pending)

        def replay(item, remark):
            item["remark"] = remark
            pending.append(item)
            stats["RESUMED"] += 1
            if len(pending) >= 40:
                flush_remarks(client, pending)

        for item in invalid:
            key = (item["sheet_id"], item["tab"], item["row"])
            if key in already:
                replay(item, already[key])
                continue
            queue(item, "INVALID")

        for index, item in enumerate(ready, start=1):
            key = (item["sheet_id"], item["tab"], item["row"])
            if key in already:
                replay(item, already[key])
                continue
            first_name = clean_person_name(item["first_name"])
            last_name = clean_person_name(item["last_name"])
            if not first_name or not last_name:
                stats["SKIP_NAME"] += 1
                log.write(json.dumps({
                    "sheet_id": item["sheet_id"], "row": item["row"], "tab": item["tab"],
                    "email": item["email"], "remark": "SKIP_NAME",
                    "first_name": item.get("first_name", ""), "last_name": item.get("last_name", ""),
                }) + "\n")
                log.flush()
                continue
            payload = {
                "firstName": first_name,
                "lastName": last_name,
                "email": item["email"],
                "countryCode": "+63",
                "phoneNumber": item["phone"].lstrip("0"),
                "aadhaarNumber": None,
                "campaign": item["campaign"],
                "campaignId": item["campaign_id"],
                "resumeBase64": None,
                "agencyId": None,
            }
            response = None
            body = ""
            for attempt in range(4):
                try:
                    response = context.request.post(
                        PORTAL, data=payload, headers={"content-type": "application/json"}, timeout=60000
                    )
                    body = response.text()
                except PlaywrightError as exc:
                    print(f"POST retry {attempt + 1} row={item['row']} {exc}", flush=True)
                    time.sleep(5 * (attempt + 1))
                    try:
                        login()
                    except PlaywrightError as login_exc:
                        print(f"RELOGIN failed {login_exc}", flush=True)
                    continue
                html = "<html" in body.lower()
                if response.status in (401, 403) or html:
                    print(f"RELOGIN status={response.status} row={item['row']}", flush=True)
                    login()
                    continue
                if response.status == 429:
                    time.sleep(8)
                    continue
                break
            remark = remark_for(response.status, body) if response is not None else ""
            if remark and "<html" not in body.lower():
                queue(item, remark)
            else:
                stats["ERROR"] += 1
                log.write(json.dumps({
                    "sheet_id": item["sheet_id"], "row": item["row"], "tab": item["tab"],
                    "email": item["email"], "status": response.status if response else 0,
                    "body": body[:300],
                }) + "\n")
                log.flush()
            if index % 25 == 0 or index == len(ready):
                print(f"PROGRESS {index}/{len(ready)} {dict(stats)}", flush=True)
            time.sleep(0.15)
        flush_remarks(client, pending)
        browser.close()
    print("STATS", dict(stats), flush=True)


def in_upload_window(now: datetime | None = None) -> bool:
    """True from 8:00 AM through 1:59 AM Philippine time. Quiet hours are 2:00–7:59 AM."""
    current = now or datetime.now(MANILA)
    return current.hour >= 8 or current.hour <= 1


def acquire_run_lock(client):
    """One upload at a time. A lock older than two hours is treated as abandoned."""
    from gspread.exceptions import WorksheetNotFound

    spreadsheet = client.open_by_key(SHEET_IDS[0])
    try:
        worksheet = spreadsheet.worksheet(LOCK_TAB)
    except WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=LOCK_TAB, rows=5, cols=2)
        worksheet.update(values=[["Hourly upload lock. Leave this cell alone."]], range_name="B1")
    current = (worksheet.acell("A1").value or "").strip()
    now = datetime.now(timezone.utc)
    if current.startswith("running|"):
        started = None
        parts = current.split("|")
        if len(parts) >= 2:
            try:
                started = datetime.fromisoformat(parts[1])
            except ValueError:
                started = None
        if started is not None and started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if started is not None and now - started < timedelta(hours=LOCK_HOURS):
            print(f"Another CNX run is in progress since {parts[1]}. Skipping.", flush=True)
            return None
        print(f"Replacing stale lock from {current}", flush=True)
    token = f"running|{now.isoformat()}|{uuid.uuid4()}"
    worksheet.update(values=[[token]], range_name="A1")
    time.sleep(1)
    if (worksheet.acell("A1").value or "").strip() != token:
        print("Another CNX run took the lock. Skipping.", flush=True)
        return None
    print("LOCK ACQUIRED", flush=True)
    return {"worksheet": worksheet, "token": token}


def release_run_lock(lock) -> None:
    if not lock:
        return
    worksheet = lock["worksheet"]
    if (worksheet.acell("A1").value or "").strip() == lock["token"]:
        worksheet.update(values=[[""]], range_name="A1")
        print("LOCK RELEASED", flush=True)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "upload" and os.getenv("CNX_FORCE") != "1" and not in_upload_window():
        print("Outside 8:00 AM–1:00 AM Philippine time. Skipping.", flush=True)
        return
    client = get_client()
    lock = None
    if mode == "upload":
        lock = acquire_run_lock(client)
        if lock is None:
            return
    try:
        _run(mode, client)
    finally:
        release_run_lock(lock)


def _run(mode: str, client):
    items = extract_backlog(client)
    counts = Counter(item["status"] for item in items)
    campaigns = Counter(item.get("campaign", "") for item in items if item["status"] == "READY")
    print("COUNTS", dict(counts))
    print("CAMPAIGNS")
    for name, count in campaigns.most_common():
        print(f"  {count:5} {name}")
    print("SAMPLES")
    shown = Counter()
    wah = 0
    for item in items:
        if item["status"] != "READY":
            continue
        campaign = item.get("campaign", "")
        if shown[campaign] >= 2:
            continue
        shown[campaign] += 1
        print(f"  {campaign} | {item['location'][:120]}")
    print("WAH")
    for item in items:
        if item.get("campaign") != "2026 Work At Home Campaign":
            continue
        wah += 1
        if wah <= 25:
            print(f"  {item['tab']} r{item['row']} | {item['location'][:140]}")
    print("WAH_TOTAL", wah)
    bad_names = [item for item in items if item["status"] == "READY" and name_problem(item)]
    print("BAD_NAMES", len(bad_names))
    for item in bad_names[:20]:
        print(f"  BAD {item['tab']} r{item['row']} {item.get('first_name')!r} {item.get('last_name')!r}")
    if mode == "plan":
        Path("/tmp/cnx-check/plan-items.json").write_text(json.dumps(items), encoding="utf-8")
        return
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    upload_all(items, limit)


if __name__ == "__main__":
    main()
