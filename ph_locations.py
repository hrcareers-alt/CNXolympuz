"""Resolve a free-text Philippine address to the nearest Concentrix site.

Place names come from the PSGC lists in data/ph (province, municipality or city,
and barangay). A city beats a province. A site landmark beats the city default
only inside the city it belongs to. The same place name in two provinces is
used only when the text names the province, or when every match is the same site.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data" / "ph"

WAH = ("2026 Work At Home Campaign", "553")
WAH_NORTH = ("2026 Work At Home Campaign | BM NORTH", "554")
WAH_SOUTH = ("2026 Work At Home Campaign | BM SOUTH", "555")
SAN_LAZARO = ("2026 San Lazaro Campaign", "548")
SPARK = ("2026 Spark Campaign", "550")
CYBERWEST = ("2026 Cyberwest Campaign", "534")
UP_AYALA = ("2026 UP Ayala Technohub Campaign", "552")
EASTWOOD = ("2026 Eastwood Campaign", "537")
ETON = ("2026 Eton Campaign", "523")
BRIDGETOWNE = ("2026 Bridgetowne Campaign", "522")
SHAW = ("2026 Shaw Campaign", "549")
MEGAMALL = ("2026 Megamall Campaign", "543")
MAKATI_ANE = ("2026 Makati ANE Campaign", "541")
MAKATI = ("2026 Makati G5 Campaign", "542")
TAGUIG = ("2026 Taguig Campaign", "551")
MOA = ("2026 MOA Campaign", "544")
ALABANG = ("2026 Alabang Campaign", "525")
NUVALI = ("2026 Nuvali Campaign", "547")
CLARK = ("2026 Clark Campaign", "533")
BAGUIO = ("2026 Baguio Campaign", "565")
NAGA = ("2026 Naga Campaign", "545")
MACTAN = ("2026 Cebu Mactan Campaign", "532")
J_CENTER = ("2026 Cebu J Center Campaign", "529")
CEBU = ("2026 Cebu IT Park Campaign", "528")
BACOLOD = ("2026 Bacolod Campaign", "526")
ILOILO = ("2026 Ilo-Ilo Campaign", "539")
CDO = ("2026 CDO Campaign", "527")
DAVAO = ("2026 Davao Campaign", "535")

# provCode -> site. NCR codes are omitted; those cities have their own sites.
PROVINCE_SITE = {
    "0128": BAGUIO, "0129": BAGUIO, "0133": BAGUIO, "0155": BAGUIO,
    "0209": BAGUIO, "0215": BAGUIO, "0231": BAGUIO, "0250": BAGUIO, "0257": BAGUIO,
    "0308": CLARK, "0314": CLARK, "0349": CLARK, "0354": CLARK,
    "0369": CLARK, "0371": CLARK, "0377": CLARK,
    "0410": NUVALI, "0421": NUVALI, "0434": NUVALI, "0456": NUVALI,
    "0458": EASTWOOD,
    "1740": NUVALI, "1751": NUVALI, "1752": NUVALI, "1753": NUVALI, "1759": NUVALI,
    "0505": NAGA, "0516": NAGA, "0517": NAGA, "0520": NAGA, "0541": NAGA, "0562": NAGA,
    "0604": ILOILO, "0606": ILOILO, "0619": ILOILO, "0630": ILOILO, "0679": ILOILO,
    "0645": BACOLOD,
    "0712": CEBU, "0722": CEBU, "0746": BACOLOD, "0761": BACOLOD,
    "0826": CEBU, "0837": CEBU, "0848": CEBU, "0860": CEBU, "0864": CEBU, "0878": CEBU,
    "0972": CDO, "0973": CDO, "0983": CDO, "0997": CDO,
    "1013": CDO, "1018": CDO, "1035": CDO, "1042": CDO, "1043": CDO,
    "1123": DAVAO, "1124": DAVAO, "1125": DAVAO, "1182": DAVAO, "1186": DAVAO,
    "1247": DAVAO, "1263": DAVAO, "1265": DAVAO, "1280": DAVAO, "1298": DAVAO,
    "1401": BAGUIO, "1411": BAGUIO, "1427": BAGUIO, "1432": BAGUIO,
    "1444": BAGUIO, "1481": BAGUIO,
    "1507": CDO, "1536": CDO, "1566": CDO, "1570": CDO,
    "1538": DAVAO,
    "1602": CDO, "1603": CDO, "1667": CDO, "1668": CDO, "1685": CDO,
}

# (normalized city name, provCode) -> site, when the city is nearer another site
# than the rest of its province.
CITY_SITE = {
    ("cainta", "0458"): BRIDGETOWNE,
    ("taytay", "0458"): BRIDGETOWNE,
    ("angono", "0458"): BRIDGETOWNE,
    ("binangonan", "0458"): BRIDGETOWNE,
    ("rodriguez", "0458"): UP_AYALA,
    ("san mateo", "0458"): UP_AYALA,
    ("lapu lapu", "0722"): MACTAN,
    ("mandaue", "0722"): J_CENTER,
}

# NCR city or district name -> site. "san juan" here is the NCR city only.
NCR_SITE = {
    "tondo": SAN_LAZARO, "binondo": SAN_LAZARO, "quiapo": SAN_LAZARO,
    "san nicolas": SAN_LAZARO, "santa cruz": SAN_LAZARO, "sampaloc": SAN_LAZARO,
    "san miguel": SAN_LAZARO, "ermita": SAN_LAZARO, "intramuros": SAN_LAZARO,
    "malate": SAN_LAZARO, "paco": SAN_LAZARO, "pandacan": SAN_LAZARO,
    "port area": SAN_LAZARO, "santa ana": SAN_LAZARO,
    "quezon city": ETON,
    "mandaluyong": SHAW, "san juan": SHAW,
    "marikina": EASTWOOD,
    "pasig": BRIDGETOWNE,
    "caloocan": CYBERWEST, "malabon": CYBERWEST, "navotas": CYBERWEST,
    "valenzuela": CYBERWEST,
    "makati": MAKATI,
    "taguig": TAGUIG, "pateros": TAGUIG,
    "pasay": MOA, "paranaque": MOA,
    "las pinas": ALABANG, "muntinlupa": ALABANG,
}

# phrase, site, city names that may use it, whether it counts with no city found.
# None means any resolved city.
LANDMARKS = [
    ("bridgetowne", BRIDGETOWNE, None, True),
    ("nuvali", NUVALI, None, True),
    ("clark", CLARK, None, True),
    ("mactan", MACTAN, None, True),
    ("mall of asia", MOA, None, True),
    ("fort bonifacio", TAGUIG, None, True),
    ("bonifacio global", TAGUIG, None, True),
    ("megamall", MEGAMALL, {"pasig"}, True),
    ("ortigas", MEGAMALL, {"pasig"}, True),
    ("kapitolyo", MEGAMALL, {"pasig"}, False),
    ("bgc", TAGUIG, {"taguig"}, True),
    ("mckinley", TAGUIG, {"taguig"}, True),
    ("ayala north exchange", MAKATI_ANE, {"makati"}, True),
    ("ayala north", MAKATI_ANE, {"makati"}, True),
    ("north exchange", MAKATI_ANE, {"makati"}, True),
    ("cubao", SPARK, {"quezon city"}, True),
    ("araneta", SPARK, {"quezon city"}, True),
    ("kamuning", SPARK, {"quezon city"}, True),
    ("socorro", SPARK, {"quezon city"}, False),
    ("commonwealth", UP_AYALA, {"quezon city"}, True),
    ("batasan", UP_AYALA, {"quezon city"}, True),
    ("fairview", UP_AYALA, {"quezon city"}, True),
    ("novaliches", UP_AYALA, {"quezon city"}, True),
    ("holy spirit", UP_AYALA, {"quezon city"}, False),
    ("teachers village", UP_AYALA, {"quezon city"}, False),
    ("west avenue", CYBERWEST, {"quezon city"}, True),
    ("sm north", CYBERWEST, {"quezon city"}, True),
    ("balintawak", CYBERWEST, {"quezon city", "caloocan"}, True),
    ("bago bantay", CYBERWEST, {"quezon city"}, False),
    ("project 6", CYBERWEST, {"quezon city"}, False),
    ("project 7", CYBERWEST, {"quezon city"}, False),
    ("project 8", CYBERWEST, {"quezon city"}, False),
    ("eastwood", EASTWOOD, {"quezon city"}, True),
    ("libis", EASTWOOD, {"quezon city"}, True),
    ("loyola heights", EASTWOOD, {"quezon city"}, False),
    ("white plains", EASTWOOD, {"quezon city"}, False),
    ("blue ridge", EASTWOOD, {"quezon city"}, False),
    ("katipunan", EASTWOOD, {"quezon city"}, True),
    ("eton", ETON, {"quezon city"}, True),
    ("centris", ETON, {"quezon city"}, True),
    ("quezon avenue", ETON, {"quezon city"}, True),
    ("tomas morato", ETON, {"quezon city"}, True),
    ("greenhills", SHAW, {"san juan", "mandaluyong"}, True),
    ("wack wack", SHAW, {"mandaluyong"}, False),
    ("shaw", SHAW, {"mandaluyong"}, True),
    ("alabang", ALABANG, {"muntinlupa"}, True),
    ("bf homes", ALABANG, {"paranaque", "las pinas", "muntinlupa"}, True),
]

EMPTY_LOCATIONS = {
    "", "n a", "na", "none", "null", "not specified", "not specify",
    "philippines", "ph", "pilipinas", "anywhere", "any", "ncr",
    "metro manila", "manila ncr",
}
GENERIC_BARANGAY = {
    "poblacion", "pob", "san isidro", "san jose", "san roque", "san vicente",
    "santo nino", "san antonio", "santa cruz", "san juan", "san miguel",
    "salvacion", "buenavista", "san agustin", "santa maria", "san nicolas",
    "san francisco", "san rafael", "santo tomas", "san pedro", "centro",
    "crossing", "proper", "zone",
}
def _place_name(keys: list[str]) -> str:
    """Name used for landmark checks. Keeps 'quezon city' and drops 'city of'."""
    city_names = {pair[0] for pair in CITY_SITE}
    for key in keys:
        if key in NCR_SITE or key in city_names:
            return key
    cores = [key for key in keys if "city" not in key.split()]
    return cores[0] if cores else keys[0]


SKIP_KEYS = {
    "city", "north", "south", "east", "west", "district", "first", "second",
    "third", "fourth", "ncr", "capital", "pob", "poblacion",
}
TOKEN_FIX = {"sta": "santa", "sto": "santo", "brgy": "", "barangay": "", "bgy": ""}
NCR_PROVINCES = {"1339", "1374", "1375", "1376"}


def norm_location(value: str) -> str:
    text = str(value or "").lower().replace("ñ", "n").replace("\u5e3d", "n").replace("ã±", "n")
    text = text.replace("’", " ").replace("'", " ")
    for char in ",./()[]\\_+&":
        text = text.replace(char, " ")
    text = text.replace("-", " ")
    return " ".join(text.split())


def _keys_for(desc: str) -> list[str]:
    extras = [norm_location(part) for part in re.findall(r"\(([^)]*)\)", desc)]
    main = norm_location(re.sub(r"\([^)]*\)", " ", desc))
    found: list[str] = []

    def add(value: str, allow_short: bool = False) -> None:
        text = " ".join(value.split())
        minimum = 3 if allow_short else 4
        if len(text) < minimum or text in SKIP_KEYS or text in found:
            return
        found.append(text)

    add(main, allow_short=True)
    if main.startswith("city of "):
        core = main[len("city of "):].strip()
        add(core)
        add(f"{core} city")
    elif main.endswith(" city"):
        core = main[:-5].strip()
        add(core)
        add(f"city of {core}")
    if re.search(r"\bi+\b", main):
        add(re.sub(r"\bi+\b", " ", main))
    for extra in extras:
        if extra not in {"capital", "pob", "poblacion"}:
            add(extra)
    return found


class _City:
    def __init__(self, code: str, prov_code: str, name: str, keys: list[str], site: tuple[str, str], chartered: bool):
        self.code = code
        self.prov_code = prov_code
        self.name = name
        self.keys = keys
        self.site = site
        self.chartered = chartered


def _read_csv(name: str) -> list[dict[str, str]]:
    path = DATA_DIR / name
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def _index() -> dict:
    provinces = []
    province_keys: set[str] = set()
    for row in _read_csv("provinces.csv"):
        if row["provCode"] in NCR_PROVINCES:
            continue
        if row["provCode"] not in PROVINCE_SITE:
            continue
        keys = _keys_for(row["provDesc"])
        # "City of Isabela" is a city, not the province of Isabela.
        if row["provCode"] == "0997":
            keys = [key for key in keys if key not in {"isabela"}]
        provinces.append({"code": row["provCode"], "name": row["provDesc"], "keys": keys})
        province_keys.update(keys)

    cities = []
    for row in _read_csv("municipalities.csv"):
        prov = row["provCode"]
        all_keys = _keys_for(row["citymunDesc"])
        if not all_keys:
            continue
        # Keep a municipality that is literally named Quezon or Bulacan.
        # Drop the bare province word stripped from "Quezon City" or "Cebu City".
        main_key = all_keys[0]
        keys = [key for key in all_keys if key == main_key or key not in province_keys]
        name = _place_name(keys)
        if prov in NCR_PROVINCES:
            site = next((NCR_SITE[key] for key in keys if key in NCR_SITE), None)
            if site is None:
                continue
        else:
            site = next((CITY_SITE[(key, prov)] for key in keys if (key, prov) in CITY_SITE), None)
            site = site or PROVINCE_SITE.get(prov)
            if site is None:
                continue
        chartered = "city" in norm_location(row["citymunDesc"]).split()
        cities.append(_City(row["citymunCode"], prov, name, keys, site, chartered))

    city_entries = []
    for city in cities:
        for key in city.keys:
            city_entries.append((key, city))
    city_entries.sort(key=lambda item: len(item[0]), reverse=True)
    key_count: dict[str, int] = {}
    for key, _city in city_entries:
        key_count[key] = key_count.get(key, 0) + 1
    unique_keys = {key for key, count in key_count.items() if count == 1}

    province_entries = []
    for province in provinces:
        for key in province["keys"]:
            province_entries.append((key, province))
    province_entries.sort(key=lambda item: len(item[0]), reverse=True)
    province_key_set = {key for key, _province in province_entries}

    barangay_hits: dict[str, set[tuple[str, str]]] = {}
    for row in _read_csv("barangays.csv"):
        for key in _keys_for(row["brgyDesc"]):
            if key in GENERIC_BARANGAY or len(key) < 8 or len(key.split()) < 2:
                continue
            barangay_hits.setdefault(key, set()).add((row["citymunCode"], row["provCode"]))
    unique_barangay = {
        key: next(iter(pairs))
        for key, pairs in barangay_hits.items()
        if len(pairs) == 1
    }
    barangay_entries = sorted(unique_barangay.items(), key=lambda item: len(item[0]), reverse=True)
    by_code = {city.code: city for city in cities}
    return {
        "unique_keys": unique_keys,
        "province_keys": province_key_set,
        "cities": city_entries,
        "provinces": province_entries,
        "barangays": barangay_entries,
        "by_code": by_code,
    }


def _prepare(location: str) -> str:
    words = []
    for word in norm_location(location).split():
        words.append(TOKEN_FIX.get(word, word))
    text = " ".join(word for word in words if word)
    padded = f" {text} "
    for source, target in (
        (" metro manila ", " "),
        (" qc ", " quezon city "),
        (" q c ", " quezon city "),
        (" cdo ", " cagayan de oro "),
        (" cdoc ", " cagayan de oro "),
        (" gensan ", " general santos "),
        (" gen san ", " general santos "),
        (" ilo ilo ", " iloilo "),
        (" gen trias ", " general trias "),
        (" ozamiz ", " ozamis "),
        (" rodriquez ", " rodriguez "),
        (" bukindon ", " bukidnon "),
        (" cagayab ", " cagayan "),
        (" anges ", " angeles "),
    ):
        padded = padded.replace(source, f" {target} ")
    return " ".join(padded.split())


def _hits(padded: str, entries: list) -> list:
    found = []
    space = f" {padded} "
    for key, entry in entries:
        if f" {key} " in space:
            found.append((key, entry))
    keys = [key for key, _ in found]
    kept = []
    for key, entry in found:
        if any(other != key and f" {key} " in f" {other} " for other in keys):
            continue
        kept.append((key, entry))
    return kept


_FILLER = {"philippines", "pilipinas", "ph", "ncr", "capital"}
_SAINT = {"santa", "santo", "san"}


def _drop_incomplete(hits: list, text: str, province_keys: set[str]) -> list:
    """Drop a place that is only the start of the written name.

    'Santa' is not the Ilocos town in 'Santa Mesa'. 'San Felipe' is not the
    Zambales town when the next word is 'Naga'. 'Davao City, Philippines'
    stays Davao City.
    """
    keys = {key for key, _entry in hits}
    kept = []
    padded = f" {text} "
    for key, entry in hits:
        rest = padded.split(f" {key} ", 1)[-1]
        nxt = rest.split(" ", 1)[0] if rest else ""
        if not nxt or nxt in _FILLER or nxt == "city" or nxt in province_keys:
            kept.append((key, entry))
            continue
        if key.endswith(" city") or key.startswith("city of "):
            kept.append((key, entry))
            continue
        starts_another = any(other != key and (other == nxt or other.startswith(nxt + " ")) for other in keys)
        saint_prefix = key in _SAINT or (key.split()[0] in _SAINT and len(key.split()) == 1)
        if saint_prefix or starts_another:
            continue
        kept.append((key, entry))
    return kept


# A bare name that is a chartered city in more than one province.
# Used only when the address does not name a province.
BARE_CITY = {"naga": "051724", "naga city": "051724"}
MANILA_DISTRICTS = (("santa mesa", SAN_LAZARO), ("san andres bukid", SAN_LAZARO))
REGIONS = (("bicol", NAGA), ("ilocos", BAGUIO))


def _landmark(padded: str, city_name: str | None, have_place: bool) -> tuple[str, str] | None:
    space = f" {padded} "
    found = []
    for phrase, site, cities, allow_without_city in LANDMARKS:
        if f" {phrase} " not in space:
            continue
        if city_name:
            if cities is not None and city_name not in cities:
                continue
        elif have_place or not allow_without_city:
            continue
        found.append((len(phrase), site))
    if not found:
        return None
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def nearest_site(location: str) -> tuple[str, str]:
    """Return the Concentrix campaign name and id for a Philippine address."""
    text = _prepare(location)
    if text in EMPTY_LOCATIONS:
        return WAH
    space = f" {text} "
    if " bm north " in space or " wah north " in space or " work at home north " in space:
        return WAH_NORTH
    if " bm south " in space or " wah south " in space or " work at home south " in space:
        return WAH_SOUTH

    index = _index()
    city_hits = _hits(text, index["cities"])
    province_hits = _hits(text, index["provinces"])
    city_keys = [key for key, _ in city_hits]
    # "Isabela City" is longer than the province Isabela. "Cagayan de Oro" is longer than Cagayan.
    province_hits = [
        item for item in province_hits
        if not any(len(key) > len(item[0]) and f" {item[0]} " in f" {key} " for key in city_keys)
    ]
    city_hits = [
        item for item in city_hits
        if len(item[0]) >= 4 or item[0] == text
    ]
    city_hits = [
        item for item in city_hits
        if not any(
            len(key) > len(item[0]) and f" {item[0]} " in f" {key} " and item[1].prov_code != province["code"]
            for key, province in province_hits
        )
    ]
    city_hits = _drop_incomplete(city_hits, text, index["province_keys"])
    province_codes = {province["code"] for _, province in province_hits}
    mentions_manila = " manila " in f" {text} " and " quezon city " not in f" {text} "
    if mentions_manila:
        districts = [item for item in city_hits if item[1].prov_code == "1339"]
        other_ncr = [
            item for item in city_hits
            if item[1].prov_code in NCR_PROVINCES and item[1].prov_code != "1339"
        ]
        if districts and not other_ncr:
            city_hits = districts
        elif not districts and not other_ncr:
            city_hits = [item for item in city_hits if item[1].prov_code in province_codes]

    if province_codes:
        in_province = [item for item in city_hits if item[1].prov_code in province_codes]
        if in_province:
            in_keys = {key for key, _city in in_province}
            named_outside = [
                item for item in city_hits
                if item[1].prov_code not in province_codes and item[0] not in in_keys
            ]
            city_hits = in_province + named_outside

    chosen = None
    site = None
    by_code: dict[str, _City] = {}
    longest: dict[str, int] = {}
    for key, city in city_hits:
        by_code[city.code] = city
        longest[city.code] = max(longest.get(city.code, 0), len(key))
    province_name_codes = {key: province["code"] for key, province in province_hits}
    if len(province_codes) > 1 and len(by_code) > 1:
        cross = [
            city for city in by_code.values()
            if city.name in province_name_codes
            and city.prov_code in province_codes
            and province_name_codes[city.name] != city.prov_code
        ]
        if len({city.code for city in cross}) == 1:
            chosen = cross[0]
            site = chosen.site
            by_code = {chosen.code: chosen}
    # "Isabela" is the province. The municipality Isabela in Negros is a different place.
    if chosen is None and province_name_codes:
        kept = {
            code: city for code, city in by_code.items()
            if city.name not in province_name_codes
            or city.prov_code == province_name_codes[city.name]
            or city.prov_code in province_codes
        }
        if kept != by_code:
            by_code = kept
            longest = {code: longest[code] for code in by_code}
    unique_codes = {
        city.code: city
        for key, city in city_hits
        if key in index["unique_keys"] and city.code in by_code
    }
    if chosen is None and len(unique_codes) == 1 and len(by_code) > 1:
        by_code = unique_codes
        longest = {code: longest.get(code, 0) for code in by_code}
    chartered = {code: city for code, city in by_code.items() if city.chartered}
    if chosen is None and len(chartered) == 1 and len(by_code) > 1:
        by_code = chartered
    if chosen is None and not province_codes and len(by_code) > 1:
        for key, city in city_hits:
            preferred = BARE_CITY.get(key)
            if preferred and preferred in by_code:
                by_code = {preferred: by_code[preferred]}
                break
    if chosen is None and len(by_code) == 1:
        chosen = next(iter(by_code.values()))
        site = chosen.site
    elif chosen is None and by_code:
        sites = {city.site for city in by_code.values()}
        if len(sites) == 1:
            site = next(iter(sites))
        else:
            best_len = max(longest.values())
            best_codes = [code for code, length in longest.items() if length == best_len]
            if len(best_codes) == 1:
                chosen = by_code[best_codes[0]]
                site = chosen.site

    if chosen is None and site is None and mentions_manila and not by_code:
        site = SAN_LAZARO

    if chosen is None and site is None and province_codes:
        province_sites = {PROVINCE_SITE[code] for code in province_codes if code in PROVINCE_SITE}
        if len(province_sites) == 1:
            site = next(iter(province_sites))
        elif province_hits:
            province_hits.sort(key=lambda item: len(item[0]), reverse=True)
            top = province_hits[0][0]
            top_sites = {
                PROVINCE_SITE[province["code"]]
                for key, province in province_hits
                if key == top and province["code"] in PROVINCE_SITE
            }
            if len(top_sites) == 1:
                site = next(iter(top_sites))

    if chosen is None and site is None:
        for key, (city_code, prov_code) in _hits(text, index["barangays"]):
            city = index["by_code"].get(city_code)
            if city is None:
                continue
            if province_codes and prov_code not in province_codes:
                continue
            chosen = city
            site = city.site
            break

    have_place = chosen is not None or site is not None
    landmark = _landmark(text, chosen.name if chosen else None, have_place)
    if landmark:
        return landmark
    if site:
        return site
    padded = f" {text} "
    for phrase, district in MANILA_DISTRICTS:
        if f" {phrase} " in padded:
            return district
    for phrase, region in REGIONS:
        if f" {phrase} " in padded:
            return region
    return WAH
