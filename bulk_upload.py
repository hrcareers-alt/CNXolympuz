#!/usr/bin/env python3
"""Upload candidates whose CNX cell is blank. Country code is always +63.

Campaign is the nearest Concentrix site based on Address, City Of Residence, or Location.
"""

import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from playwright.sync_api import sync_playwright

from extract import SHEET_IDS, clean_email, get_client, normalize_phone

PORTAL = "https://agencyportaltalkpush.replit.app/candidates"
LOGIN_EMAIL = "nickisabelo@olympuz-org.com"
RESULT_PATH = Path("/tmp/cnx-check/bulk-results.jsonl")

# (campaign value sent to the portal, campaign id, keywords). Longer keywords win.
SITES = [
    ("2026 San Lazaro Campaign", "548", [
        "sampaloc", "quiapo", "santa cruz", "sta cruz", "tondo", "binondo",
        "intramuros", "ermita", "malate", "paco", "pandacan", "santa ana",
        "sta ana", "santa mesa", "sta mesa", "san andres", "san nicolas",
        "manila city", "city of manila", "manila",
    ]),
    ("2026 Spark Campaign", "550", [
        "cubao", "araneta", "socorro", "kamuning", "project 2", "project 3",
        "project 4", "p tuazon", "p. tuazon", "10th avenue", "10th ave",
    ]),
    ("2026 Cyberwest Campaign", "534", [
        "west avenue", "west ave", "sm north", "project 6", "project 7",
        "project 8", "veterans", "bago bantay", "munoz", "muñoz", "balintawak",
        "caloocan", "malabon", "navotas", "valenzuela",
    ]),
    ("2026 UP Ayala Technohub Campaign", "552", [
        "commonwealth", "batasan", "fairview", "novaliches", "sauyo",
        "up village", "up campus", "teachers village", "holy spirit",
        "greater lagro", "north fairview", "rodriguez", "rodriquez",
        "montalban", "san mateo",
    ]),
    ("2026 Eastwood Campaign", "537", [
        "eastwood", "libis", "bagumbayan", "white plains", "blue ridge",
        "katipunan", "loyola", "marikina", "antipolo", "project 4",
        "teresa", "tanay", "morong", "pililla", "baras", "cardona",
        "jalajala", "dalig",
    ]),
    ("2026 Eton Campaign", "523", [
        "eton", "centris", "quezon avenue", "quezon ave", "south triangle",
        "timog", "tomas morato", "scout", "sikatuna", "diliman", "quezon city",
        " q.c", "qc",
    ]),
    ("2026 Bridgetowne Campaign", "522", [
        "bridgetowne", "pasig", "ugong", "rosario pasig", "manggahan",
        "santolan", "cainta", "taytay", "angono", "binangonan",
    ]),
    ("2026 Shaw Campaign", "549", [
        "shaw", "mandaluyong", "san juan", "greenhills", "addition hills",
        "wack wack", "wack-wack",
    ]),
    ("2026 Megamall Campaign", "543", [
        "megamall", "ortigas", "kapitolyo",
    ]),
    ("2026 Makati ANE Campaign", "541", [
        "ayala north", "north exchange", "ane",
    ]),
    ("2026 Makati G5 Campaign", "542", [
        "makati", "poblacion", "bel-air", "bel air", "salcedo", "legazpi village",
        "rockwell",
    ]),
    ("2026 Taguig Campaign", "551", [
        "taguig", "bgc", "bonifacio", "fort bonifacio", "pateros", "mc kinley",
        "mckinley",
    ]),
    ("2026 MOA Campaign", "544", [
        "moa", "mall of asia", "pasay", "paranaque", "parañaque", "baclaran",
        "don galo",
    ]),
    ("2026 Alabang Campaign", "525", [
        "alabang", "muntinlupa", "las pinas", "las piñas", "sucat", "bf homes",
        "pilar village",
    ]),
    ("2026 Nuvali Campaign", "547", [
        "nuvali", "santa rosa", "sta rosa", "santa cruz laguna", "cabuyao", "calamba", "binan",
        "biñan", "san pedro", "laguna", "los banos", "los baños", "dasmarinas",
        "dasmariñas", "imus", "bacoor", "general trias", "gentri", "silang",
        "tagaytay", "tanza", "kawit", "noveleta", "carmona", "cavite",
        "batangas", "lipa", "tanauan", "lucena", "quezon province",
        "trece martires", "trece", "amadeo", "indang", "naic", "sariaya",
        "gumaca", "lucban", "candelaria", "tiaong", "mauban",
        "atimonan", "malvar", "lemery", "nasugbu", "balayan", "calaca",
        "real quezon", "lopez quezon", "talolong",
    ]),
    ("2026 Clark Campaign", "533", [
        "clark", "pampanga", "angeles", "anges city", "mabalacat", "san fernando pampanga",
        "tarlac", "olongapo", "zambales", "subic", "bataan", "balanga",
        "nueva ecija", "cabanatuan", "gapan", "bulacan", "malolos", "meycauayan",
        "marilao", "san jose del monte", "porac", "apalit", "macabebe",
        "bocaue", "baliuag", "guiguinto", "plaridel", "baler", "dingalan",
        "floridablanca", "guagua", "arayat", "magalang",
    ]),
    ("2026 Baguio Campaign", "565", [
        "baguio", "benguet", "la trinidad", "la union", "san fernando la union",
        "ilocos", "vigan", "laoag", "pangasinan", "dagupan", "urdaneta",
        "ifugao", "kalinga", "abra", "mountain province", "cagayan", "tuguegarao",
        "isabela", "santiago city", "nueva vizcaya", "penablanca", "agoo", "caba",
    ]),
    ("2026 Naga Campaign", "545", [
        "naga", "camarines", "camrines", "albay", "legazpi", "legaspi", "sorsogon", "iriga",
        "daet", "bicol", "masbate", "camalig", "ligao", "tabaco", "libmanan",
        "magarao", "catanduanes", "virac",
    ]),
    ("2026 Cebu Mactan Campaign", "532", [
        "lapu-lapu", "lapu lapu", "mactan",
    ]),
    ("2026 Cebu J Center Campaign", "529", [
        "mandaue", "j center", "jcentre", "j centre",
    ]),
    ("2026 Cebu IT Park Campaign", "528", [
        "cebu", "talisay", "consolacion", "liloan", "danao", "toledo", "bogo",
        "carcar", "bohol", "tagbilaran", "tacloban", "leyte", "samar", "ormoc",
        "maasin", "palo", "eastern visayas", "villareal",
    ]),
    ("2026 Bacolod Campaign", "526", [
        "bacolod", "negros", "talisay negros", "dumaguete", "silay", "kabankalan", "sagay",
        "san carlos", "bago city", "himamaylan", "cadiz", "escalante", "sibulan",
        "siquijor", "murcia",
    ]),
    ("2026 Ilo-Ilo Campaign", "539", [
        "iloilo", "ilo-ilo", "ilonggo", "panay", "antique", "aklan", "capiz",
        "kalibo", "boracay", "roxas city", "guimaras",
    ]),
    ("2026 CDO Campaign", "527", [
        "cagayan de oro", "cagayab", "cdoc", "mis or", "cdo", "misamis", "bukidnon", "bukindon",
        "iligan", "camiguin", "ozamiz", "zamboanga", "pagadian", "dipolog",
        "butuan", "surigao", "agusan", "valencia city", "malaybalay",
        "manolo fortich", "don carlos", "bislig", "mangagoy", "naawan",
        "lanao", "dapitan", "cabadbaran", "bayugan", "tubod",
    ]),
    ("2026 Davao Campaign", "535", [
        "davao", "general santos", "gensan", "cotabato", "kidapawan", "tagum",
        "panabo", "mati", "digos", "koronadal", "midsayap", "glan", "alabel",
        "sarangani", "polomolok", "isulan", "sultan kudarat", "maguindanao",
    ]),
    ("2026 Work At Home Campaign | BM NORTH", "554", [
        "bm north", "wah north", "work at home north",
    ]),
    ("2026 Work At Home Campaign | BM SOUTH", "555", [
        "bm south", "wah south", "work at home south",
    ]),
    ("2026 Work At Home Campaign", "553", [
        "work at home", "work-at-home", "wfh", "home based", "home-based",
    ]),
]

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


# Province or whole-city defaults. A barangay or host city beats these.
REGION_KEYWORDS = {
    "quezon city", "qc", "manila", "metro manila", "ncr", "philippines", "ph",
    "cebu", "negros", "laguna", "cavite", "batangas", "quezon province",
    "pampanga", "bulacan", "nueva ecija", "tarlac", "zambales", "bataan",
    "davao", "iloilo", "panay", "misamis", "bukidnon", "pangasinan", "ilocos",
    "bicol", "camarines", "albay", "leyte", "samar", "bohol", "agusan",
    "surigao", "zamboanga", "cotabato", "benguet",
}


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


def nearest_site(location: str) -> tuple[str, str]:
    """A specific city or barangay beats a province. Longest keyword wins inside a tier."""
    padded = f" {norm_location(location)} "
    matches = []
    for campaign, campaign_id, keywords in SITES:
        for keyword in keywords:
            token = norm_location(keyword)
            if token and f" {token} " in padded:
                matches.append((len(token), campaign, campaign_id, token))
    anchors = [item for item in matches if item[3] not in REGION_KEYWORDS]
    pool = anchors or matches
    if not pool:
        return "2026 Work At Home Campaign", "553"
    pool.sort(key=lambda item: item[0], reverse=True)
    return pool[0][1], pool[0][2]


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


def upload_all(items: list[dict], limit: int | None):
    ready = [item for item in items if item["status"] == "READY"]
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
                "email": item["email"], "campaign": item.get("campaign", ""),
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
            for attempt in range(3):
                response = context.request.post(
                    PORTAL, data=payload, headers={"content-type": "application/json"}
                )
                body = response.text()
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


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    client = get_client()
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
    if mode == "plan":
        Path("/tmp/cnx-check/plan-items.json").write_text(json.dumps(items), encoding="utf-8")
        return
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    upload_all(items, limit)


if __name__ == "__main__":
    main()
