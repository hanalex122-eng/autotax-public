"""
AutoTax-HUB Invoice Parser v2.0
───────────────────────────────
Extracts structured data from OCR raw text:
  - vendor name
  - category (auto-detected from vendor)
  - date (multi-format)
  - total amount
  - VAT rate & amount (with country defaults)
  - invoice/receipt number
  - payment method
  - country detection
"""

import re
from datetime import datetime

# ════════════════════════════════════════════════════════════════
# VENDOR → CATEGORY MAPPING
# ════════════════════════════════════════════════════════════════

VENDOR_CATEGORY_MAP: dict[str, str] = {
    # Supermarkets / Food
    "lidl": "food",
    "aldi": "food",
    "auchan": "food",
    "rewe": "food",
    "edeka": "food",
    "netto": "food",
    "penny": "food",
    "kaufland": "food",
    "norma": "food",
    "carrefour": "food",
    "leclerc": "food",
    "intermarche": "food",
    "intermarché": "food",
    "monoprix": "food",
    "migros": "food",
    "coop": "food",
    "spar": "food",
    "globus": "food",
    "real": "food",
    "tegut": "food",
    "hit": "food",
    "nahkauf": "food",
    "wasgau": "food",
    "famila": "food",
    "combi": "food",
    "marktkauf": "food",
    "denn's": "food",
    "bio company": "food",
    "basic": "food",
    "alnatura": "food",

    # Restaurants / Cafes
    "starbucks": "restaurant",
    "mcdonald": "restaurant",
    "mcdonalds": "restaurant",
    "mcdonald's": "restaurant",
    "burger king": "restaurant",
    "subway": "restaurant",
    "kfc": "restaurant",
    "dominos": "restaurant",
    "domino's": "restaurant",
    "pizza hut": "restaurant",
    "dunkin": "restaurant",
    "nordsee": "restaurant",
    "backwerk": "restaurant",
    "back-factory": "restaurant",
    "dean & david": "restaurant",
    "vapiano": "restaurant",
    "hans im glück": "restaurant",
    "hans im glueck": "restaurant",
    "peter pane": "restaurant",
    "alex": "restaurant",
    "block house": "restaurant",

    # Clothing / Shoes
    "deichmann": "clothing",
    "h&m": "clothing",
    "zara": "clothing",
    "c&a": "clothing",
    "primark": "clothing",
    "kik": "clothing",
    "takko": "clothing",
    "new yorker": "clothing",
    "esprit": "clothing",
    "jack & jones": "clothing",
    "peek & cloppenburg": "clothing",
    "p&c": "clothing",
    "zalando": "clothing",

    # Fuel / Gas Stations
    "shell": "fuel",
    "aral": "fuel",
    "total": "fuel",
    "totalenergies": "fuel",
    "esso": "fuel",
    "bp": "fuel",
    "jet": "fuel",
    "star": "fuel",
    "agip": "fuel",
    "eni": "fuel",
    "hem": "fuel",
    "avia": "fuel",
    "q1": "fuel",
    "tankstelle": "fuel",
    "bft": "fuel",

    # Electronics
    "saturn": "electronics",
    "mediamarkt": "electronics",
    "media markt": "electronics",
    "conrad": "electronics",
    "apple": "electronics",
    "notebooksbilliger": "electronics",
    "cyberport": "electronics",
    "alternate": "electronics",
    "expert": "electronics",
    "euronics": "electronics",

    # Drugstores / Health
    "dm": "health",
    "rossmann": "health",
    "müller": "health",
    "mueller": "health",
    "apotheke": "health",
    "pharmacy": "health",
    "pharmacie": "health",
    "douglas": "health",

    # Office Supplies
    "staples": "office",
    "viking": "office",
    "bürobedarf": "office",
    "mcpaper": "office",
    "pagro": "office",

    # Hardware / Home
    "bauhaus": "home",
    "obi": "home",
    "hornbach": "home",
    "toom": "home",
    "hagebau": "home",
    "ikea": "home",
    "roller": "home",
    "poco": "home",
    "mömax": "home",

    # Transport / Travel
    "deutsche bahn": "transport",
    "db ": "transport",
    "flixbus": "transport",
    "uber": "transport",
    "bolt": "transport",
    "taxi": "transport",
    "lufthansa": "transport",
    "ryanair": "transport",
    "easyjet": "transport",

    # Telecom / Internet
    "telekom": "telecom",
    "vodafone": "telecom",
    "o2": "telecom",
    "1&1": "telecom",
    "congstar": "telecom",

    # Insurance
    "allianz": "insurance",
    "huk": "insurance",
    "ergo": "insurance",
    "axa": "insurance",

    # Post / Shipping
    "deutsche post": "shipping",
    "dhl": "shipping",
    "hermes": "shipping",
    "dpd": "shipping",
    "gls": "shipping",
    "ups": "shipping",
    "fedex": "shipping",

    # Software / Subscriptions
    "amazon": "shopping",
    "ebay": "shopping",
    "paypal": "shopping",
    "walmart": "shopping",
    "action": "shopping",
    "tedi": "shopping",
    "target": "shopping",
    "costco": "shopping",
    "tk maxx": "shopping",
    "microsoft": "software",
    "google": "software",
    "adobe": "software",
    "spotify": "subscription",
    "netflix": "subscription",
}

# ════════════════════════════════════════════════════════════════
# MERCHANT NORMALIZATION (lightweight brand detection from OCR)
# ════════════════════════════════════════════════════════════════

# canonical_name → list of OCR variations (lowercase, no special handling needed)
_MERCHANT_ALIASES: dict[str, list[str]] = {
    "REWE":       ["rewe", "r e w e", "rewe markt", "rewe city", "rewe center", "rewe to go"],
    "EDEKA":      ["edeka", "e d e k a", "edeka center", "edeka markt", "e center", "edeka neukauf", "nah und gut"],
    "ALDI":       ["aldi", "aldi sud", "aldi süd", "aldi sued", "aldi nord", "a l d i", "aldi se", "aldi gmbh"],
    "LIDL":       ["lidl", "l i d l", "lidl stiftung", "lidl dienstleistung", "lidl vertriebs"],
    "NETTO":      ["netto", "netto marken-discount", "netto marken discount", "netto discount", "netto filiale"],
    "PENNY":      ["penny", "penny markt", "penny rewe", "p e n n y"],
    "KAUFLAND":   ["kaufland", "k a u f l a n d", "kaufland warenhandel", "kaufland dienstleistung"],
    "DM":         ["dm-drogerie", "dm drogerie", "dm-markt", "dm markt", "dm filiale"],
    "Rossmann":   ["rossmann", "dirk rossmann", "rossmann gmbh"],
    "IKEA":       ["ikea", "i k e a", "ikea deutschland", "ikea einrichtungshaus"],
    "OBI":        ["obi", "obi markt", "obi baumarkt"],
    "Hornbach":   ["hornbach", "hornbach baumarkt", "hornbach holding"],
    "BAUHAUS":    ["bauhaus", "bauhaus gmbh"],
    "MediaMarkt": ["mediamarkt", "media markt", "media-markt", "mediamarkt saturn", "media markt saturn"],
    "Saturn":     ["saturn", "saturn electro", "saturn elektro"],
    "Amazon":     ["amazon", "amzn", "amazon.de", "amazon eu", "amazon payments", "amazon marketplace", "amz"],
    "Zalando":    ["zalando", "zalando se", "zalando payments"],
    "Shell":      ["shell", "shell station", "shell deutschland", "shell tankstelle"],
    "Aral":       ["aral", "aral ag", "aral tankstelle", "bp aral"],
    "TotalEnergies": ["total", "totalenergies", "total station", "total tankstelle"],
    "NORMA":      ["norma", "norma lebensmittel"],
    "tegut":      ["tegut", "tegut gute lebensmittel"],
    "Globus":     ["globus", "globus baumarkt", "globus sb-warenhaus"],
    "Müller":     ["müller", "mueller", "müller drogerie", "mueller drogerie"],
    "Douglas":    ["douglas", "douglas parfümerie", "douglas parfumerie"],
    "Deichmann":  ["deichmann", "deichmann se"],
    "H&M":        ["h&m", "h & m", "hennes & mauritz", "hennes mauritz"],
    "ZARA":       ["zara", "zara deutschland", "inditex"],
    "C&A":        ["c&a", "c & a", "c und a"],
    "Primark":    ["primark", "primark mode"],
    "Toom":       ["toom", "toom baumarkt"],
    "POCO":       ["poco", "poco domäne", "poco einrichtungsmarkt"],
    "Conrad":     ["conrad", "conrad electronic", "conrad elektronik"],
    "Deutsche Bahn": ["deutsche bahn", "db fernverkehr", "db regio", "db vertrieb", "db station"],
    "Telekom":    ["telekom", "deutsche telekom", "t-mobile", "t mobile"],
    "Vodafone":   ["vodafone", "vodafone gmbh", "vodafone deutschland"],
    "O2":         ["o2", "telefonica", "telefónica"],
    "DHL":        ["dhl", "dhl paket", "dhl express", "deutsche post dhl"],
    "Hermes":     ["hermes", "hermes versand", "hermes paketshop"],
    "McDonald's": ["mcdonald", "mcdonalds", "mcdonald's", "mc donalds", "mc donald"],
    "Burger King":["burger king", "burgerking"],
    "Starbucks":  ["starbucks", "starbucks coffee"],
    "Subway":     ["subway", "subway restaurant"],
    "Flixbus":    ["flixbus", "flix se", "flixtrain"],
    "ESSO":       ["esso", "esso station", "esso tankstelle"],
    "JET":        ["jet tankstelle", "jet station"],
    "Allianz":    ["allianz", "allianz versicherung", "allianz se"],
    "HUK-COBURG": ["huk", "huk-coburg", "huk coburg"],
    "PayPal":     ["paypal", "paypal europe"],
    "eBay":       ["ebay", "ebay kleinanzeigen", "ebay gmbh"],
    "Spotify":    ["spotify", "spotify ab", "spotify technology"],
    "Netflix":    ["netflix", "netflix international"],
    "Google":     ["google", "google ireland", "google payment", "google cloud"],
    "Microsoft":  ["microsoft", "microsoft ireland", "microsoft 365"],
    "Apple":      ["apple", "apple distribution", "apple store", "itunes"],
    "Adobe":      ["adobe", "adobe systems", "adobe inc"],
}

# Pre-build a fast lookup: normalized_alias → canonical_name
_MERCHANT_LOOKUP: dict[str, str] = {}
for _canon, _aliases in _MERCHANT_ALIASES.items():
    for _alias in _aliases:
        _MERCHANT_LOOKUP[_alias] = _canon


def _normalize_for_merchant(text: str) -> str:
    """Normalize text for merchant matching: lowercase, collapse spaces, normalize umlauts."""
    t = text.lower().strip()
    t = t.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    t = re.sub(r"\s+", " ", t)
    return t


def _netto_is_store_context(text: str) -> bool:
    """True only when 'Netto' looks like the NETTO discounter, not a net-amount
    keyword. 'Netto MwSt / Netto-Betrag / Netto 7%' appears on virtually EVERY
    German receipt and must NOT be matched as the store."""
    t = (text or "").lower()
    if re.search(r"netto\s+marken[\s-]*discount|nettomarkt|ntt[-_]\d", t):
        return True
    for m in re.finditer(r"\bnetto\b", t):
        tail = t[m.end():m.end() + 14]
        if not re.match(r"[\s.:\-]*(?:mwst|brutto|betrag|summe|steuer|umsatz|"
                        r"wert|preis|warenwert|%|\d|eur|€)", tail):
            return True  # a 'netto' NOT followed by an amount keyword -> store
    return False


def detect_merchant(raw_text: str) -> tuple[str, float]:
    """Public wrapper around _detect_merchant_inner with a NETTO net-amount
    guard. Identical for every other merchant; only suppresses the
    'Netto MwSt' -> NETTO false positive (a net-amount line on every receipt)."""
    canon, conf = _detect_merchant_inner(raw_text)
    if canon == "NETTO" and not _netto_is_store_context(raw_text):
        return ("", 0.0)
    return (canon, conf)


def _detect_merchant_inner(raw_text: str) -> tuple[str, float]:
    """Detect merchant/brand from OCR text. Returns (merchant_name, confidence 0.0-1.0).

    Strategy:
    - Scan first 5 lines with high confidence (receipt header)
    - Then scan remaining text with lower confidence
    - Exact alias match preferred, then substring containment
    """
    if not raw_text or not raw_text.strip():
        return ("", 0.0)

    lines = raw_text.strip().split("\n")

    # Phase 1: Exact alias match in first 5 lines (high confidence)
    for i, line in enumerate(lines[:5]):
        norm = _normalize_for_merchant(line)
        for alias, canon in _MERCHANT_LOOKUP.items():
            norm_alias = alias.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
            if norm_alias in norm:
                conf = 0.95 if i < 2 else 0.90 if i < 4 else 0.85
                return (canon, conf)

    # Phase 2: Substring match in first 10 lines (medium confidence)
    for i, line in enumerate(lines[:10]):
        norm = _normalize_for_merchant(line)
        for alias, canon in _MERCHANT_LOOKUP.items():
            norm_alias = alias.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
            if len(norm_alias) >= 4 and norm_alias in norm:
                conf = 0.75 if i < 7 else 0.65
                return (canon, conf)

    # Phase 3: Full text scan (low confidence)
    full_norm = _normalize_for_merchant(raw_text)
    for alias, canon in _MERCHANT_LOOKUP.items():
        norm_alias = alias.replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
        if len(norm_alias) >= 5 and norm_alias in full_norm:
            return (canon, 0.5)

    # Phase 4: OCR noise tolerant — strip ALL spaces/punctuation and match
    full_stripped = re.sub(r"[^a-z0-9]", "", full_norm)
    for alias, canon in _MERCHANT_LOOKUP.items():
        alias_stripped = re.sub(r"[^a-z0-9]", "", alias.lower())
        if len(alias_stripped) >= 4 and alias_stripped in full_stripped:
            return (canon, 0.6)

    # Phase 5: Character proximity — find merchant names with 1-2 char OCR errors
    for i, line in enumerate(lines[:8]):
        line_stripped = re.sub(r"[^a-z0-9]", "", _normalize_for_merchant(line))
        for canon, aliases in _MERCHANT_ALIASES.items():
            canon_stripped = re.sub(r"[^a-z0-9]", "", canon.lower())
            if len(canon_stripped) < 4:
                continue
            # Sliding window match — allow 1 wrong char per 4
            for start in range(len(line_stripped) - len(canon_stripped) + 1):
                chunk = line_stripped[start:start + len(canon_stripped)]
                mismatches = sum(1 for a, b in zip(chunk, canon_stripped) if a != b)
                if mismatches <= max(1, len(canon_stripped) // 4):
                    conf = 0.55 if i < 3 else 0.45
                    return (canon, conf)

    return ("", 0.0)


# ════════════════════════════════════════════════════════════════
# COUNTRY DETECTION & DEFAULT VAT RATES
# ════════════════════════════════════════════════════════════════

COUNTRY_VAT_DEFAULTS: dict[str, float] = {
    "DE": 19.0,
    "FR": 20.0,
    "AT": 20.0,
    "NL": 21.0,
    "BE": 21.0,
    "IT": 22.0,
    "ES": 21.0,
    "PT": 23.0,
    "CH": 8.1,
    "LU": 17.0,
    "PL": 23.0,
    "CZ": 21.0,
    "DK": 25.0,
    "SE": 25.0,
    "FI": 25.5,
    "IE": 23.0,
    "GR": 24.0,
    "HU": 27.0,
    "RO": 19.0,
    "BG": 20.0,
    "HR": 25.0,
    "SK": 23.0,
    "SI": 22.0,
    "LT": 21.0,
    "LV": 21.0,
    "EE": 22.0,
    "CY": 19.0,
    "MT": 18.0,
}

# --- ADDED START: Extra countries with high VAT rates ---
COUNTRY_VAT_DEFAULTS.update({
    "TR": 20.0,   # Türkiye (KDV)
    "GB": 20.0,   # United Kingdom (VAT)
    "NO": 25.0,   # Norway (MVA)
    "IS": 24.0,   # Iceland
    "RS": 20.0,   # Serbia (PDV)
    "BA": 17.0,   # Bosnia (PDV)
    "ME": 21.0,   # Montenegro
    "MK": 18.0,   # North Macedonia (DDV)
    "AL": 20.0,   # Albania (TVSH)
    "XK": 18.0,   # Kosovo
    "UA": 20.0,   # Ukraine (PDV)
    "MD": 20.0,   # Moldova
    "GE": 18.0,   # Georgia
    "IN": 18.0,   # India (GST)
    "BR": 17.0,   # Brazil (ICMS avg)
    "AR": 21.0,   # Argentina (IVA)
    "MX": 16.0,   # Mexico (IVA)
    "CL": 19.0,   # Chile (IVA)
    "CO": 19.0,   # Colombia (IVA)
    "US": 0.0,    # USA (no federal VAT, sales tax varies)
    "CA": 5.0,    # Canada (GST)
    "AU": 10.0,   # Australia (GST)
    "NZ": 15.0,   # New Zealand (GST)
    "JP": 10.0,   # Japan (consumption tax)
    "KR": 10.0,   # South Korea (VAT)
    "CN": 13.0,   # China (VAT)
    "AE": 5.0,    # UAE (VAT)
    "SA": 15.0,   # Saudi Arabia (VAT)
    "IL": 17.0,   # Israel (Ma'am)
    "ZA": 15.0,   # South Africa (VAT)
    "MA": 20.0,   # Morocco (TVA)
    "TN": 19.0,   # Tunisia (TVA)
    "EG": 14.0,   # Egypt (VAT)
    "NG": 7.5,    # Nigeria (VAT)
    "KE": 16.0,   # Kenya (VAT)
    "RU": 20.0,   # Russia (NDS)
})


# --- ADDED END (indicators update moved after dict definition below) ---

COUNTRY_INDICATORS: dict[str, list[str]] = {
    "DE": [
        "deutschland", "germany", "steuer-nr", "steuernummer",
        "ust-id", "ustid", "finanzamt", "handelsregister", "hrb",
        "beleg", "kassenbon", "plz",
        # These are shared with AT/CH but weighted here for DE-only context
        "gmbh", "e.v.", "eur",
    ],
    "FR": [
        "france", "tva", "siret", "siren", "sarl", "sas", "eurl",
        "facture", "montant", "total ttc", "total ht", "rue ",
        "cedex", "arrondissement",
    ],
    "AT": [
        "österreich", "austria", "wien", "graz", "linz", "salzburg",
        "innsbruck", "klagenfurt", "uid-nr", "uid nr",
    ],
    "NL": [
        "nederland", "netherlands", "btw", "kvk", "b.v.", "bv ",
    ],
    "BE": [
        "belgique", "belgie", "belgium", "tva/btw",
    ],
    "IT": [
        "italia", "italy", "iva", "p.iva", "fattura", "scontrino",
        "codice fiscale", "s.r.l.", "s.p.a.",
    ],
    "ES": [
        "españa", "spain", "nif", "cif", "factura", "iva ",
    ],
    "CH": [
        "schweiz", "suisse", "svizzera", "switzerland", "chf",
        "mwst-nr", "che-", "zürich", "bern", "basel", "genf",
        "luzern", "lausanne",
    ],
    "LU": [
        "luxembourg", "luxemburg",
    ],
}

# --- ADDED START: Extra country indicators ---
COUNTRY_INDICATORS.update({
    "TR": [
        "türkiye", "turkey", "kdv", "t.c.", "vergi", "fatura", "fis", "fiş",
        "istanbul", "ankara", "izmir", "antalya", "bursa", "adana",
        "tl", "₺", "turkish lira",
    ],
    "GB": [
        "united kingdom", "uk", "vat reg", "london", "manchester",
        "birmingham", "ltd", "plc", "£", "gbp",
    ],
    "NO": [
        "norge", "norway", "mva", "org.nr", "oslo", "bergen", "nok",
    ],
    "RS": [
        "srbija", "serbia", "pdv", "beograd", "pib", "rsd",
    ],
    "UA": [
        "україна", "ukraine", "pdv", "kyiv", "uah", "грн",
    ],
    "RU": [
        "россия", "russia", "ндс", "nds", "inn", "москва", "rub", "₽",
    ],
})
# --- ADDED END ---

# Known reduced VAT rates per country
KNOWN_VAT_RATES: dict[str, list[float]] = {
    "DE": [19.0, 7.0],
    "FR": [20.0, 10.0, 5.5, 2.1],
    "AT": [20.0, 13.0, 10.0],
    "NL": [21.0, 9.0],
    "BE": [21.0, 12.0, 6.0],
    "IT": [22.0, 10.0, 5.0, 4.0],
    "ES": [21.0, 10.0, 4.0],
    "CH": [8.1, 3.8, 2.6],
    "LU": [17.0, 14.0, 8.0, 3.0],
}

# --- ADDED START: Extra country VAT rates ---
KNOWN_VAT_RATES.update({
    "TR": [20.0, 10.0, 1.0],
    "GB": [20.0, 5.0, 0.0],
    "NO": [25.0, 15.0, 12.0],
    "IS": [24.0, 11.0],
    "RS": [20.0, 10.0],
    "UA": [20.0, 14.0, 7.0],
    "IN": [28.0, 18.0, 12.0, 5.0],
    "BR": [17.0, 12.0, 7.0],
    "AR": [21.0, 10.5, 27.0],
    "MX": [16.0, 0.0],
    "JP": [10.0, 8.0],
    "CN": [13.0, 9.0, 6.0],
    "AE": [5.0],
    "SA": [15.0],
    "RU": [20.0, 10.0],
})
# --- ADDED END ---

# ════════════════════════════════════════════════════════════════
# NORMALIZATION
# ════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    """Normalize OCR text for amount/keyword extraction."""
    t = text.lower()
    # Replace newlines with spaces (OCR splits keywords across lines)
    t = re.sub(r"\n+", " ", t)
    # Standardize currency symbols
    t = t.replace("€", " EUR ")
    t = t.replace("chf", " CHF ")
    # Fix common OCR artifacts
    t = re.sub(r"[|l](?=\d)", "1", t)  # l or | before digits -> 1
    # Normalize spaces around EUR
    t = re.sub(r"\beur\.?\b", " EUR ", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_amount_text(text: str) -> str:
    """Prepare text for amount extraction: handle EU comma decimals."""
    t = text
    # Convert "1.234,56" to "1234.56" (dot-thousands + comma-decimals)
    t = re.sub(r"(\d{1,3})\.(\d{3}),(\d{2})\b", lambda m: f"{m.group(1)}{m.group(2)}.{m.group(3)}", t)
    # Simple comma decimal: "12,99" -> "12.99"
    t = re.sub(r"(\d+),(\d{2})\b", r"\1.\2", t)
    return t


# ════════════════════════════════════════════════════════════════
# VENDOR EXTRACTION
# ════════════════════════════════════════════════════════════════

# Common non-vendor lines to skip
_SKIP_PATTERNS = re.compile(
    r"^("
    r"datum|date|kasse|filiale|bon|beleg|rechnung|quittung|invoice|facture|receipt"
    r"|tel\.?\s|fax|fon|phone|www\.|http|email|e-mail"
    r"|ust|mwst|steuer|tax\b|tva|iva|btw"
    r"|str\.|straße|strasse|platz\b|weg\b|allee|gasse|rue |avenue|boulevard"
    r"|am\s+\w+\s+\d"  # "Am Staden 4" style addresses
    r"|[a-zäöü]+\w*\s+str\.?\s"  # "Mainzer Str. 45" style
    r"|[a-zäöü]+\w*\s+straße"  # "Hauptstraße" etc.
    r"|\w+str\.?\s+\d"  # "Stiftsbergstr. 1" style
    r"|[a-zäöü]+-?\w*-?str\.\s*\d"  # "Heinrich-Deichmann-Str. 9"
    r"|europa-allee|berliner\s+promenade"  # common street names
    r"|\d{4,5}\s+\w"  # postal code + city
    r"|.*@.*\.\w{2,4}"  # email
    r"|vielen\s+dank|merci|thank"  # thank you lines
    r"|zone\s+commerciale"  # FR shopping zone
    # Digital PDF (Stripe/Anthropic/Resend/Verdent) ortak artiklari
    r"|page\s+\d|seite\s+\d|of\s+\d+"
    r"|invoice\s+(number|date|due|to)|date\s+of\s+issue|date\s+due"
    r"|bill\s+to|ship\s+to|sold\s+to|payable\s+to|pay\s+online|pay\s+to|amount\s+due"
    r"|description|qty|unit\s+price|subtotal|total\s+excluding"
    r"|please|dear\s+|hallo\s+|sehr\s+geehrte"
    r")",
    re.IGNORECASE
)

# Business entity suffixes — matched with word boundaries
_VENDOR_SUFFIX_RE = re.compile(
    r"\b(?:gmbh|mbh|ohg|e\.?k\.?|e\.?v\.?|"
    r"ltd\.?|inc\.?|sarl|sas|eurl|"
    r"s\.?r\.?l\.?|s\.?p\.?a\.?|b\.?v\.?|ug)\b"
    r"|(?:\bco\.\s*kg\b|\b&\s*co\.?\b|\bag\b|\bkg\b|\bsa\b)",
    re.IGNORECASE,
)

# Lines that look like product/item lines (text + price at end)
_ITEM_LINE_RE = re.compile(r".+\s+\d+[.,]\d{2}\s*$")

# Lines that are totals/subtotals
_TOTAL_LINE_RE = re.compile(
    r"^(summe|total|gesamt|betrag|brutto|netto|gesamtbetrag|endbetrag|"
    r"zu\s*zahlen|zahlbetrag|zwischensumme|subtotal|montant|inkl|davon|"
    r"mwst|ust|tva|vat|steuer|gegeben|rückgeld|wechselgeld|"
    r"kartenzahlung|barzahlung|visa|mastercard|ec-karte|girocard|"
    r"paiement|payment|bezahlt|rendu)\b",
    re.IGNORECASE,
)


# Vendor fingerprint detection — barcode prefix / cash-register serial / company-name pattern.
# Used as a HIGH-priority signal BEFORE logo OCR (which is fragile). Each
# entry is (regex, canonical_vendor_name). First match wins, so order
# matters — most specific patterns first.
#
# Why this works: the ~22-digit Lidl Kassenbon barcode (e.g.
# 0888303235949102030326 / 0888413060839701290526) starts with '0888' on
# every Lidl receipt regardless of branch. The 'LDL-NNN-XX' kasa serial is
# printed as text on every receipt. Even when the logo is mangled by OCR,
# these stable strings survive.
_VENDOR_FINGERPRINTS = [
    # Lidl — Kassenbon barcode '0888' + ~18 hane (sube farketmez) + kasa
    # serisi 'LDL-NNN-XX'. (2026-06-05: eski '0888303' sabit prefix ve
    # 'LDL-NN-NNN' dar formati gercek fislerde — 0888413..., LDL-000-4T —
    # eslesmiyordu; gercek ornekle kanitlanip genisletildi.)
    (r"\b0888\d{16,19}\b", "LIDL"),
    (r"\bLDL[-_]\d{2,4}[-_]\w{1,5}", "LIDL"),
    (r"\bLidl\s+Stiftung", "LIDL"),
    (r"\bLidl\s+Plus\b", "LIDL"),
    # Aldi
    (r"\bALD[I1l][-_]\d", "ALDI"),
    (r"\bALDI\s+SE\b|\bAldi\s+(?:Süd|Sued|Nord|Einkauf)\b", "ALDI"),
    # Rewe
    (r"\bREW[E3][-_]\d|\bRewe\s+Markt\s+GmbH\b", "REWE"),
    # Edeka
    (r"\bEDK[-_]\d|\bEDEKA\s+(?:Center|Markt)\b", "EDEKA"),
    # Penny
    (r"\bPenny\s+Markt\b|\bPNY[-_]\d", "PENNY"),
    # Netto
    (r"\bNetto\s+Marken[-\s]?Discount\b|\bNTT[-_]\d", "NETTO"),
    # Kaufland
    (r"\bKaufland\s+(?:Dienstleistung|Stiftung|Warenhandel)", "KAUFLAND"),
    # Norma
    (r"\bNORMA\s+Lebensmittelfilialbetrieb", "NORMA"),
    # Action — Action Deutschland GmbH
    (r"\bAction\s+Deutschland\s+GmbH", "ACTION"),
    # TEDI — TEDi GmbH & Co. KG
    (r"\bTEDi\s+GmbH\b|\bTEDi\.de\b|\bSteinstr\.?\s*2/4\s*66115", "TEDI"),
    # KiK
    (r"\bKiK\s+Textilien\b", "KIK"),
    # dm-drogerie markt — 'dm-drogerie markt' her fisin footer'inda yazili.
    # (2026-06-05: dm taninmiyordu; marka-metni fingerprint eklendi. Gercek
    # dm fisi gelince barkod/USt-ID ile guclendirilecek.)
    (r"\bdm[-\s]?drogerie\s*markt", "dm"),
    (r"\bdm[-\s]?drogerie\b", "dm"),
    # Drugstores
    (r"\bdm[-\s]?drogerie\s+markt\b|\bdm\s+Drogeriemarkt\b", "DM"),
    (r"\bDirk\s+Rossmann\b|\bRossmann\s+GmbH\b|\bROSSMANN\s+\d", "ROSSMANN"),
    (r"\bMüller\s+Holding\b|\bDrogerie\s+Müller\b", "MÜLLER"),
    # Electronics
    (r"\bMedia\s*[-\s]?Markt\s+(?:Saturn|TV)\b|\bMediaMarktSaturn\b", "MEDIA MARKT"),
    (r"\bSaturn\s+Electro\b", "SATURN"),
    # Fuel stations
    (r"\bAral\s+(?:AG|Tankstelle)\b|\bARAL\s+AG\s+27/151", "ARAL"),
    (r"\bShell\s+Deutschland\b|\bShell\s+Tankstelle\b", "SHELL"),
    (r"\bEsso\s+Tankstelle\b|\bEsso\s+Deutschland\b", "ESSO"),
    (r"\bJet\s+Tankstellen\s+Deutschland\b", "JET"),
    # Clothing / Fashion
    (r"\bSNIPES\s+SE\b|\bsnipes:", "SNIPES"),
    (r"\bDeichmann\s+SE\b|\bDeichmann\s+Schuhe\b", "DEICHMANN"),
    (r"\bH&M\s+Hennes\s+&\s+Mauritz\b", "H&M"),
    (r"\bC&A\s+Mode\b", "C&A"),
    (r"\bPRIMARK\s+Deutschland\b", "PRIMARK"),
    (r"\bZARA\s+Deutschland\b", "ZARA"),
    # Home / DIY
    (r"\bIKEA\s+Deutschland\b", "IKEA"),
    (r"\bBauhaus\s+(?:AG|Vertriebs)\b", "BAUHAUS"),
    (r"\bOBI\s+(?:GmbH|Bau)\b", "OBI"),
    (r"\bHornbach\s+Baumarkt\b", "HORNBACH"),
    (r"\bToom\s+Baumarkt\b", "TOOM"),
    # Software / Tech (digital invoices)
    (r"\bAdobe\s+Systems\s+Software\b|\bAdobe\s+Ireland\b", "Adobe Systems Ireland"),
    (r"\bMicrosoft\s+(?:Ireland|Deutschland|Corporation)\b", "Microsoft"),
    (r"\bGoogle\s+(?:Ireland|Cloud|LLC)\b", "Google"),
    (r"\bAmazon\s+(?:EU|Web\s+Services|Services\s+Europe)\b", "Amazon"),
    (r"\bApple\s+(?:Distribution|Inc\.?)\b", "Apple"),
    (r"\bTopaz\s+Labs\b", "Topaz Labs"),
    # Telecom
    (r"\bDeutsche\s+Telekom\s+AG\b|\bTelekom\s+Deutschland\b", "Telekom"),
    (r"\bVodafone\s+(?:GmbH|Deutschland)\b", "Vodafone"),
    (r"\bO2\s+Telef[óo]nica\b", "O2"),
    # Logistics
    (r"\bDeutsche\s+Post\s+AG\b|\bDHL\s+Paket\b", "DHL"),
    (r"\bHermes\s+Germany\b", "Hermes"),
]

_VENDOR_FINGERPRINT_COMPILED = [
    (re.compile(pat, re.IGNORECASE), name) for pat, name in _VENDOR_FINGERPRINTS
]


def detect_vendor_from_fingerprint(raw_text: str) -> str:
    """Detect vendor from machine-readable signals (barcode prefix /
    cash-register serial / company-name pattern) instead of fragile logo
    OCR. Returns canonical vendor name or empty string if no match.

    Scans the entire OCR text including any '[QR] ...' suffix added by
    main.py after QR decode — so the 22-digit Lidl barcode body is also
    matched.

    Why a separate function: extract_vendor() works line-by-line on the
    HEAD of the receipt where the logo lives. Fingerprints are scattered
    across the whole receipt (cash register block, footer, tax block).
    """
    if not raw_text:
        return ""
    for rx, name in _VENDOR_FINGERPRINT_COMPILED:
        if rx.search(raw_text):
            return name
    return ""


def extract_vendor(raw_text: str) -> str:
    """Extract vendor/store name from the first meaningful lines of OCR text."""
    lines = raw_text.strip().split("\n")
    candidates = []
    # Footer/greeting/payment lines are NOT vendor names — reject them so they
    # don't get picked as a (wrong) vendor. Precision fix: avoids "Danke",
    # "Kundenbeleg", "Rückgeld", "EC-Karte" being returned as the vendor.
    _footer_noise = re.compile(
        r"^(danke|vielen\s+dank|auf\s+wiedersehen|tsch[üu]ss|sch[öo]nen\s+(?:tag|abend)|"
        r"bis\s+bald|ihr\s+team|wir\s+danken|besuchen\s+sie|[öo]ffnungszeit|r[üu]ckgeld|"
        r"kundenbeleg|h[äa]ndlerbeleg|zwischensumme|kartenzahlung|ec[-\s]?karte)\b",
        re.IGNORECASE,
    )

    # Scan the first 20 lines (was 12): German receipts often push the store
    # name to line 4-15 behind logo/header noise. Priority ordering below
    # (suffix > known-vendor > non-address) still protects against footer lines.
    for line in lines[:20]:
        cleaned = line.strip()
        if not cleaned or len(cleaned) < 2:
            continue
        # Skip lines that are purely numbers/symbols
        if re.match(r"^[\d\s\.\-\/,€%:;#*+]+$", cleaned):
            continue
        # Skip common non-vendor header patterns
        if _SKIP_PATTERNS.match(cleaned):
            continue
        # Skip item/product lines (text followed by price)
        if _ITEM_LINE_RE.match(cleaned):
            continue
        # Skip total/payment lines
        if _TOTAL_LINE_RE.match(cleaned):
            continue
        # Skip footer/greeting/payment-method lines (not a vendor name)
        if _footer_noise.match(cleaned):
            continue
        # Skip very long lines (likely description/address)
        if len(cleaned) > 60:
            continue
        candidates.append(cleaned)

    if not candidates:
        return "Unbekannt"

    # Priority 1: line containing a business entity suffix (GmbH, Ltd, etc.)
    for c in candidates[:5]:
        if _VENDOR_SUFFIX_RE.search(c):
            return _clean_vendor_name(c)

    # Priority 2: line matching a known vendor name (word-boundary match
    # so "spar" doesn't hit "sparkasse" or "sparkarte", "hit" doesn't hit
    # arbitrary words, etc). Skip ambiguous/generic keys — they will
    # false-positive on VAT tables and generic category words.
    _PRIORITY2_SKIP = {
        "netto", "total", "penny",            # VAT / summary terms
        "tankstelle", "taxi", "apotheke",     # generic categories
        "pharmacy", "pharmacie",
        "hit", "basic", "combi", "star",      # common words
        "real", "coop", "alex", "jet",
    }
    for c in candidates[:5]:
        cl = c.lower()
        # Skip lines that are obviously VAT/price info
        if re.search(r"\b(netto|brutto|mwst|ust|inkl\.?|steuer)\b[:\s]", cl):
            continue
        for known_vendor in VENDOR_CATEGORY_MAP:
            if known_vendor in _PRIORITY2_SKIP:
                continue
            if len(known_vendor) < 3:
                continue
            if re.search(r"\b" + re.escape(known_vendor) + r"\b", cl):
                return _clean_vendor_name(c)

    # Priority 3: first candidate that is NOT an address/city/phone
    # --- ADDED START: skip address-like candidates ---
    _addr_re = re.compile(
        r"(?:\d{4,5}\s+\w)"  # PLZ + city
        r"|(?:\w+(?:str|straße|strasse|weg|platz|allee|gasse|ring|damm|ufer|chaussee)\b)"  # street names
        r"|(?:str\.\s*\d)"  # "Str. 5"
        r"|(?:rue\s|avenue\s|boulevard\s|chemin\s)"  # French streets
        r"|(?:^\d+[a-z]?\s*,)"  # "12a, ..."
        r"|(?:\w+\s+\d+\s*[-/]\s*\d+)"  # "Musterweg 5-7"
        r"|(?:^\d[\d\s/\-]{6,}$)"  # phone numbers
        r"|(?:^tel|^fax|^fon|^phone)"  # phone labels
        r"|(?:^0\d{2,4}\s)"  # German area codes "0681 ..."
        r"|(?:^\+\d)"  # international phone "+49..."
        , re.IGNORECASE
    )
    _city_re = re.compile(
        r"^(?:berlin|hamburg|münchen|munich|köln|cologne|frankfurt|stuttgart|düsseldorf|dortmund|essen|bremen|dresden|leipzig|hannover|nürnberg|duisburg|bochum|wuppertal|bielefeld|bonn|mannheim|karlsruhe|wiesbaden|augsburg|aachen|braunschweig|chemnitz|kiel|halle|magdeburg|freiburg|lübeck|erfurt|rostock|mainz|kassel|saarbrücken|oberhausen|mülheim|potsdam|leverkusen|oldenburg|osnabrück|heidelberg|darmstadt|paderborn|regensburg|ingolstadt|würzburg|wolfsburg|offenbach|ulm|heilbronn|göttingen|reutlingen|koblenz|remscheid|trier|salzgitter|jena|gera|moers|hildesheim|cottbus|siegen|gütersloh|witten|iserlohn|schwerin|konstanz|worms|marburg|lüneburg|bamberg|bayreuth|aschaffenburg|plauen|fulda|landshut|velbert|giessen|detmold|wilhelmshaven|norderstedt|neumünster|schwäbisch|euskirchen|lüdenscheid|dorsten|gladbeck|herten|dinslaken|grevenbroich|bergheim|wesel|dormagen|troisdorf|meerbusch|friedrichshafen|langenfeld|bornheim|haltern|ahlen|bremerhaven|goslar|emden|delmenhorst|celle|neubrandenburg|greifswald|stralsund|paris|lyon|marseille|toulouse|nice|nantes|strasbourg|montpellier|bordeaux|lille|wien|graz|linz|salzburg|innsbruck|zürich|bern|basel|genf|lausanne|istanbul|ankara|izmir|antalya|london|manchester|birmingham|amsterdam|rotterdam|den\s+haag|bruxelles|brüssel|roma|milano|madrid|barcelona)"
        r"(?:\s|$|,)", re.IGNORECASE
    )
    for c in candidates:
        if not _addr_re.search(c) and not _city_re.match(c.strip()):
            return _clean_vendor_name(c)
    # --- ADDED END ---
    # Fallback: first candidate even if address-like
    return _clean_vendor_name(candidates[0])


_VENDOR_OCR_CORRECTIONS = {
    # Supermarkets — common OCR misreads
    "lödl": "LIDL", "lōdl": "LIDL", "l1dl": "LIDL", "lidl": "LIDL",
    "lldi": "LIDL", "lid1": "LIDL", "iidl": "LIDL", "lidl.de": "LIDL",
    "lidii": "LIDL", "lidll": "LIDL", "liidl": "LIDL", "lidi": "LIDL",
    "lad1": "LIDL", "ladi": "LIDL", "lidl": "LIDL", "ildl": "LIDL",
    "1idl": "LIDL", "iidii": "LIDL", "lidii": "LIDL",
    # User-reported OCR misreads (2026-04-12)
    "lyidl": "LIDL", "lydl": "LIDL", "lydi": "LIDL",
    "lidle": "LIDL", "lidel": "LIDL", "lenk": "LIDL",
    # 2026-05-03: Lidl logosunun kirmizi i-noktasi OCR tarafindan
    # bazen 'kar' / 'kare' / 'k' olarak yorumlanir.
    "lkaredl": "LIDL", "likaredl": "LIDL", "lkardl": "LIDL",
    "lkare": "LIDL", "lkaredi": "LIDL", "lkardi": "LIDL",
    "likdl": "LIDL", "likdi": "LIDL", "likeredi": "LIDL",
    # Not: 'ldl' uc-harfli kisa pattern oldugu icin eklenmedi —
    # 'goldlist' / 'aldhof' gibi kelimelerde false positive verir.
    # Eger OCR 'LDL' tek basina dondururse asagidaki tam-eslesme yakalar.
    "l1dl1": "LIDL", "l1dl.": "LIDL",
    "acti0n": "ACTION", "actlon": "ACTION", "actiom": "ACTION",
    "act1on": "ACTION", "aktion": "ACTION",
    "aldl": "ALDI", "a1di": "ALDI", "aldi": "ALDI", "aidi": "ALDI",
    "aldi süd": "ALDI SÜD", "aldi sud": "ALDI SÜD", "aldi nord": "ALDI NORD",
    "rewe": "REWE", "rew3": "REWE", "r3we": "REWE", "rewe.de": "REWE",
    "edeka": "EDEKA", "edek4": "EDEKA", "3deka": "EDEKA",
    "penny": "PENNY", "p3nny": "PENNY", "pennymarkt": "PENNY",
    "netto": "NETTO", "n3tto": "NETTO", "nettomarkt": "NETTO",
    "kaufland": "KAUFLAND", "kauf1and": "KAUFLAND",
    "norma": "NORMA", "n0rma": "NORMA",
    "auchan": "AUCHAN", "auchan.fr": "AUCHAN",
    "carrefour": "CARREFOUR", "carref0ur": "CARREFOUR",
    "leclerc": "E.LECLERC", "e.leclerc": "E.LECLERC",
    "monoprix": "MONOPRIX", "m0noprix": "MONOPRIX",
    "migros": "MIGROS", "coop": "COOP", "spar": "SPAR",
    # Restaurants
    "amazon": "AMAZON", "amaz0n": "AMAZON", "amazon.de": "AMAZON",
    "starbucks": "STARBUCKS", "starbuck5": "STARBUCKS", "starbuks": "STARBUCKS",
    "mcdonald": "MCDONALDS", "mcdonalds": "MCDONALDS", "mcdona1ds": "MCDONALDS",
    "mc donald": "MCDONALDS", "mcdo": "MCDONALDS",
    "burger king": "BURGER KING", "burgerking": "BURGER KING",
    "subway": "SUBWAY", "kfc": "KFC",
    # Fuel
    "shell": "SHELL", "sh3ll": "SHELL", "shell.de": "SHELL",
    "aral": "ARAL", "ara1": "ARAL", "aral.de": "ARAL",
    "total": "TOTALENERGIES", "totalenergies": "TOTALENERGIES",
    "esso": "ESSO", "ess0": "ESSO", "bp": "BP",
    # Drugstores
    "dm": "DM", "dm-drogerie": "DM", "dm drogerie": "DM",
    "rossmann": "ROSSMANN", "r0ssmann": "ROSSMANN",
    "mueller": "MÜLLER", "müller": "MÜLLER", "muller": "MÜLLER",
    # Electronics
    "saturn": "SATURN", "mediamarkt": "MEDIA MARKT", "media markt": "MEDIA MARKT",
    "apple": "APPLE", "apple.com": "APPLE",
    # Clothing
    "deichmann": "DEICHMANN", "de'chmann": "DEICHMANN", "delchmann": "DEICHMANN",
    "h&m": "H&M", "hm": "H&M", "zara": "ZARA", "c&a": "C&A",
    "primark": "PRIMARK", "kik": "KIK", "takko": "TAKKO",
    # Home / DIY
    "ikea": "IKEA", "1kea": "IKEA", "bauhaus": "BAUHAUS", "obi": "OBI",
    "hornbach": "HORNBACH", "h0rnbach": "HORNBACH",
    # Transport
    "deutsche bahn": "DEUTSCHE BAHN", "db ": "DEUTSCHE BAHN",
    "flixbus": "FLIXBUS", "uber": "UBER", "bolt": "BOLT",
    # Telecom
    "telekom": "TELEKOM", "vodafone": "VODAFONE", "o2": "O2",
    # Post
    "dhl": "DHL", "deutsche post": "DEUTSCHE POST", "hermes": "HERMES",
    # Software
    "microsoft": "MICROSOFT", "google": "GOOGLE", "adobe": "ADOBE",
    "spotify": "SPOTIFY", "netflix": "NETFLIX", "paypal": "PAYPAL",
    # === FRANCE ===
    "auchan": "AUCHAN", "auchan.fr": "AUCHAN", "auchanfr": "AUCHAN",
    "carrefour": "CARREFOUR", "carref0ur": "CARREFOUR", "carrefour market": "CARREFOUR",
    "carrefour city": "CARREFOUR", "carrefour express": "CARREFOUR",
    "leclerc": "E.LECLERC", "e.leclerc": "E.LECLERC", "e leclerc": "E.LECLERC",
    "monoprix": "MONOPRIX", "m0noprix": "MONOPRIX", "monop'": "MONOPRIX",
    "intermarche": "INTERMARCHÉ", "intermarché": "INTERMARCHÉ",
    "casino": "CASINO", "géant casino": "GÉANT CASINO", "geant casino": "GÉANT CASINO",
    "franprix": "FRANPRIX", "picard": "PICARD",
    "boulangerie": "BOULANGERIE", "patisserie": "PÂTISSERIE",
    "bricomarche": "BRICOMARCHÉ", "bricorama": "BRICORAMA",
    "leroy merlin": "LEROY MERLIN", "leroymerlin": "LEROY MERLIN",
    "castorama": "CASTORAMA", "darty": "DARTY", "fnac": "FNAC",
    "boulanger": "BOULANGER", "sncf": "SNCF", "ratp": "RATP",
    "la poste": "LA POSTE", "chronopost": "CHRONOPOST",
    "orange": "ORANGE", "sfr": "SFR", "bouygues": "BOUYGUES TELECOM",
    "free": "FREE", "free mobile": "FREE",
    "total": "TOTALENERGIES", "totalenergies": "TOTALENERGIES",
    "decathlon": "DECATHLON", "d3cathlon": "DECATHLON",
    "kiabi": "KIABI", "action": "ACTION",
    # === ITALY ===
    "esselunga": "ESSELUNGA", "conad": "CONAD", "coop italia": "COOP",
    "eurospin": "EUROSPIN", "lidl italia": "LIDL", "md discount": "MD",
    "pam": "PAM", "despar": "DESPAR", "bennet": "BENNET",
    "autogrill": "AUTOGRILL", "eni": "ENI", "agip": "AGIP",
    "trenitalia": "TRENITALIA", "italo": "ITALO",
    "tim": "TIM", "wind tre": "WINDTRE", "iliad": "ILIAD",
    "poste italiane": "POSTE ITALIANE", "mediaworld": "MEDIAWORLD",
    "unieuro": "UNIEURO", "feltrinelli": "FELTRINELLI",
    "ovs": "OVS", "calzedonia": "CALZEDONIA", "intimissimi": "INTIMISSIMI",
    # === SPAIN ===
    "mercadona": "MERCADONA", "mercad0na": "MERCADONA",
    "dia": "DIA", "el corte ingles": "EL CORTE INGLÉS",
    "el corte inglés": "EL CORTE INGLÉS", "eroski": "EROSKI",
    "hipercor": "HIPERCOR", "alcampo": "ALCAMPO",
    "consum": "CONSUM", "bonpreu": "BONPREU", "caprabo": "CAPRABO",
    "repsol": "REPSOL", "cepsa": "CEPSA",
    "renfe": "RENFE", "iberia": "IBERIA", "vueling": "VUELING",
    "movistar": "MOVISTAR", "vodafone": "VODAFONE",
    "correos": "CORREOS", "mediamarkt": "MEDIA MARKT",
    "zara": "ZARA", "mango": "MANGO", "desigual": "DESIGUAL",
    "massimo dutti": "MASSIMO DUTTI", "bershka": "BERSHKA",
    "pull&bear": "PULL&BEAR", "stradivarius": "STRADIVARIUS",
    # === UK / USA ===
    "tesco": "TESCO", "tesc0": "TESCO", "sainsbury": "SAINSBURY'S",
    "sainsbury's": "SAINSBURY'S", "asda": "ASDA", "morrisons": "MORRISONS",
    "waitrose": "WAITROSE", "marks & spencer": "MARKS & SPENCER", "m&s": "M&S",
    "walmart": "WALMART", "wa1mart": "WALMART", "wal-mart": "WALMART",
    "target": "TARGET", "targ3t": "TARGET",
    "costco": "COSTCO", "c0stco": "COSTCO",
    "whole foods": "WHOLE FOODS", "trader joe": "TRADER JOE'S",
    "trader joe's": "TRADER JOE'S", "kroger": "KROGER",
    "walgreens": "WALGREENS", "cvs": "CVS", "rite aid": "RITE AID",
    "home depot": "HOME DEPOT", "lowe's": "LOWE'S", "lowes": "LOWE'S",
    "best buy": "BEST BUY", "bestbuy": "BEST BUY",
    "apple store": "APPLE", "amazon.com": "AMAZON",
    "uber eats": "UBER EATS", "doordash": "DOORDASH", "grubhub": "GRUBHUB",
    "lyft": "LYFT", "uber": "UBER",
    "at&t": "AT&T", "verizon": "VERIZON", "t-mobile": "T-MOBILE",
    "usps": "USPS", "fedex": "FEDEX", "ups": "UPS",
    "nike": "NIKE", "adidas": "ADIDAS", "gap": "GAP",
    "old navy": "OLD NAVY", "forever 21": "FOREVER 21",
    # === TURKEY ===
    "bim": "BİM", "a101": "A101", "şok": "ŞOK", "sok": "ŞOK",
    "migros": "MİGROS", "carrefoursa": "CARREFOURSA",
    "macro center": "MACRO CENTER", "metro": "METRO",
    "gratis": "GRATIS", "watsons": "WATSONS",
    "teknosa": "TEKNOSA", "mediamarkt": "MEDIA MARKT",
    "koçtaş": "KOÇTAŞ", "koctas": "KOÇTAŞ", "bauhaus": "BAUHAUS",
    "lc waikiki": "LC WAIKIKI", "defacto": "DEFACTO",
    "turkcell": "TURKCELL", "vodafone": "VODAFONE", "türk telekom": "TÜRK TELEKOM",
    "ptt": "PTT", "yurtiçi kargo": "YURTİÇİ KARGO", "aras kargo": "ARAS KARGO",
    "thy": "TÜRK HAVA YOLLARI", "türk hava": "TÜRK HAVA YOLLARI",
    "pegasus": "PEGASUS", "sunexpress": "SUNEXPRESS",
    "opet": "OPET", "petrol ofisi": "PETROL OFİSİ", "bp": "BP",
    "starbucks": "STARBUCKS", "burger king": "BURGER KING",
}

# Website → Vendor mapping (found in OCR text)
_WEBSITE_VENDOR_MAP = {
    "lidl.de": "LIDL", "lidl.fr": "LIDL", "lidl.com": "LIDL",
    "aldi-sued.de": "ALDI SÜD", "aldi-nord.de": "ALDI NORD", "aldi.de": "ALDI",
    "rewe.de": "REWE", "edeka.de": "EDEKA", "penny.de": "PENNY",
    "netto-online.de": "NETTO", "kaufland.de": "KAUFLAND",
    "auchan.fr": "AUCHAN", "carrefour.fr": "CARREFOUR", "carrefour.com": "CARREFOUR",
    "leclerc.fr": "E.LECLERC", "monoprix.fr": "MONOPRIX",
    "amazon.de": "AMAZON", "amazon.com": "AMAZON", "amazon.fr": "AMAZON",
    "ebay.de": "EBAY", "ebay.com": "EBAY",
    "starbucks.com": "STARBUCKS", "starbucks.de": "STARBUCKS",
    "mcdonalds.de": "MCDONALDS", "mcdonalds.com": "MCDONALDS",
    "shell.de": "SHELL", "shell.com": "SHELL",
    "aral.de": "ARAL", "bp.com": "BP", "totalenergies.de": "TOTALENERGIES",
    "dm.de": "DM", "rossmann.de": "ROSSMANN",
    "saturn.de": "SATURN", "mediamarkt.de": "MEDIA MARKT",
    "apple.com": "APPLE", "microsoft.com": "MICROSOFT",
    "ikea.de": "IKEA", "ikea.com": "IKEA",
    "deichmann.de": "DEICHMANN", "deichmann.com": "DEICHMANN",
    "hm.com": "H&M", "zara.com": "ZARA",
    "bauhaus.info": "BAUHAUS", "obi.de": "OBI", "hornbach.de": "HORNBACH",
    "bahn.de": "DEUTSCHE BAHN", "flixbus.de": "FLIXBUS",
    "telekom.de": "TELEKOM", "vodafone.de": "VODAFONE",
    "dhl.de": "DHL", "paypal.com": "PAYPAL",
    "spotify.com": "SPOTIFY", "netflix.com": "NETFLIX",
    "google.com": "GOOGLE", "adobe.com": "ADOBE",
    # France
    "auchan.fr": "AUCHAN", "carrefour.fr": "CARREFOUR", "leclerc.fr": "E.LECLERC",
    "monoprix.fr": "MONOPRIX", "intermarche.com": "INTERMARCHÉ",
    "fnac.com": "FNAC", "darty.com": "DARTY", "leroymerlin.fr": "LEROY MERLIN",
    "sncf.com": "SNCF", "decathlon.fr": "DECATHLON",
    # Italy
    "esselunga.it": "ESSELUNGA", "conad.it": "CONAD", "trenitalia.it": "TRENITALIA",
    "mediaworld.it": "MEDIAWORLD", "posteitaliane.it": "POSTE ITALIANE",
    # Spain
    "mercadona.es": "MERCADONA", "elcorteingles.es": "EL CORTE INGLÉS",
    "renfe.com": "RENFE", "zara.com": "ZARA", "mango.com": "MANGO",
    # UK
    "tesco.com": "TESCO", "sainsburys.co.uk": "SAINSBURY'S", "asda.com": "ASDA",
    # USA
    "walmart.com": "WALMART", "target.com": "TARGET", "costco.com": "COSTCO",
    "bestbuy.com": "BEST BUY", "homedepot.com": "HOME DEPOT",
    # Turkey
    "bim.com.tr": "BİM", "a101.com.tr": "A101", "migros.com.tr": "MİGROS",
    "teknosa.com": "TEKNOSA", "lcwaikiki.com": "LC WAIKIKI",
    "thy.com": "TÜRK HAVA YOLLARI", "pegasus.com": "PEGASUS",
}

# Tax ID prefixes → known vendors (German USt-IdNr.)
_TAX_ID_VENDOR_MAP = {
    "DE127282923": "LIDL", "DE811207047": "ALDI SÜD", "DE129491404": "ALDI NORD",
    "DE812706034": "REWE", "DE132600790": "EDEKA",
    "DE137389567": "AMAZON", "DE814865842": "SATURN",
    "DE811154539": "SHELL", "DE811515593": "ARAL",
    "DE113549055": "DM", "DE116304402": "ROSSMANN",
    "DE129384285": "IKEA", "DE811228562": "TELEKOM",
    # France (SIRET/SIREN patterns — first digits)
    "FR40303656985": "CARREFOUR", "FR39552096281": "AUCHAN",
    "FR72428240760": "E.LECLERC", "FR03552083297": "MONOPRIX",
    # Spain (CIF)
    "ESA46103834": "MERCADONA",
    # Italy (P.IVA)
    "IT02153300963": "ESSELUNGA",
}


# Footer / receipt-boilerplate fragments that are NEVER a vendor name.
# Module-level so both extract_vendor and the garbage detector reuse it.
_VENDOR_FOOTER_RE = re.compile(
    r"^(danke|vielen\s+dank|auf\s+wiedersehen|tsch[üu]ss|sch[öo]nen\s+(?:tag|abend)|"
    r"bis\s+bald|ihr\s+team|wir\s+danken|besuchen\s+sie|[öo]ffnungszeit|r[üu]ckgeld|"
    r"kundenbeleg|h[äa]ndlerbeleg|zwischensumme|kartenzahlung|ec[-\s]?karte|"
    r"gegeben|bar\s+gezahlt|zahlbetrag|trinkgeld|geg(?:eben)?\s+bar|"
    r"betrag\s+erhalten|wechselgeld|terminal[- ]?id|beleg[- ]?nr|bon[- ]?nr)\b",
    re.IGNORECASE,
)


def _is_garbage_vendor(name: str) -> bool:
    """Return True when `name` looks like OCR noise rather than a real vendor:
    logo gibberish ("er, en DR ar | ae"), random character soup, or a footer
    fragment. Callers MUST whitelist known brands BEFORE calling this — it only
    judges unrecognized strings.

    Conservative by design: when unsure, return False (keep the name). The goal
    is to swap obvious garbage for 'Unbekannt' + needs_review, not to discard
    legitimate small-shop names the user can still correct. vendor-only — it
    never influences total/date/source-priority.
    """
    if not name:
        return True
    s = name.strip()
    if not s:
        return True
    low = s.lower()

    # 1) Footer / receipt boilerplate is never a vendor.
    if _VENDOR_FOOTER_RE.match(low):
        return True

    letters = re.sub(r"[^a-zA-ZäöüÄÖÜß]", "", s)
    # 2) Too few real letters, or symbol/number soup.
    if len(letters) < 3:
        return True
    if len(letters) / len(s) < 0.5:
        return True

    # 3) No vowel at all across a multi-letter string -> consonant gibberish
    #    ("brkzt", "xdfg"). German vowels incl. umlauts + y.
    if len(letters) >= 4 and not re.search(r"[aeiouyäöü]", low):
        return True

    # 4) Logo gibberish: many tiny alphabetic tokens ("er en DR ar ae"),
    #    or a couple of all-tiny tokens with junk ("5 et Be"). Real two-word
    #    short names ("De Nico", "Le Coq") survive — not ALL their tokens <=2.
    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß]+", s)
    if len(tokens) >= 3:
        tiny = sum(1 for t in tokens if len(t) <= 2)
        if tiny / len(tokens) >= 0.6:
            return True
        if sum(len(t) for t in tokens) / len(tokens) < 2.5:
            return True
    if len(tokens) >= 2 and all(len(t) <= 2 for t in tokens) and len(letters) <= 6:
        return True

    # 5) Implausibly long consonant run typical of OCR garble ("frtztghk").
    if re.search(r"[bcdfghjklmnpqrstvwxzß]{7,}", low):
        return True

    # 6) Math/compare/bracket glyphs never occur in real vendor names, but OCR
    #    noise carries them ("mie = ee. LO a <<< quam can 7"). Legit name
    #    punctuation (& . - ' , /) and stray '|' are NOT in this set, so
    #    'H&M', 'C&A', "L'Oréal", 'bereket Metzgerei |' survive.
    if re.search(r"[=<>~^\\{}]", s):
        return True

    return False


# Generic scanner / camera / document default filename words. A filename made of
# only these + digits/date separators is NOT a vendor.
_GENERIC_FNAME_WORDS = (
    "scan", "img", "image", "photo", "bild", "foto", "doc", "document",
    "dokument", "page", "seite", "untitled", "kopie", "copy", "neu", "neue",
    "test", "rechnung", "invoice", "fatura", "fis", "file", "whatsapp",
    "screenshot",
)


def filename_vendor_guess(filename: str) -> str | None:
    """Derive a vendor name from an upload filename, or None when the filename
    is a generic scanner/camera/doc default ('Scan2026-06-05_170051.pdf',
    'IMG_1234.jpg', 'WhatsApp Image 2026-...', 'document.pdf').

    Returns None for junk so the caller keeps 'Unbekannt' + needs_review instead
    of storing a fake vendor like 'Scan2026 06 05'. Real shop names embedded in a
    filename survive. KNOWN-vendor matching is the caller's job, BEFORE this.

    Fix (2026-06-14): the old check only flagged SHORT generic names
    (len <= prefix+5), so date-suffixed scan names slipped through. Now a name is
    rejected whenever nothing but generic words + digits/separators remains —
    regardless of length.
    """
    if not filename:
        return None
    base = re.sub(r"\.[a-z0-9]+$", "", filename, flags=re.IGNORECASE)
    base = re.sub(r"[-_\s]+\d{1,5}[.,]?\d{0,2}\s*$", "", base)
    base = re.sub(r"[-_]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()
    if not base or len(base) < 3:
        return None
    # Strip digits first (so 'scan2026' -> 'scan'), then remove generic words.
    # If <3 real letters remain, the filename was scanner/date junk, not a vendor.
    residue = re.sub(r"\d+", " ", base.lower())
    for _w in _GENERIC_FNAME_WORDS:
        residue = re.sub(rf"\b{_w}\b", " ", residue)
    if len(re.sub(r"[^a-zäöüß]", "", residue)) < 3:
        return None
    return base if base == base.upper() else base.title()


def _clean_vendor_name(name: str) -> str:
    """Clean up vendor name: remove trailing punctuation, asterisks, OCR corrections.
    Also canonicalize: if a long legal name contains a known brand
    ('Parfümerie Douglas Deutschland GmbH' → 'Douglas'), collapse to
    the canonical brand so the invoice list stays tidy and matches
    across slightly different OCR readings of the same store.
    """
    name = re.sub(r"[*#]+", "", name).strip()
    # Strip leading and trailing noise: punctuation, pipes, colons, dashes
    name = re.sub(r"^[^A-Za-zÄÖÜäöüß0-9]+", "", name)
    name = re.sub(r"[^A-Za-zÄÖÜäöüß0-9.]+$", "", name).strip()
    name = re.sub(r"[\s\-:,]+$", "", name).strip()

    # Canonicalize: if a known brand name is embedded in a longer legal
    # name, return the canonical brand form. Longest match wins so
    # 'burger king restaurant' → 'Burger King' (not just 'king').
    _check_lower = " " + re.sub(r"\s+", " ", name.lower()) + " "
    # Skip generic category words and ambiguous short keys that would
    # beat real brands on length ordering (tankstelle=10 beats aral=4).
    _GENERIC_SKIP = {
        "netto", "total", "penny",            # VAT / summary terms
        "tankstelle", "taxi", "apotheke",     # generic categories
        "pharmacy", "pharmacie",
        "hit", "basic", "combi", "star",      # common words
        "real", "coop", "alex", "jet",
    }
    for _brand in sorted(VENDOR_CATEGORY_MAP.keys(), key=len, reverse=True):
        if _brand in _GENERIC_SKIP or len(_brand) < 4:
            continue
        # Require word boundaries so 'spar' doesn't hit 'sparkasse'
        if re.search(r"\b" + re.escape(_brand) + r"\b", _check_lower):
            return _brand.upper() if len(_brand) <= 5 else _brand.title()

    # OCR correction FIRST: rescue known misreads (lödl, acti0n, ...) before
    # the garbage detector could mistake them for noise.
    name_lower = re.sub(r"[^a-zäöüß0-9]", "", name.lower())
    for wrong, correct in _VENDOR_OCR_CORRECTIONS.items():
        if wrong in name_lower:
            return correct

    # Garbage detection — logo gibberish / random soup / footer fragments.
    # Whitelist known short vendors (H&M, DM, BP, ...) first so they survive.
    name_check = name.lower().strip()
    is_known_vendor = any(v in name_check for v in VENDOR_CATEGORY_MAP if len(v) >= 2)
    if not is_known_vendor and _is_garbage_vendor(name):
        return "Unbekannt"

    # Title-case if all upper
    if name == name.upper() and len(name) > 3:
        name = name.title()
    return name if name else "Unbekannt"


def _first_line_vendor_guess(raw_text: str) -> str:
    """Last-resort vendor pick: scan the first 8 lines and return the first
    line that looks like a real business name. Used when extract_vendor and
    _deep_vendor_search both return 'Unbekannt' — so small/unknown stores
    (Bereket, De Nico, Topaz, etc) at least surface their header line.
    The user can correct it in the invoice editor.
    """
    if not raw_text:
        return ""
    skip_noise = re.compile(
        r"^("
        r"datum|date|bon|beleg|filiale|kasse|quittung|rechnung|tel\.?\s|fax|www\.|http|"
        r"ust|mwst|steuer|str\.|straße|strasse|\d{4,5}\s|\d{2}\.\d{2}\.\d{2,4}|"
        r"summe|gesamt|total|betrag|brutto|netto|eur|euro|"
        r"kunde|mitarbeiter|bediener|kassierer|kassiererin|verkauf|vielen\s+dank|"
        r"ticket|beleg\s*nr|rechnung\s*nr|trans(?:aktion)?|tse|zahlbetrag|"
        # Digital PDF (Stripe/Resend/Anthropic) ortak artiklari — bunlar gercek vendor degil
        r"page\s+\d|seite\s+\d|invoice\s*$|invoice\s+(number|date|due|to)|receipt\s*$|"
        r"bill\s+to|ship\s+to|sold\s+to|payable\s+to|pay\s+online|pay\s+to|amount\s+due|"
        r"date\s+of\s+issue|date\s+due|description|qty|unit\s+price|tax|subtotal|"
        r"please\s|thank\s+you|dear\s+|hallo\s+|sehr\s+geehrte"
        r")",
        re.IGNORECASE,
    )
    # Address / street patterns (shared with extract_vendor's Priority 3)
    addr_re = re.compile(
        r"(?:\d{4,5}\s+[A-ZÄÖÜ])"                                    # "12345 Berlin"
        r"|(?:\w+(?:str|straße|strasse|weg|platz|allee|gasse|ring|damm|ufer|chaussee)\b)"
        r"|(?:\b(?:str|straße|strasse)\.?\s*\d)"                     # "Str. 42"
        r"|(?:rue\s|avenue\s|boulevard\s|chemin\s)"
        r"|(?:^\d+[a-z]?\s*,)"
        r"|(?:^[A-ZÄÖÜ][a-zäöüß]+\s+\d{1,4}[a-z]?\s*$)"              # "Hauptstraße 42"
        , re.IGNORECASE
    )
    city_only = re.compile(r"^[A-ZÄÖÜ][a-zäöüß\-]+(?:\s[A-ZÄÖÜ][a-zäöüß\-]+)?$")  # "Berlin" / "Frankfurt Main"
    phone_re = re.compile(r"^(?:tel|fax|fon|phone|\+?\d[\d\s/\-]{6,})", re.IGNORECASE)

    for raw_line in raw_text.splitlines()[:8]:
        line = raw_line.strip()
        if not line or len(line) < 4:
            continue
        # Must contain at least one word of 4+ letters
        if not re.search(r"[A-Za-zÄÖÜäöüß]{4,}", line):
            continue
        # At least 50% letters
        letters = sum(1 for c in line if c.isalpha())
        if letters / len(line) < 0.5:
            continue
        if skip_noise.match(line):
            continue
        # Skip lines that are mostly a phone/IBAN/number
        if re.match(r"^[\d\s\.\-\+\/]+$", line):
            continue
        # Skip street + number, postal codes, city-only lines, phones
        if addr_re.search(line):
            continue
        if phone_re.match(line):
            continue
        # Reject bare-city lines ONLY if they are short — avoid nuking real
        # single-word vendor names like "ACTION", "MUELLER"; a two-word
        # lowercase-started city like "Berlin" typically won't pass the
        # letter-ratio check but keep a guard anyway.
        if city_only.match(line) and len(line) <= 20 and line[0].isupper() and line[1:].islower():
            continue
        return _clean_vendor_name(line)
    return ""


def _deep_vendor_search(raw_text: str) -> str:
    """Deep search for vendor when extract_vendor returns Unbekannt.
    Searches entire OCR text for: websites, tax IDs, known vendor names, fuzzy matches.
    """
    text_lower = raw_text.lower()
    text_clean = re.sub(r"[^a-zäöüß0-9\s./@\-]", "", text_lower)

    # 1. Website detection (most reliable)
    for site, vendor in _WEBSITE_VENDOR_MAP.items():
        if site in text_lower:
            return vendor

    # 2. Tax ID detection (DE, FR, ES, IT, etc.)
    tax_patterns = [
        r"(DE\d{9})",                    # Germany USt-IdNr
        r"(FR\d{11})",                   # France TVA
        r"(ES[A-Z]\d{8})",              # Spain CIF
        r"(IT\d{11})",                   # Italy P.IVA
        r"(GB\d{9})",                    # UK VAT
        r"(AT\d{9})",                    # Austria
        r"(CH\d{9})",                    # Switzerland
    ]
    for pat in tax_patterns:
        tax_match = re.search(pat, raw_text)
        if tax_match:
            tax_id = tax_match.group(1)
            if tax_id in _TAX_ID_VENDOR_MAP:
                return _TAX_ID_VENDOR_MAP[tax_id]

    # 3. Known vendor name in full text (not just first lines).
    # Use WORD BOUNDARIES so short brand keys don't substring-match random
    # words. Also skip ambiguous/generic keys that false-positive on VAT
    # tables and generic category words (tankstelle, apotheke, etc).
    _DEEP_SEARCH_SKIP = {
        "netto", "total", "penny",            # VAT / summary terms
        "tankstelle", "taxi", "apotheke",     # generic categories
        "pharmacy", "pharmacie",
        "hit", "basic", "combi", "star",      # common words
        "real", "coop", "alex", "jet",
    }
    for vendor_key in sorted(VENDOR_CATEGORY_MAP.keys(), key=len, reverse=True):
        if vendor_key in _DEEP_SEARCH_SKIP:
            continue
        if len(vendor_key) < 4:
            continue
        if re.search(r"\b" + re.escape(vendor_key) + r"\b", text_clean):
            return vendor_key.upper() if len(vendor_key) <= 5 else vendor_key.title()

    # 4. OCR corrections on full text — word boundaries + ambiguous-key skip
    for wrong, correct in _VENDOR_OCR_CORRECTIONS.items():
        if wrong.lower() in _DEEP_SEARCH_SKIP or correct.lower() in _DEEP_SEARCH_SKIP:
            continue
        if len(wrong) < 4:
            continue
        if re.search(r"\b" + re.escape(wrong) + r"\b", text_clean):
            return correct

    # 5. DISABLED: fuzzy character-similarity matching was too loose.
    # It matched "spare" (German 'to save') against "spar" brand with 80%
    # similarity, poisoning every Lidl/Aldi receipt that mentioned savings.
    # Phase 3 with word boundaries is already strong enough for reliable
    # brand detection; fuzzy recovery is not worth the false positive rate.

    # 6. Look for company suffix patterns anywhere in text (international)
    # IMPORTANT: use word boundaries around the suffix, otherwise 'Incl.'
    # (inclusive) matches as 'Inc.' + 'l.' and grabs the preceding text
    # ('EUR' on Lidl receipts where 'Incl.: 7% MwSt.' appears).
    company_match = re.search(
        r"([A-ZÄÖÜa-zäöüß][\w\s&\-'.]{2,40})\s+\b(?:GmbH|Co\.?\s?KG|AG|e\.K\.|OHG|UG|SE|Ltd\.?|Inc\.?|SAS|SARL|S\.A\.?|S\.L\.?|S\.R\.L\.?|Oy|AB|NV|BV|PLC|LLC|Corp\.?|Pty|A\.Ş\.|Ş[tT]i\.?|LTD\.?\s*ŞTİ)\b",
        raw_text
    )
    if company_match:
        name = company_match.group(1).strip()
        name = re.sub(r"[\s\-:,]+$", "", name).strip()
        if len(name) >= 3 and name.lower() not in ("die", "der", "das", "für", "und", "mit"):
            return name

    return "Unbekannt"


# ════════════════════════════════════════════════════════════════
# CATEGORY DETECTION
# ════════════════════════════════════════════════════════════════

def detect_category(vendor: str, raw_text: str) -> str:
    """Auto-detect invoice category from vendor name and content."""
    vendor_lower = vendor.lower()
    text_lower = raw_text.lower()

    # 1. Direct vendor match
    for key, cat in VENDOR_CATEGORY_MAP.items():
        if key in vendor_lower:
            return cat

    # 2. Scan full text for known vendor mentions
    for key, cat in VENDOR_CATEGORY_MAP.items():
        if len(key) >= 4 and key in text_lower:
            return cat

    # 3. Content-based heuristics
    fuel_keywords = ["liter", "diesel", "benzin", "super e", "tankstelle", "zapfsäule", "unleaded", "gasoil"]
    if any(k in text_lower for k in fuel_keywords):
        return "fuel"

    food_keywords = ["lebensmittel", "grocery", "bio ", "obst", "gemüse", "milch", "brot", "fleisch"]
    if any(k in text_lower for k in food_keywords):
        return "food"

    restaurant_keywords = ["restaurant", "café", "cafe", "bistro", "gaststätte", "speisen", "getränke", "trinkgeld", "tip", "bedienung"]
    if any(k in text_lower for k in restaurant_keywords):
        return "restaurant"

    office_keywords = ["büromaterial", "office", "druckerpatrone", "toner", "papier a4", "kopierpapier"]
    if any(k in text_lower for k in office_keywords):
        return "office"

    transport_keywords = ["fahrkarte", "ticket", "boarding", "flug", "flight", "bahn", "zug ", "train"]
    if any(k in text_lower for k in transport_keywords):
        return "transport"

    telecom_keywords = ["mobilfunk", "internet", "flatrate", "datenvolumen", "rufnummer"]
    if any(k in text_lower for k in telecom_keywords):
        return "telecom"

    return "other"


# ════════════════════════════════════════════════════════════════
# COUNTRY DETECTION
# ════════════════════════════════════════════════════════════════

def detect_country(raw_text: str) -> str:
    """Detect the country of origin from receipt text."""
    text_lower = raw_text.lower()

    scores: dict[str, int] = {}
    for country, indicators in COUNTRY_INDICATORS.items():
        score = sum(1 for ind in indicators if ind in text_lower)
        if score > 0:
            scores[country] = score

    if scores:
        return max(scores, key=scores.get)

    # Default to Germany
    return "DE"


def detect_currency(raw_text: str) -> str:
    """Detect currency from symbols and keywords in text."""
    t = raw_text
    # Check symbols first (most reliable)
    if "$" in t and "€" not in t:
        return "USD"
    if "₺" in t:
        return "TRY"
    if "£" in t and "€" not in t:
        return "GBP"
    # Check keywords
    tu = t.upper()
    if " USD" in tu or "US$" in tu:
        return "USD"
    if " TL " in tu or " TL\n" in tu or tu.endswith(" TL"):
        return "TRY"
    if " GBP" in tu:
        return "GBP"
    if " CHF" in tu:
        return "CHF"
    # --- ADDED START: Extra currencies ---
    if "₽" in t or " RUB" in tu:
        return "RUB"
    if " NOK" in tu or " KR" in tu:
        if any(w in t.lower() for w in ["norge", "norway", "oslo"]):
            return "NOK"
    if " SEK" in tu:
        return "SEK"
    if " DKK" in tu:
        return "DKK"
    if " PLN" in tu or " ZŁ" in tu or "zł" in t:
        return "PLN"
    if " CZK" in tu or " KČ" in tu or "kč" in t:
        return "CZK"
    if " HUF" in tu or " FT" in tu:
        return "HUF"
    if " RON" in tu or " LEI" in tu:
        return "RON"
    if " HRK" in tu or " KN" in tu:
        return "HRK"
    if " RSD" in tu or " DIN" in tu:
        return "RSD"
    if " UAH" in tu or "₴" in t or "грн" in t:
        return "UAH"
    if "¥" in t or " JPY" in tu:
        return "JPY"
    if "₩" in t or " KRW" in tu:
        return "KRW"
    if "₹" in t or " INR" in tu:
        return "INR"
    if " CNY" in tu or " RMB" in tu or "元" in t:
        return "CNY"
    if " AED" in tu or "د.إ" in t:
        return "AED"
    if " SAR" in tu or "﷼" in t:
        return "SAR"
    if " ZAR" in tu:
        return "ZAR"
    if " BRL" in tu or "R$" in t:
        return "BRL"
    if " MXN" in tu:
        return "MXN"
    if " ARS" in tu:
        return "ARS"
    if " CAD" in tu or "C$" in t:
        return "CAD"
    if " AUD" in tu or "A$" in t:
        return "AUD"
    if " NZD" in tu:
        return "NZD"
    if " ILS" in tu or "₪" in t:
        return "ILS"
    if " MAD" in tu:
        return "MAD"
    if " TND" in tu:
        return "TND"
    if " EGP" in tu:
        return "EGP"
    # --- ADDED END ---
    # Default
    if "€" in t or "EUR" in tu:
        return "EUR"
    return "EUR"


# ════════════════════════════════════════════════════════════════
# DATE EXTRACTION
# ════════════════════════════════════════════════════════════════

_MONTH_MAP = {
    # Deutsch
    "jan": "01", "januar": "01",
    "feb": "02", "februar": "02",
    "mär": "03", "märz": "03",
    "apr": "04", "april": "04",
    "mai": "05",
    "jun": "06", "juni": "06",
    "jul": "07", "juli": "07",
    "aug": "08", "august": "08",
    "sep": "09", "september": "09",
    "okt": "10", "oktober": "10",
    "nov": "11", "november": "11",
    "dez": "12", "dezember": "12",
    # English
    "january": "01", "february": "02", "march": "03", "mar": "03",
    "april": "04", "may": "05", "june": "06", "july": "07",
    "august": "08", "october": "10", "oct": "10",
    "december": "12", "dec": "12",
    # Français
    "janvier": "01", "janv": "01",
    "février": "02", "fevrier": "02", "fév": "02", "fev": "02",
    "mars": "03",
    "avril": "04", "avr": "04",
    "mai": "05",
    "juin": "06",
    "juillet": "07", "juil": "07",
    "août": "08", "aout": "08",
    "septembre": "09", "sept": "09",
    "octobre": "10",
    "novembre": "11",
    "décembre": "12", "decembre": "12",
    # Türkçe
    "ocak": "01", "oca": "01",
    "şubat": "02", "subat": "02", "şub": "02", "sub": "02",
    "mart": "03",
    "nisan": "04", "nis": "04",
    "mayıs": "05", "mayis": "05",
    "haziran": "06", "haz": "06",
    "temmuz": "07", "tem": "07",
    "ağustos": "08", "agustos": "08", "ağu": "08", "agu": "08",
    "eylül": "09", "eylul": "09", "eyl": "09",
    "ekim": "10", "eki": "10",
    "kasım": "11", "kasim": "11", "kas": "11",
    "aralık": "12", "aralik": "12", "ara": "12",
    # Español
    "enero": "01", "ene": "01",
    "febrero": "02",
    "marzo": "03",
    "mayo": "05",
    "junio": "06",
    "julio": "07",
    "agosto": "08",
    "septiembre": "09",
    "octubre": "10",
    "noviembre": "11",
    "diciembre": "12", "dic": "12",
    # Italiano
    "gennaio": "01", "gen": "01",
    "febbraio": "02",
    "marzo": "03",
    "aprile": "04",
    "maggio": "05", "mag": "05",
    "giugno": "06", "giu": "06",
    "luglio": "07", "lug": "07",
    "settembre": "09", "set": "09",
    "ottobre": "10", "ott": "10",
    "dicembre": "12",
}


def extract_date(raw_text: str) -> str:
    """Extract date from OCR text, supporting multiple formats."""
    text = raw_text

    # 1. Try keyword-prefixed dates first (most reliable)
    keyword_match = re.search(
        r"(?:datum|date|le|fecha)\s*:?\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})",
        text, re.IGNORECASE
    )
    if keyword_match:
        d, m, y = keyword_match.group(1), keyword_match.group(2), keyword_match.group(3)
        if len(y) == 2:
            y = "20" + y
        result = _validate_date(y, m.zfill(2), d.zfill(2))
        if result:
            return result

    # 2. Try named month patterns. Separator: bosluk, nokta, dash, slash —
    # cesitli formatlar: "15. März 2024" / "16 mars 2026" / "3 Ocak 2025" /
    # "05-DEZ-2023" (Adobe ABD/Irlanda dijital fatura) / "15/MAR/2024".
    _month_names = sorted(_MONTH_MAP.keys(), key=len, reverse=True)
    _month_pattern = "|".join(re.escape(m) for m in _month_names)
    _date_sep = r"[\s.\-/]+"
    month_match = re.search(
        rf"(\d{{1,2}})\.?{_date_sep}({_month_pattern}){_date_sep}(\d{{4}})",
        text, re.IGNORECASE
    )
    if not month_match:
        # Also try: "mars 16, 2026" / "March 16 2026" / "DEC 5, 2023" (month first)
        month_match2 = re.search(
            rf"({_month_pattern}){_date_sep}(\d{{1,2}}),?\s+(\d{{4}})",
            text, re.IGNORECASE
        )
        if month_match2:
            month_str = month_match2.group(1).lower()
            day = month_match2.group(2).zfill(2)
            year = month_match2.group(3)
            if month_str in _MONTH_MAP:
                result = _validate_date(year, _MONTH_MAP[month_str], day)
                if result:
                    return result
    if month_match:
        day = month_match.group(1).zfill(2)
        month_str = month_match.group(2).lower()
        year = month_match.group(3)
        if month_str in _MONTH_MAP:
            result = _validate_date(year, _MONTH_MAP[month_str], day)
            if result:
                return result
        # Fallback: startswith match for abbreviated forms
        for key, val in _MONTH_MAP.items():
            if month_str.startswith(key) or key.startswith(month_str):
                result = _validate_date(year, val, day)
                if result:
                    return result
                break

    # 3. DD.MM.YYYY (German standard)
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", text)
    if m:
        result = _validate_date(m.group(3), m.group(2), m.group(1))
        if result:
            return result

    # 4. DD.MM.YY
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{2})\b", text)
    if m:
        result = _validate_date("20" + m.group(3), m.group(2), m.group(1))
        if result:
            return result

    # 5. YYYY-MM-DD (ISO)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        result = _validate_date(m.group(1), m.group(2), m.group(3))
        if result:
            return result

    # 6. DD/MM/YYYY
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", text)
    if m:
        result = _validate_date(m.group(3), m.group(2), m.group(1))
        if result:
            return result

    # 7. DD/MM/YY
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})\b", text)
    if m:
        result = _validate_date("20" + m.group(3), m.group(2), m.group(1))
        if result:
            return result

    # 8. DD-MM-YYYY
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", text)
    if m:
        result = _validate_date(m.group(3), m.group(2), m.group(1))
        if result:
            return result

    return ""  # no receipt date found → leave Belegdatum empty (created_at keeps the entry date); never stamp "today"


def extract_due_date(raw_text: str) -> str:
    """Faturadaki son odeme tarihini cikarir (Rechnung due date).

    Sadece BELIRGIN ANCHOR'lar yakalanir — yoksa false-positive (mesela
    'Datum 12.03.2026' tarihi 'Zahlbar bis' yerine yakalanmamali). Default
    fatura tarihinden 14 gun sonra DEGIL — anchor yoksa bos string doner,
    DB'de NULL kalir, kullanici manuel girer.

    Anchor patternleri (Almanya + uluslararasi):
      - 'Zahlbar bis 15.03.2026'
      - 'Faellig am 15.03.2026' / 'Fallig am'
      - 'Zahlungsziel 15.03.2026'
      - 'Zahlung bis 15.03.2026'
      - 'Date due April 29, 2026'
      - 'Due date 2026-04-29'
      - 'Payment due April 29, 2026'
      - 'Bezahlen bis 15.03.2026'
    """
    if not raw_text:
        return ""
    text = raw_text

    # Anchor + tarih (ayni satir veya yakin). Almanca'da umlaut OCR'da
    # bazen 'ae' olarak yazilir: 'fällig' ve 'faellig' her ikisi yakalanir.
    anchors = (
        r"zahlbar\s*bis", r"zahlungsziel", r"zahlung\s*bis", r"bezahlen\s*bis",
        r"f(?:ä|ae)llig\s*am", r"f(?:ä|ae)llig\s*bis", r"f(?:ä|ae)lligkeit",
        r"date\s*due", r"due\s*date", r"payment\s*due", r"net\s*due",
        r"[ée]ch[ée]ance", r"[ée]ch[ée]ance\s*au", r"a\s*payer\s*avant",
    )
    anchor_re = "(?:" + "|".join(anchors) + ")"

    # Format 1: anchor + 'DD.MM.YYYY' veya 'DD-MM-YYYY' veya 'DD/MM/YYYY'
    m = re.search(
        rf"{anchor_re}\s*:?\s*(\d{{1,2}})[.\-/](\d{{1,2}})[.\-/](\d{{2,4}})",
        text, re.IGNORECASE,
    )
    if m:
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if len(y) == 2:
            y = "20" + y
        result = _validate_future_date(y, mo.zfill(2), d.zfill(2))
        if result:
            return result

    # Format 2: anchor + 'YYYY-MM-DD' (ISO)
    m = re.search(
        rf"{anchor_re}\s*:?\s*(\d{{4}})-(\d{{2}})-(\d{{2}})",
        text, re.IGNORECASE,
    )
    if m:
        result = _validate_future_date(m.group(1), m.group(2), m.group(3))
        if result:
            return result

    # Format 3: anchor + 'D Month YYYY' (e.g., '29 April 2026', '15. März 2024')
    _month_names = sorted(_MONTH_MAP.keys(), key=len, reverse=True)
    _month_pattern = "|".join(re.escape(mn) for mn in _month_names)
    m = re.search(
        rf"{anchor_re}\s*:?\s*(\d{{1,2}})\.?[\s.\-/]+({_month_pattern})[\s.\-/]+(\d{{4}})",
        text, re.IGNORECASE,
    )
    if m:
        day = m.group(1).zfill(2)
        month_str = m.group(2).lower()
        year = m.group(3)
        if month_str in _MONTH_MAP:
            result = _validate_future_date(year, _MONTH_MAP[month_str], day)
            if result:
                return result

    # Format 4: anchor + 'Month D, YYYY' / 'Month D YYYY'
    # ('Date due April 29, 2026' — Verdent format)
    m = re.search(
        rf"{anchor_re}\s*:?\s*({_month_pattern})\s+(\d{{1,2}}),?\s+(\d{{4}})",
        text, re.IGNORECASE,
    )
    if m:
        month_str = m.group(1).lower()
        day = m.group(2).zfill(2)
        year = m.group(3)
        if month_str in _MONTH_MAP:
            result = _validate_future_date(year, _MONTH_MAP[month_str], day)
            if result:
                return result

    return ""


def _validate_date(year: str, month: str, day: str) -> str | None:
    """Validate and return YYYY-MM-DD or None. Rejects unrealistic years and future dates."""
    try:
        dt = datetime(int(year), int(month), int(day))
        today = datetime.now()
        if 2020 <= dt.year <= today.year + 1:
            if dt.date() > today.date():
                days_ahead = (dt.date() - today.date()).days
                if days_ahead > 7:
                    return None
            return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return None


def _validate_future_date(year: str, month: str, day: str) -> str | None:
    """Due date validator — gelecek tarihlere izin verir (12 ay'a kadar).
    Past tarihler de OK (gecmis odeme vadesi). Rejects unrealistic years."""
    try:
        dt = datetime(int(year), int(month), int(day))
        today = datetime.now()
        if 2020 <= dt.year <= today.year + 2:
            return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return None


# ════════════════════════════════════════════════════════════════
# TOTAL AMOUNT EXTRACTION
# ════════════════════════════════════════════════════════════════

_TOTAL_KEYWORDS_HIGH = [
    # Deutsch — highest priority (final totals on receipts)
    r"zu\s*zahlen", r"zahlbetrag", r"gesamtbetrag", r"endbetrag",
    r"rechnungsbetrag", r"rechnungssumme", r"gesamtsumme", r"endsumme",
    r"summe\s*brutto", r"brutto\s*gesamt", r"bruttobetrag", r"gesamtpreis",
    r"fälliger\s*betrag", r"gesamtbetrag\s*brutto",
    r"gesamtbetrag\s*inkl", r"summe\s*inkl",
    r"summe\s*eur", r"summe", r"s[uü]mme",  # "SUMME" alone = receipt total
    # English
    r"grand\s*total", r"total\s*amount", r"amount\s*due", r"balance\s*due",
    r"total\s*due", r"invoice\s*total", r"total\s*payable", r"amount\s*payable",
    r"sum\s*total", r"final\s*total", r"total\s*incl", r"total\s*inc\s*vat",
    r"amount\s*to\s*pay", r"pay\s*this\s*amount", r"bill\s*total",
    r"order\s*total", r"payment\s*due", r"net\s*total", r"gross\s*total",
    # Français
    r"montant\s*total", r"total\s*ttc", r"net\s*[àa]\s*payer",
    r"montant\s*ttc", r"somme\s*totale", r"total\s*[àa]\s*payer",
    r"montant\s*[àa]\s*payer", r"montant\s*d[ûu]", r"solde\s*[àa]\s*payer",
    r"total\s*g[ée]n[ée]ral",
    r"montant\s*r[ée]el", r"montant\s*net", r"montant\s*brut",
    r"montant\s*facture", r"montant\s*hors\s*taxe", r"montant\s*ht",
    r"prix\s*total", r"prix\s*[àa]\s*payer", r"prix\s*net",
    r"reste\s*d[ûu]", r"solde\s*d[ûu]",
    r"total\s*facture", r"total\s*net", r"total\s*brut",
    # Türkçe
    r"toplam\s*tutar", r"genel\s*toplam", r"[öo]denecek\s*tutar",
    r"toplam\s*fiyat", r"kdv\s*dahil\s*toplam", r"vergiler\s*dahil",
    r"net\s*toplam", r"fatura\s*toplam[ıi]", r"ara\s*toplam",
    # Español
    r"importe\s*total", r"total\s*a\s*pagar", r"monto\s*total",
    r"cantidad\s*total", r"suma\s*total", r"total\s*factura",
    r"importe\s*a\s*pagar", r"total\s*con\s*iva", r"saldo\s*a\s*pagar",
    # Italiano
    r"importo\s*totale", r"totale\s*fattura", r"totale\s*da\s*pagare",
    r"importo\s*da\s*pagare", r"totale\s*complessivo", r"somma\s*totale",
    r"totale\s*generale", r"netto\s*a\s*pagare", r"importo\s*dovuto",
    # Nederlands
    r"totaalbedrag", r"te\s*betalen", r"totaal\s*te\s*betalen",
    r"verschuldigd\s*bedrag", r"factuurtotaal", r"eindbedrag",
    r"totaal\s*incl", r"totaalprijs",
    # Português
    r"valor\s*total", r"total\s*a\s*pagar", r"montante\s*total",
    r"valor\s*a\s*pagar", r"total\s*da\s*fatura",
    # Polski
    r"do\s*zap[łl]aty", r"kwota\s*do\s*zap[łl]aty", r"razem\s*do\s*zap[łl]aty",
    r"suma\s*do\s*zap[łl]aty", r"warto[śs][ćc]\s*brutto", r"razem\s*brutto",
    r"og[óo][łl]em", r"nale[żz]no[śs][ćc]",
    # Русский
    r"итого", r"всего", r"сумма\s*к\s*оплате", r"итого\s*к\s*оплате",
    r"общая\s*сумма", r"к\s*оплате", r"итого\s*с\s*ндс",
    # العربية
    r"المبلغ\s*الإجمالي", r"الإجمالي", r"المجموع", r"المبلغ\s*المستحق",
]

_TOTAL_KEYWORDS_MED = [
    # Generic / multi-language
    r"zwischensumme", r"total", r"gesamt", r"betrag", r"brutto", r"netto",
    r"5umme", r"surnme", r"sumrne", r"ge5amt", r"t0tal", r"tota1",  # OCR misreads
    r"subtotal", r"sub\s*total", r"amount", r"sum", r"due", r"price",
    # Deutsch
    r"wert", r"warenwert", r"rechnungswert", r"preis", r"steuerbetrag", r"teilbetrag", r"restbetrag",
    # English
    r"net\s*amount", r"gross\s*amount", r"tax\s*amount",
    # Français
    r"montant", r"prix", r"sous.total", r"reste\s*[àa]\s*payer",
    # Türkçe
    r"tutar", r"toplam", r"bakiye", r"[öo]deme", r"fiyat",
    r"net\s*tutar", r"iskonto",
    # Español
    r"importe", r"monto", r"cantidad", r"base\s*imponible",
    # Italiano
    r"importo", r"totale", r"imponibile", r"subtotale",
    # Nederlands
    r"totaal", r"bedrag", r"nettobedrag",
    # Polski
    r"razem", r"suma", r"[łl][aą]cznie", r"kwota",
    # Português
    r"valor", r"montante",
    # Русский
    r"сумма", r"всего", r"итого",
    # Currency / receipt abbreviations
    r"eur", r"usd", r"gbp", r"chf", r"try", r"pln",
    r"ttl", r"tot", r"amt", r"bal",
]


def extract_total(raw_text: str) -> float:
    """Extract total amount from OCR text. Scans full lines including end-of-line values."""
    text = normalize(raw_text)
    text = normalize_amount_text(text)

    # Per-line normalized text — preserve newlines so per-line scan really
    # works. `normalize` joins newlines into spaces, so we apply only the
    # comma-decimal step to the raw line.
    _per_line = []
    for _ln in raw_text.split("\n"):
        _ln = _ln.lower()
        _ln = re.sub(r"(\d{1,3})\.(\d{3}),(\d{2})\b", lambda m: f"{m.group(1)}{m.group(2)}.{m.group(3)}", _ln)
        _ln = re.sub(r"(\d+),(\d{2})\b", r"\1.\2", _ln)
        _per_line.append(_ln)

    # Lines that are addresses or dates — skip when scanning for amounts
    # (street numbers and dates look like prices). Keep the data field
    # available, just don't treat numbers in these lines as totals.
    _addr_re = re.compile(r"\b(?:str|stra(?:ß|ss)e|weg|platz|allee|gasse|ring|damm|ufer|chaussee)\.?\b", re.IGNORECASE)
    _date_re = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")

    # Lines that look like totals but are NOT (discount, tax row, partial,
    # savings shown as "you saved X"). Production hits:
    #   Lidl: "Preisvorteil 0,80"      -> NOT total (savings)
    #   Douglas: "Restbetrag 2,02"     -> NOT total (remaining after voucher)
    #   any: "MwSt 19% 5,70"           -> NOT total (tax row)
    #   any: "Netto 30,00"             -> NOT total (subtotal)
    _NEGATIVE_LINE_KWS = (
        "preisvorteil", "rabatt", "ersparnis", "nachlass", "skonto", "gutschein",
        "discount", "remise", "réduction", "reduction", "descuento", "iskonto", "indirim",
        "restbetrag", "teilbetrag", "anzahlung", "rückgeld", "wechselgeld", "rendu",
        "tip", "trinkgeld", "service",
        "zwischensumme", "subtotal", "sub-total", "ara toplam",
    )
    # Tax/subtotal rows — skip UNLESS the same line also says "Summe brutto" /
    # "Total inkl MwSt" / "Gesamtbetrag inkl" (those are the actual total).
    _TAX_ROW_KWS = ("netto", "mwst", "ust", "steuer", "tva", "vat ")
    _TAX_OVERRIDE_RE = re.compile(
        r"\b(?:summe|gesamt|total|gesamtbetrag|zu\s*zahlen|zahlbetrag|montant|importe|toplam)\b"
        r".*(?:\bbrutto\b|\binkl\b|\bincl\b|\bdahil\b|\bcon\s*iva\b|\bttc\b)",
        re.IGNORECASE,
    )

    def _is_negative_line(line: str) -> bool:
        """True if line is a discount/tax/sub row — we should not pull the total from here."""
        ll = line.lower()
        # Hard skip — discount/savings/partial/refund lines
        for kw in _NEGATIVE_LINE_KWS:
            if re.search(rf"\b{re.escape(kw)}\b", ll):
                return True
        # Soft skip — tax rows, but not if the same line is a labelled total
        for kw in _TAX_ROW_KWS:
            if re.search(rf"\b{kw}\b", ll):
                if _TAX_OVERRIDE_RE.search(ll):
                    return False
                return True
        return False

    def _last_amount_on_line(line: str):
        """Return last \\d+.dd on line, or None if line is address/date/negative-row or has no amount.
        Avoids grabbing the trailing 2 digits of a 3+ decimal token (19.008 -> 19.00).
        """
        if _addr_re.search(line):
            return None
        if _date_re.search(line):
            return None
        if _is_negative_line(line):
            return None
        amounts = re.findall(r"(?<![\d.])\d+\.\d{2}(?![\d.])", line)
        if not amounts:
            return None
        try:
            return float(amounts[-1])
        except ValueError:
            return None

    # Try high-priority keywords — line-scan FIRST (last amount on line is
    # the correct total in VAT-breakdown layouts like "Summe 1.43 8.67 10.10"),
    # then loose regex as fallback.
    _lines_high = _per_line
    for kw in _TOTAL_KEYWORDS_HIGH:
        # PRIMARY: keyword on a line → take LAST amount on that line
        for line in _lines_high:
            if re.search(rf"(?<!\w){kw}", line, re.IGNORECASE):
                v = _last_amount_on_line(line)
                if v is not None and 0.01 <= v < 100000:
                    return v
        # FALLBACK: loose regex over the joined text (covers cross-line layouts)
        pat = rf"(?<!\w){kw}\s*(?:inkl\.?\s*(?:mwst|ust|vat)\s*)?:?\s*(?:eur|€|\$|chf)?\s*(\d+\.\d{{2}})"
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            # Prefer last match (end-of-line values)
            for m in reversed(matches):
                val = float(m.group(1))
                if 0.01 <= val < 100000:
                    return val
        # NEW: keyword on line N, amount on line N+1..N+3 (big-label layouts:
        # "GESAMTBETRAG" alone on one line, amount on the next)
        for i, line in enumerate(_lines_high):
            if re.search(rf"(?<!\w){kw}\b", line, re.IGNORECASE):
                # already had amount on same line -> handled above.
                if re.search(r"\d+\.\d{2}", line):
                    continue
                for j in range(i + 1, min(i + 4, len(_lines_high))):
                    nxt = _lines_high[j].strip()
                    if not nxt:
                        continue
                    # Skip if next line is an address/date (street numbers
                    # and dates regularly look like prices to the regex).
                    if _addr_re.search(nxt) or _date_re.search(nxt):
                        continue
                    # Must be a short line with just an amount (and optionally
                    # a currency); skip if line looks like a new keyword row.
                    amts = re.findall(r"(?<![\d.])\d+\.\d{2}(?![\d.])", nxt)
                    if not amts:
                        # Non-amount text between — stop looking
                        if len(nxt) > 4 and not re.match(r"^[\s€$\-=_]*$", nxt):
                            break
                        continue
                    val = float(amts[-1])
                    if 0.01 <= val < 100000:
                        return val

    # Try medium-priority keywords — line-scan first, loose regex as fallback
    for kw in _TOTAL_KEYWORDS_MED:
        # PRIMARY: keyword on a line → take LAST amount on that line
        for line in _per_line:
            if re.search(rf"(?<!\w){kw}", line, re.IGNORECASE):
                v = _last_amount_on_line(line)
                if v is not None and 0.01 <= v < 100000:
                    return v
        # FALLBACK: loose regex over joined text
        pat = rf"(?<!\w){kw}\s*(?:inkl\.?\s*(?:mwst|ust|vat)\s*)?:?\s*(\d+\.\d{{2}})"
        matches = list(re.finditer(pat, text, re.IGNORECASE))
        if matches:
            for m in reversed(matches):
                val = float(m.group(1))
                if 0.01 <= val < 100000:
                    return val

    # EUR/€ pattern fallback — per-line, bottom-up, skips item-price lines.
    # Production trap (fis 126 Bereket Metzger): line "0,498 kg x 12,99€/Kg"
    # is a unit price (per-kilo), not a total. Without this skip the parser
    # picked 12,99 EUR instead of the real total 57,51 (no anchor on that line).
    _item_price_re = re.compile(
        r"\b(?:kg|gramm|stk|stueck|stück|st\.|x\s*\d|/\s*kg|/\s*l\b|/\s*100\s*g)\b",
        re.IGNORECASE,
    )

    def _scan_currency_lines():
        for line in reversed(_per_line):  # bottom-up
            if _addr_re.search(line) or _date_re.search(line):
                continue
            if _is_negative_line(line):
                continue
            if _item_price_re.search(line):
                # Unit-price line (e.g. '12,99 EUR/kg') — skip
                continue
            # Try strict 'X,YY' or 'X,YY EUR' / '€ X,YY' patterns
            for pat in (
                r"(?<![\d.])\d+\.\d{2}(?![\d.])\s*(?:eur|€)",
                r"(?:eur|€)\s*(?<![\d.])\d+\.\d{2}(?![\d.])",
                r"(?<![\d.])\d+\.\d{2}(?![\d.])\s*tl",
            ):
                matches = list(re.finditer(pat, line, re.IGNORECASE))
                if matches:
                    raw = matches[-1].group(0)
                    num = re.search(r"\d+\.\d{2}", raw)
                    if num:
                        val = float(num.group(0))
                        if 0.01 <= val < 100000:
                            return val
        return None

    cur_val = _scan_currency_lines()
    if cur_val is not None:
        return cur_val

    # Fallback: largest reasonable amount on the receipt
    # Skip TVA/VAT-rate rows, discount rows, AND address/date rows. Operate
    # on per-line normalized text so we keep line context (the joined `text`
    # version glues addresses next to totals).
    amounts = []
    for line in _per_line:
        # Address (Johannerstr. 105 -> 1.05 was the bug) and date rows
        if _addr_re.search(line) or _date_re.search(line):
            continue
        # TVA/VAT rate table rows
        if re.match(r"^\s*\d{1,2}[.,]\d{2}\s+\d", line):
            continue
        if re.match(r"^\s*(?:tva|vat|mwst|ust|brut\b|net\b)", line, re.IGNORECASE):
            if not re.search(r"\b(?:summe|gesamt|total|brutto)\b", line, re.IGNORECASE):
                continue
        if re.search(r"\b(?:rabatt|discount|ersparnis|nachlass|skonto|gutschein)\b", line, re.IGNORECASE):
            continue
        for m in re.findall(r"(?<![\d.])\d+\.\d{2}(?![\d.])", line):
            val = float(m)
            if 0.01 <= val < 100000:
                amounts.append(val)

    if amounts:
        return max(amounts)

    # Last resort: integer amounts near currency keywords (multi-language)
    for m in re.findall(r"(?:montant|betrag|summe|total|amount|toplam|tutar|importe|totale|الإجمالي|المجموع)\s*(?:reel\s*)?(\d+)\s*(?:eur|€|tl|₺|usd|\$|gbp|£|chf|sar|aed|dh)", text, re.IGNORECASE):
        val = float(m)
        if 1 <= val < 100000:
            return val

    return 0.0


# --- ADDED: Scoring-based total candidate re-ranker (additive, does not replace extract_total) ---
def _score_total_candidates(raw_text: str) -> list[tuple[float, int]]:
    """Return list of (amount, score) tuples ranked by payability signals.
    Multi-language scoring with strict priority hierarchy.
    Used as a confirmation layer AFTER extract_total() — not a replacement.
    """
    text = normalize(raw_text)
    text = normalize_amount_text(text)
    lines = [l for l in text.split("\n") if l.strip()]
    if not lines:
        return []
    total_lines = len(lines)

    # HIGH priority keywords (definitive total — +7 score)
    high_kws = (
        # Deutsch
        "gesamtbetrag", "gesamt betrag", "zu zahlen", "zahlbetrag", "rechnungsbetrag",
        "rechnungssumme", "gesamtsumme", "endsumme", "summe brutto", "bruttobetrag",
        "summe inkl", "gesamtbetrag inkl", "summe eur",
        # English
        "grand total", "total amount", "amount due", "balance due", "total due",
        "amount to pay", "total payable", "invoice total",
        # Français
        "montant total", "total ttc", "net a payer", "montant a payer", "total a payer",
        "montant du", "solde a payer", "total general", "montant reel",
        # Español
        "importe total", "total a pagar", "monto total", "importe a pagar", "total con iva",
        # Türkçe
        "toplam tutar", "genel toplam", "odenecek tutar", "kdv dahil toplam",
        "fatura toplami",
        # Italiano
        "importo totale", "totale da pagare", "totale fattura",
        # العربية
        "المبلغ الإجمالي", "الإجمالي", "المجموع", "المبلغ المستحق",
        # Nederlands
        "totaalbedrag", "te betalen", "totaal te betalen",
        # Polski
        "do zaplaty", "kwota do zaplaty", "razem brutto",
    )

    # MEDIUM priority keywords (+4 score)
    med_kws = (
        # Deutsch
        "summe", "gesamt", "betrag", "brutto", "gesamtpreis", "wert", "warenwert",
        # English
        "total", "amount", "sum total", "net total", "gross total",
        # Français
        "montant", "total", "prix total",
        # Español
        "importe", "total", "monto",
        # Türkçe
        "toplam", "tutar", "fiyat",
        # Italiano
        "totale", "importo",
        # Nederlands
        "totaal", "bedrag",
        # Polski
        "razem", "suma", "ogolom",
        # العربية
        "المجموع",
    )

    # LOW priority keywords (+2 score)
    low_kws = (
        "endbetrag", "preis", "amount", "price", "subtotal", "prix",
        "valor", "montante", "kwota", "bakiye",
    )

    # NEGATIVE keywords — skip these lines entirely
    neg_kws = (
        "mwst", "netto", "steuer", "tva", "ust", "vat ",
        "zwischensumme", "rabatt", "ersparnis", "nachlass", "skonto",
        "gutschein", "discount", "remise", "reduction", "descuento",
        "iskonto", "indirim",
    )

    # Special: if "summe inkl" or "total inkl" in a line with MwSt → DON'T skip
    def _is_neg_line(ll):
        if any(n in ll for n in neg_kws):
            # Exception: "summe inkl mwst", "total incl vat" etc → NOT negative
            if re.search(r"\b(?:summe|total|gesamt|montant|toplam|importe)\b.*\b(?:inkl|incl|dahil|con)\b", ll):
                return False
            return True
        return False

    # Detect if this is a discount store receipt (Lidl, Aldi, etc.)
    _is_discount = False
    _first3 = " ".join(lines[:3]).lower()
    for _ds in ("lidl", "aldi", "netto", "penny", "norma", "action", "tedi"):
        if _ds in _first3:
            _is_discount = True
            break

    scored = []
    _OCR_NUM_FIX = str.maketrans({"O": "0", "o": "0", "Z": "2", "l": "1", "I": "1"})

    for idx, line in enumerate(lines):
        line_lower = line.lower()

        if _is_neg_line(line_lower):
            continue

        # Fix common OCR digit misreads
        _line_fixed = re.sub(r"[OoZlI](?=\d|[.,])|(?<=\d)[OoZlI]", lambda m: m.group(0).translate(_OCR_NUM_FIX), line)

        for m in re.findall(r"(\d+\.\d{2})", _line_fixed):
            try:
                val = float(m)
            except ValueError:
                continue
            if not (0.01 <= val < 100000):
                continue

            score = 1

            # Keyword scoring (strict priority)
            if any(k in line_lower for k in high_kws):
                score += 7
            elif any(k in line_lower for k in med_kws):
                score += 4
                # Discount store "betrag" boost — it IS the total
                if _is_discount and "betrag" in line_lower:
                    score += 2
            elif any(k in line_lower for k in low_kws):
                score += 2

            # Currency boost
            if "€" in line or "eur" in line_lower:
                score += 2
            elif any(c in line_lower for c in ("tl", "₺")):
                score += 1  # Turkish Lira
            elif any(c in line_lower for c in ("usd", "$", "gbp", "£", "chf")):
                score += 1

            # Negative value detection (refund/discount amounts)
            if re.search(r"[-−]\s*\d+\.\d{2}", line):
                score -= 4

            # Suspiciously large amounts
            if val > 10000:
                score -= 2
            elif val > 50000:
                score -= 4

            # Position boost (totals tend to be at the bottom)
            pos = idx / total_lines
            if pos > 0.75:
                score += 3
            elif pos > 0.55:
                score += 2
            elif pos > 0.35:
                score += 1

            scored.append((val, score))

    scored.sort(key=lambda t: (-t[1], -t[0]))
    return scored


# ════════════════════════════════════════════════════════════════
# VAT EXTRACTION & CALCULATION
# ════════════════════════════════════════════════════════════════

def extract_vat_info(raw_text: str, total: float, country: str) -> tuple[list[float], float]:
    """
    Extract VAT rates and calculate VAT amount.
    Returns (vat_rates, vat_amount).
    """
    text = normalize(raw_text)
    text = normalize_amount_text(text)

    # 0. German tax-class summary table ("Typ Netto USt Brutto" + "A 16,81 3,19
    #    20,00"), common on fuel/POS receipts. Most reliable signal WHEN present
    #    and fully guarded (netto+steuer≈brutto, rate snaps to a known DE rate,
    #    brutto≈total). Returns None — never fabricates — when unvalidated.
    _tbl = _extract_vat_from_tax_table(text, total)
    if _tbl is not None:
        return _tbl

    # 1. Try to find explicit VAT amount on receipt
    vat_amount = _extract_explicit_vat_amount(text)

    # 2. Try to find explicit VAT rate
    vat_rates = _extract_vat_rates(text, country)

    # 3. If we have an explicit VAT amount, use it
    if vat_amount and vat_amount > 0:
        if total > 0 and vat_amount < total:
            if not vat_rates:
                implied_rate = round((vat_amount / (total - vat_amount)) * 100, 1)
                known = KNOWN_VAT_RATES.get(country, [])
                for kr in known:
                    if abs(implied_rate - kr) < 1.5:
                        vat_rates = [kr]
                        break
                if not vat_rates:
                    vat_rates = [implied_rate]
            return vat_rates, round(vat_amount, 2)

    # 4. If we found rates but no amount, calculate
    if vat_rates and total > 0:
        rate = vat_rates[0]
        amount = round(total * rate / (100 + rate), 2)
        return vat_rates, amount

    # 5. Country default — SADECE metinde VAT/KDV sinyali varsa.
    # Aksi halde KDV uydurmus olursunuz (ABD/UK/Isvicre disi A4 fatura
    # KDV'siz olabilir; Verdent gibi USD aboneliklerde 'Subtotal $19,
    # Total $19' var, KDV yok). Bu durumda 0/0% donmek dogru cevap.
    has_vat_signal = bool(
        re.search(
            r"\b(?:mwst|ust|mehrwertsteuer|umsatzsteuer|steuer|"
            r"vat|tva|iva|gst|hst|impuesto|tax)\b",
            text, re.IGNORECASE,
        )
        or "%" in text
    )
    if not has_vat_signal:
        return [0.0], 0.0

    default_rate = COUNTRY_VAT_DEFAULTS.get(country, 19.0)
    if total > 0:
        amount = round(total * default_rate / (100 + default_rate), 2)
        return [default_rate], amount

    return [default_rate], 0.0


# German tax-class summary table (fuel/POS receipts). Header order Netto→Steuer
# →Brutto; the steuer token is OCR-noisy (USt / MwSt / Hust / Nust / Mst / MST).
_VAT_TABLE_HEADER_RE = re.compile(
    r"netto[^|]{0,25}(?:u\.?st|mwst|hust|nust|tust|mst|steuer)[^|]{0,25}brutto",
    re.IGNORECASE,
)
# A data row: tax-class letter (A-D), optional garbled rate, then the
# Netto / Steuer / Brutto triple (already dot-normalized by normalize_amount_text).
_VAT_TABLE_ROW_RE = re.compile(
    r"\b([a-d])\b[^|]{0,12}?"
    r"(\d{1,4}\.\d{2})\s+(\d{1,4}\.\d{2})\s+(\d{1,4}\.\d{2})",
    re.IGNORECASE,
)
_KNOWN_DE_VAT_RATES = (19.0, 7.0, 16.0, 5.0)


def _extract_vat_from_tax_table(text: str, total: float):
    """Parse a German 'Typ Netto USt Brutto' tax-class summary table.

    Returns (vat_rates, vat_amount) or None. CONSERVATIVE / guard-first — it
    only returns a value when EVERY check passes, otherwise None so the caller
    keeps its existing behaviour. Never fabricates VAT.

    Guards:
      R4  netto + steuer ≈ brutto (arithmetic identity, ±0.02)
      R3  steuer/netto snaps to a known DE rate (±1.0) — else reject the row
      R4  parsed brutto(s) reconcile with the receipt total (±max(0.05, 1%))
    """
    if not text or total is None:
        return None
    if not _VAT_TABLE_HEADER_RE.search(text):
        return None
    rows = []
    for m in _VAT_TABLE_ROW_RE.finditer(text):
        try:
            netto, steuer, brutto = float(m.group(2)), float(m.group(3)), float(m.group(4))
        except (TypeError, ValueError):
            continue
        if netto <= 0 or brutto <= 0 or steuer < 0:
            continue
        if abs(netto + steuer - brutto) > 0.02:          # R4: identity
            continue
        implied = (steuer / netto) * 100 if netto else 0
        rate = next((r for r in _KNOWN_DE_VAT_RATES if abs(implied - r) <= 1.0), None)
        if rate is None:                                  # R3: known-rate only
            continue
        rows.append((rate, round(steuer, 2), round(brutto, 2)))
    if not rows:
        return None
    sum_brutto = round(sum(r[2] for r in rows), 2)
    if total > 0 and abs(sum_brutto - total) > max(0.05, total * 0.01):
        return None                                       # R4: reconcile w/ total
    vat_amount = round(sum(r[1] for r in rows), 2)
    vat_rates = sorted({r[0] for r in rows}, reverse=True)
    return vat_rates, vat_amount


def _extract_explicit_vat_amount(text: str) -> float | None:
    """Try to find an explicitly stated VAT/MwSt amount.

    R1: accept both dot and comma decimals ([.,]) as a safety net. Primary text
    is already dot-normalized by normalize_amount_text, but a stray comma (e.g.
    'MwSt 19% 3,19' before normalization, or a thousands edge case) is recovered.
    """
    patterns = [
        r"(?:mwst|ust|mehrwertsteuer|umsatzsteuer)\s*(?:\d+\s*%\s*)?:?\s*(\d+[.,]\d{2})",
        r"(?:tva|taxe)\s*(?:\d+[\.,]\d+\s*%\s*)?:?\s*(\d+[.,]\d{2})",
        r"(?:vat|tax)\s*(?:\d+\s*%\s*)?:?\s*(\d+[.,]\d{2})",
        r"(?:steuer|imposta|iva)\s*:?\s*(\d+[.,]\d{2})",
        r"davon\s*mwst\s*:?\s*(\d+[.,]\d{2})",
        r"(?:enth(?:\.|ält)|incl(?:\.|uding)?)\s*(?:mwst|ust|vat)\s*(?:\d+\s*%\s*)?:?\s*(\d+[.,]\d{2})",
        r"mwst[-\s]*betrag\s*:?\s*(\d+[.,]\d{2})",
        r"ust[-\s]*betrag\s*:?\s*(\d+[.,]\d{2})",
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", "."))
            except ValueError:
                continue
    return None


def _extract_vat_rates(text: str, country: str) -> list[float]:
    """Extract VAT percentage rates from text."""
    rates = set()
    known = KNOWN_VAT_RATES.get(country, [])

    # Find all percentage mentions
    for m in re.findall(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", text):
        val = float(m.replace(",", "."))
        if 0 < val <= 30:
            rates.add(val)

    # Look for MwSt/USt specific patterns
    for m in re.findall(r"(?:mwst|ust|tva|vat|iva|btw|kdv)\s*:?\s*(\d{1,2}(?:[.,]\d{1,2})?)\s*%?", text, re.IGNORECASE):
        val = float(m.replace(",", "."))
        if 0 < val <= 30:
            rates.add(val)

    return sorted(rates, reverse=True)


# ════════════════════════════════════════════════════════════════
# INVOICE NUMBER EXTRACTION
# ════════════════════════════════════════════════════════════════

_INVOICE_NUMBER_PATTERNS = [
    # Standalone patterns with known prefixes (highest priority)
    (r"\b(RE-[\w\-]{4,25})\b", 0),
    (r"\b(INV-[\w\-]{4,25})\b", 0),
    (r"\b(RG-[\w\-]{4,25})\b", 0),
    (r"\b(FC-[\w\-]{4,25})\b", 0),
    # German patterns
    (r"(?:rechnungs?\.?\s*(?:nr|nummer|no)\.?|re\.?\s*nr\.?)\s*:?\s*([A-Z0-9][\w\-/]{2,25})", re.IGNORECASE),
    (r"(?:beleg\.?\s*(?:nr|nummer|no)\.?|beleg-nr\.?)\s*:?\s*([A-Z0-9][\w\-/]{2,25})", re.IGNORECASE),
    (r"(?:bon\.?\s*(?:nr|nummer)\.?|bon-nr\.?)\s*:?\s*(\d[\w\-/]{2,20})", re.IGNORECASE),
    (r"(?:quittungs?\.?\s*(?:nr|nummer)\.?|quittung\s*nr\.?)\s*:?\s*([A-Z0-9][\w\-/]{2,20})", re.IGNORECASE),
    # International patterns
    (r"(?:invoice\.?\s*(?:no|number|nr|#)\.?|inv[\.-])\s*:?\s*([A-Z0-9][\w\-/]{2,20})", re.IGNORECASE),
    (r"(?:receipt\.?\s*(?:no|number|#)\.?)\s*:?\s*(\d[\w\-/]{2,20})", re.IGNORECASE),
    (r"(?:facture\.?\s*(?:no|numéro|n°)\.?)\s*:?\s*([A-Z0-9][\w\-/]{2,20})", re.IGNORECASE),
    (r"(?:ticket\.?\s*(?:no|nr)\.?)\s*:?\s*(\d[\w\-/]{2,20})", re.IGNORECASE),
    # Generic document number
    (r"(?:dok(?:ument)?\.?\s*(?:nr|nummer)\.?|doc\.?\s*(?:no|#)\.?)\s*:?\s*([A-Z0-9][\w\-/]{2,20})", re.IGNORECASE),
    # Rechnung-Nr.: with colon (MediaMarkt style)
    (r"(?:rechnung-nr\.?)\s*:?\s*([A-Z0-9][\w\-/]{2,25})", re.IGNORECASE),
]


def extract_invoice_number(raw_text: str) -> str:
    """Extract invoice/receipt number."""
    for pattern, flags in _INVOICE_NUMBER_PATTERNS:
        match = re.search(pattern, raw_text, flags)
        if match:
            num = match.group(1).strip()
            if num and not re.match(r"^0+$", num) and len(num) <= 25:
                return num
    return ""


# ════════════════════════════════════════════════════════════════
# PAYMENT METHOD DETECTION
# ════════════════════════════════════════════════════════════════

_PAYMENT_PATTERNS: dict[str, list[str]] = {
    "card": [
        "karte", "card", "carte", "ec-karte", "ec karte", "girocard",
        "maestro", "debit", "kredit", "credit", "visa", "mastercard",
        "amex", "american express", "contactless", "kontaktlos", "nfc",
        "kartenzahlung", "elektronisch",
    ],
    "cash": [
        "bar ", "bargeld", "cash", "barzahlung", "gegeben", "rückgeld",
        "wechselgeld", "espèces",
    ],
    "transfer": [
        "überweisung", "transfer", "bank transfer", "virement",
        "sepa", "iban",
    ],
    "paypal": ["paypal"],
    "klarna": ["klarna"],
    "apple_pay": ["apple pay"],
    "google_pay": ["google pay"],
}


def detect_payment_method(raw_text: str) -> str:
    """Detect payment method from receipt text."""
    text_lower = raw_text.lower()

    for method, keywords in _PAYMENT_PATTERNS.items():
        for kw in keywords:
            if kw in text_lower:
                return method

    return ""


# ════════════════════════════════════════════════════════════════
# MAIN PARSER
# ════════════════════════════════════════════════════════════════

def parse_invoice(raw_text: str) -> dict:
    """
    Parse OCR text into structured invoice data.

    Returns dict with keys:
        total_amount, vat_amount, vat_rate, vendor, date,
        category, invoice_number, payment_method, country, raw_text
    """
    if not raw_text or not raw_text.strip():
        return {
            "total_amount": 0.0,
            "vat_amount": 0.0,
            "vat_rate": "0%",
            "vendor": "Unbekannt",
            "date": "",
            "category": "other",
            "invoice_number": "",
            "payment_method": "",
            "country": "DE",
            "raw_text": raw_text or "",
        }

    # FINGERPRINT — barcode/serial/company-name pattern. Deterministik,
    # OCR'in logo bozulmasindan etkilenmez. Tum raw_text'i tarar (QR ekleri
    # dahil). Match olursa vendor kesin belli; logo OCR'a guvenmek yerine
    # bunu kullaniriz. (Lidl '0888303...' barcode prefix + 'LDL-' kasa
    # serial / Adobe 'Adobe Systems' / Aral 'Aral AG' / vs.)
    fp_vendor = detect_vendor_from_fingerprint(raw_text)
    if fp_vendor:
        vendor = fp_vendor
        vendor_source = "fingerprint"
    else:
        vendor = extract_vendor(raw_text)
        vendor_source = "primary"
        # If vendor not found, try deep search in full OCR text
        if vendor == "Unbekannt" or len(vendor) <= 2:
            deep_vendor = _deep_vendor_search(raw_text)
            if deep_vendor != "Unbekannt":
                vendor = deep_vendor
                vendor_source = "deep"
    # Last resort: pick a meaningful first-line candidate so small unknown
    # stores (Bereket, De Nico, Topaz) surface a real name instead of
    # 'Unbekannt'. User can correct it in the editor.
    if vendor == "Unbekannt":
        first_line = _first_line_vendor_guess(raw_text)
        if first_line:
            vendor = first_line
            vendor_source = "guess"
    country = detect_country(raw_text)
    currency = detect_currency(raw_text)
    category = detect_category(vendor, raw_text)
    date = extract_date(raw_text)
    due_date = extract_due_date(raw_text)
    total = extract_total(raw_text)

    # Single fallback: only if extract_total found nothing.
    # The previous 5-layer override chain (Betrag/Brutto/Summe/best_amount/
    # scoring) is what made parsing non-deterministic — each layer used a
    # slightly different regex, picking different amounts on the same text.
    # extract_total now does bottom-first scan with negative-line filtering
    # (Preisvorteil/Restbetrag/MwSt/Netto skipped) and address/date guarding.
    # Trust it; only invoke a fallback when it returned nothing usable.
    if total is None or total <= 0:
        better = extract_best_amount(raw_text)
        if better is not None and better > 0:
            total = better
        else:
            _scored = _score_total_candidates(raw_text)
            if _scored:
                total = _scored[0][0]

    vat_rates, vat_amount = extract_vat_info(raw_text, total, country)
    vat_rate_str = f"{vat_rates[0]}%" if vat_rates else "0%"
    invoice_number = extract_invoice_number(raw_text)
    payment_method = detect_payment_method(raw_text)

    # --- ADDED START: Extract company details (IBAN, address, phone, email) ---
    entities = extract_entities(raw_text)
    # --- ADDED END ---

    # --- Merchant normalization (post-extraction, non-invasive) ---
    merchant, merchant_confidence = detect_merchant(raw_text)
    # If merchant detected with high confidence and vendor is generic, upgrade vendor
    if merchant and merchant_confidence >= 0.75 and vendor in ("Unbekannt", "", None):
        vendor = merchant
    # If merchant detected, also try to improve category
    if merchant and merchant_confidence >= 0.65:
        merchant_cat = detect_category(merchant, "")
        if merchant_cat != "other" and category == "other":
            category = merchant_cat

    # Vendor sanity check — eger generic PDF artigi yakaladiysak (Page, Invoice, Receipt,
    # vs.) VEYA hala Unbekannt ise vendor_email domain'inden vendor adi turet.
    # Ornek: support@anthropic.com -> 'Anthropic'
    _generic_vendor_re = re.compile(
        r"^(unbekannt|page\s|seite\s|invoice|receipt|bill\s|description|date\b|"
        r"summary|customer|kunde|order|amount|total|please|hello|hallo)",
        re.IGNORECASE
    )
    # entities["emails"] order-preserving list -> ilk email genelde vendor (text basinda),
    # sonrakiler musteri/bill-to. Generic provider'lari atla.
    _free_providers = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
                        "yahoo.com", "live.com", "icloud.com", "web.de", "gmx.de",
                        "gmx.com", "gmx.net", "t-online.de", "aol.com", "mail.com"}
    _vendor_email = ""
    if isinstance(entities, dict) and entities.get("emails"):
        # Vendor email = ilk non-free-provider email (text sirasi korunmus)
        for _e in entities["emails"]:
            _d = (_e.split("@", 1)[-1] if "@" in _e else "").strip().lower()
            if _d and _d not in _free_providers:
                _vendor_email = _e
                break
        if not _vendor_email:
            _vendor_email = entities["emails"][0]  # fallback
    if (vendor in ("Unbekannt", "", None) or _generic_vendor_re.match(str(vendor or ""))) and _vendor_email:
        _domain = _vendor_email.split("@", 1)[-1].strip().lower()
        if _domain and _domain not in _free_providers:
            _name = _domain.split(".")[0]
            if _name and len(_name) >= 2:
                vendor = _name.capitalize() if _name.islower() else _name
                vendor_source = "email_domain"

    # P1-1: known-brand-in-header override. The extractor sometimes picks a
    # header line that MISSES the brand sitting on a different line (OCR split
    # "Bauhaus Gesellschaft" / "Bau und Hausbedarf mbH" -> picked the 2nd, so
    # neither the brand boost nor canonicalize fired). If a known brand appears
    # in the header AND the current vendor is weak (and isn't already a known
    # brand), prefer the brand. Header-only scan avoids matching branded items
    # in the body. Fail-soft.
    try:
        _cur_v = str(vendor or "").strip().lower()
        _weak = (vendor in ("Unbekannt", "", None)) or (vendor_source in ("guess", "primary", "email_domain"))
        _already_brand = any(re.search(r"\b" + re.escape(_k) + r"\b", _cur_v)
                             for _k in VENDOR_CATEGORY_MAP if len(_k) >= 4)
        _generic_brand_skip = {
            "netto", "total", "penny", "tankstelle", "taxi", "apotheke",
            "pharmacy", "pharmacie", "hit", "basic", "combi", "star",
            "real", "coop", "alex", "jet",
        }
        if _weak and not _already_brand:
            _head = " ".join((raw_text or "").split("\n")[:6]).lower()
            for _k in sorted(VENDOR_CATEGORY_MAP.keys(), key=len, reverse=True):
                if len(_k) < 4 or _k in _generic_brand_skip:
                    continue
                if re.search(r"\b" + re.escape(_k) + r"\b", _head):
                    vendor = _k.upper() if len(_k) <= 5 else _k.title()
                    vendor_source = "brand_ocr"
                    break
    except Exception:
        pass

    # Garbage choke-point (vendor only): the 'guess'/email paths bypass
    # _clean_vendor_name, so a nonsense logo line could still reach here with a
    # source-based confidence (e.g. 'er en DR ar | ae' as 'guess'). Reject it ->
    # 'Unbekannt' -> confidence 0 -> needs_review, instead of trusting noise.
    # Known brands / legal-suffix names are whitelisted. total/date untouched.
    try:
        _vchk = str(vendor or "").strip()
        if _vchk and _vchk != "Unbekannt":
            _known = any(k in _vchk.lower() for k in VENDOR_CATEGORY_MAP if len(k) >= 2) \
                or bool(_VENDOR_SUFFIX_RE.search(_vchk))
            if not _known and _is_garbage_vendor(_vchk):
                vendor = "Unbekannt"
                vendor_source = "garbage_rejected"
    except Exception:
        pass

    # Vendor-specific confidence (0-100), reliability by source. Lets the UI/log
    # flag UNCERTAIN vendors instead of trusting them. (vendor only — total/date untouched.)
    _vc_map = {"fingerprint": 95, "deep": 78, "primary": 66, "email_domain": 50, "guess": 32}
    if vendor in ("Unbekannt", "", None):
        vendor_confidence = 0
    else:
        vendor_confidence = _vc_map.get(vendor_source, 50)
        try:
            _vl = " " + str(vendor).lower() + " "
            if _VENDOR_SUFFIX_RE.search(str(vendor)) or any((" " + k + " ") in _vl for k in VENDOR_CATEGORY_MAP if len(k) >= 4):
                vendor_confidence = max(vendor_confidence, 88)  # legal suffix or known brand in the name
        except Exception:
            pass
        if merchant and merchant_confidence and str(vendor) == str(merchant):
            vendor_confidence = max(vendor_confidence, int(merchant_confidence * 100))

    return {
        "total_amount": total,
        "vat_amount": vat_amount,
        "vat_rate": vat_rate_str,
        "vendor": vendor,
        "vendor_source": vendor_source,
        "vendor_confidence": vendor_confidence,
        "date": date,
        "category": category,
        "invoice_number": invoice_number,
        "payment_method": payment_method,
        "country": country,
        "currency": currency,
        "raw_text": raw_text,
        "merchant": merchant,
        "merchant_confidence": merchant_confidence,
        "due_date": due_date,
        "vendor_iban": entities.get("ibans", [""])[0] if entities.get("ibans") else "",
        "vendor_email": entities.get("emails", [""])[0] if entities.get("emails") else "",
        "vendor_phone": entities.get("phones", [""])[0] if entities.get("phones") else "",
        "vendor_fax": entities.get("faxes", [""])[0] if entities.get("faxes") else "",
        "vendor_address": entities.get("addresses", [""])[0] if entities.get("addresses") else "",
        "vendor_ust_id": entities.get("ust_ids", [""])[0] if entities.get("ust_ids") else "",
        "vendor_hrb": entities.get("hrbs", [""])[0] if entities.get("hrbs") else "",
        "vendor_steuernr": entities.get("steuernrs", [""])[0] if entities.get("steuernrs") else "",
        "vendor_domain": entities.get("domains", [""])[0] if entities.get("domains") else "",
        "vendor_website": entities.get("domains", [""])[0] if entities.get("domains") else "",
    }


# --- ADDED START ---
def extract_entities(text: str) -> dict:
    """Extract structured entities (IBAN, email, phone, address) from OCR text using regex."""
    import re as _re

    # IBAN — sadece "IBAN" label'inden sonra eslesir (uydurma riskini onler).
    # Onceki regex label'siz uzun rakam dizilerini IBAN sayiyordu — fatura
    # numaralari, telefonlar, tarih+kart no kombinasyonlari yanlis pozitif veriyordu.
    iban_pat = r"(?i)IBAN[\s:.\-]*([A-Z]{2}\s?\d{2}\s?(?:\d{4}\s?){2,7}\d{1,4})"
    raw_ibans = _re.findall(iban_pat, text)
    ibans = [i.replace(" ", "").upper() for i in raw_ibans if len(i.replace(" ", "")) >= 15]

    # Email — @ zorunlu, yanlis pozitif riski dusuk
    email_pat = r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b"
    emails = _re.findall(email_pat, text)

    # Phone — Tel/Telefon ayri, Fax ayri. Permissive number pattern:
    # uluslararasi format destegi (+353 1 2345678 / +49 89 1234567 /
    # +44 20 7946 0958 / 0681 12345 / 030 1234567 hepsi).
    # 8-25 karakter, baslangic + veya rakam, icerik rakam/bosluk/dash/paren/slash.
    _phone_num = r"([\+\d][\d\s\-/()]{7,24})"
    tel_pat = r"(?i)(?:tel|telefon|telephone|phone|fon)\.?[\s.:\-]*" + _phone_num
    fax_pat = r"(?i)(?:fax|telefax)\.?[\s.:\-]*" + _phone_num
    raw_tels = _re.findall(tel_pat, text)
    raw_faxes = _re.findall(fax_pat, text)
    # Filter: at least 7 digits (otherwise too generic) + reject if too many spaces
    def _is_phone(s: str) -> bool:
        digits = sum(c.isdigit() for c in s)
        return digits >= 7 and digits <= 16  # max 16 digits (E.164 limit)
    phones = [p.strip() for p in raw_tels if _is_phone(p)]
    faxes = [f.strip() for f in raw_faxes if _is_phone(f)]

    # Address: lines containing street keywords + (optional) house number.
    # Genisletildi: A4 dijital fatura adresinde sokak adi var ama ev numarasi
    # baska satirda olabilir (Adobe: "10, Wiesenstrasse Dudweiler"). Ev no
    # zorunlu degil — sadece sokak keyword'u yeterli.
    addr_keywords = r"(?:str\.|straße|strasse|weg|platz|allee|gasse|ring|damm|ufer|chaussee|avenue|rue|road|street)"
    addr_pat = r"(?i)(.{0,40}" + addr_keywords + r".{0,30}\d{0,5}.{0,20})"
    addresses = [a.strip() for a in _re.findall(addr_pat, text)]
    # PLZ + Ort — 5 rakam + (Title-case VEYA UPPERCASE) sehir adi.
    # 'SAARBRUCKEN' gibi tum buyuk harf yazimi da yakalanir
    # (Adobe ABD/Irlanda dijital faturalari boyle yaziyor).
    # NOT: \s+ yerine [ \t]+ — newline match etmesin diye (yoksa farkli
    # satirlardaki kelimeleri birbirine yapistirir).
    plz_pat = (
        r"\b(\d{5}[ \t]+"
        r"(?:[A-ZÄÖÜ][a-zäöüß]{2,}|[A-ZÄÖÜ]{3,})"
        r"(?:[ \t]+(?:[A-ZÄÖÜ][a-zäöüß]{2,}|[A-ZÄÖÜ]{3,}))?"
        r")\b"
    )
    addresses += [a.strip() for a in _re.findall(plz_pat, text)]

    # USt-IdNr (Almanya KDV no) — vendor kimlik anahtari, OCR bozulmasina dayanikli
    # DE + 9 rakam, arada bosluk olabilir. "USt-Id" / "USt-IdNr" etiketi ile
    # veya etiketsiz yakalanir.
    ust_id_pat = r"(?i)\b(DE)\s?(\d{3}\s?\d{3}\s?\d{3})\b"
    raw_ust = _re.findall(ust_id_pat, text)
    ust_ids = ["DE" + n.replace(" ", "") for _, n in raw_ust]

    # Steuernummer (Almanya yerel vergi no) — USt-IdNr'den FARKLI.
    # Format: 12/345/67890 veya 123/4567/8901 (genelde "Steuernr.:" / "St.-Nr." sonrasi).
    steuernr_pat = (
        r"(?i)(?:steuer-?nr\.?|st\.?-?nr\.?|steuernummer)\s*:?\s*"
        r"(\d{2,3}\s?/\s?\d{3,4}\s?/\s?\d{4,5})"
    )
    raw_steuernr = _re.findall(steuernr_pat, text)
    steuernrs = [s.replace(" ", "") for s in raw_steuernr]

    # HRB / HRA — ticari sicil numarasi. "HRB 12345" veya "HRB Frankfurt 12345" formatinda.
    hrb_pat = r"(?i)\b(HR[BA])\s+(?:[A-ZÄÖÜ][a-zäöüß]+\s+)?(\d{1,7})\b"
    raw_hrb = _re.findall(hrb_pat, text)
    hrbs = [f"{prefix.upper()} {num}" for prefix, num in raw_hrb]

    # Domain (web sitesi) — vendor kimlik fallback
    domain_pat = r"(?i)\b(?:www\.)?([a-z0-9\-]{2,}\.(?:de|com|at|ch|eu|net|org|shop))\b"
    domains = [d.lower() for d in _re.findall(domain_pat, text)]

    # NOT: dict.fromkeys() ile siralamayi koruyarak unique yapariz —
    # set() kullanmak vendor email yerine musteri email'ini secebilir
    # (Anthropic invoice: support@anthropic.com ilk, hanalex122@gmail.com sonra;
    # set'le hash siralamasi musteri email'ini one alabiliyordu).
    return {
        "ibans": list(dict.fromkeys(ibans)),
        "emails": list(dict.fromkeys(emails)),
        "phones": list(dict.fromkeys(phones)),
        "faxes": list(dict.fromkeys(faxes)),
        "addresses": list(dict.fromkeys(addresses)),
        "ust_ids": list(dict.fromkeys(ust_ids)),
        "hrbs": list(dict.fromkeys(hrbs)),
        "domains": list(dict.fromkeys(domains)),
        "steuernrs": list(set(steuernrs)),
    }


# Example call:
# result = extract_entities("Rechnung an: Max Mustermann, Hauptstr. 12, 60311 Frankfurt\nIBAN: DE89 3704 0044 0532 0130 00\nTel: +49 69 1234567\nEmail: max@beispiel.de")
# print(result)
# => {"ibans": ["DE89370400440532013000"], "emails": ["max@beispiel.de"], "phones": ["+49 69 1234567"], "addresses": ["Hauptstr. 12, 60311 Frankfurt", "60311 Frankfurt"]}
# --- ADDED END ---


# --- ADDED START ---
class CompanyStore:
    """Simple in-memory company store. Matches by IBAN (primary) or email (fallback)."""

    def __init__(self):
        self._by_iban: dict[str, dict] = {}
        self._by_email: dict[str, dict] = {}

    def add_company(self, data: dict) -> dict:
        """Add or update a company entry. Returns the stored company."""
        company = {
            "name": str(data.get("name", "") or ""),
            "iban": str(data.get("iban", "") or "").replace(" ", ""),
            "email": str(data.get("email", "") or "").lower().strip(),
            "address": str(data.get("address", "") or ""),
        }
        if company["iban"]:
            self._by_iban[company["iban"]] = company
        if company["email"]:
            self._by_email[company["email"]] = company
        return company

    def find_by_iban(self, iban: str) -> dict | None:
        """Look up company by IBAN. Returns None if not found."""
        return self._by_iban.get(iban.replace(" ", ""))

    def find_by_email(self, email: str) -> dict | None:
        """Look up company by email. Returns None if not found."""
        return self._by_email.get(email.lower().strip())

    def match_or_create(self, entities: dict) -> dict:
        """Match existing company from extracted entities, or create new entry.
        Uses IBAN as primary key, email as fallback."""
        # Try IBAN match first
        for iban in entities.get("ibans", []):
            found = self.find_by_iban(iban)
            if found:
                return found
        # Fallback: try email match
        for email in entities.get("emails", []):
            found = self.find_by_email(email)
            if found:
                return found
        # No match — create new entry from entities
        new_company = {
            "name": "",
            "iban": entities.get("ibans", [""])[0] if entities.get("ibans") else "",
            "email": entities.get("emails", [""])[0] if entities.get("emails") else "",
            "address": entities.get("addresses", [""])[0] if entities.get("addresses") else "",
        }
        return self.add_company(new_company)


# Global instance
company_store = CompanyStore()

# Example usage:
# store = CompanyStore()
# store.add_company({"name": "Auchan", "iban": "FR7630004000031234567890143", "email": "info@auchan.fr", "address": "Breme d'Or"})
# entities = {"ibans": ["FR7630004000031234567890143"], "emails": [], "phones": [], "addresses": []}
# result = store.match_or_create(entities)
# print(result)  # => {"name": "Auchan", "iban": "FR7630004000031234567890143", "email": "info@auchan.fr", "address": "Breme d'Or"}
# --- ADDED END ---


# --- ADDED START: OCR quality validation & field detection helpers ---
import re as _re
import logging as _logging

_val_logger = _logging.getLogger("autotax.validation")


def validate_ocr_result(text: str) -> dict:
    """Score OCR output quality 0-100. Checks text length, amounts, dates, keywords."""
    if not text:
        return {"is_valid": False, "score": 0, "fields": {}}

    score = 0
    fields = {"has_amount": False, "has_date": False, "has_keywords": False, "has_iban": False}

    # Text length scoring (max 25 points)
    tlen = len(text.strip())
    if tlen > 200:
        score += 25
    elif tlen > 100:
        score += 20
    elif tlen > 50:
        score += 15
    elif tlen > 20:
        score += 10
    elif tlen > 5:
        score += 5

    # Amount detection (max 25 points)
    amt_patterns = [
        r"\d+[.,]\d{2}\s*€",
        r"€\s*\d+[.,]\d{2}",
        r"\b\d{1,3}(?:\.\d{3})*,\d{2}\b",
        r"\b\d+,\d{2}\b",
    ]
    for pat in amt_patterns:
        if _re.search(pat, text):
            fields["has_amount"] = True
            score += 25
            break

    # Date detection (max 20 points)
    date_patterns = [
        r"\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
    ]
    for pat in date_patterns:
        if _re.search(pat, text):
            fields["has_date"] = True
            score += 20
            break

    # Keyword detection (max 15 points)
    keywords = ["rechnung", "quittung", "beleg", "betrag", "gesamt", "summe", "total",
                "netto", "brutto", "mwst", "steuer", "ust", "datum", "kassenbon",
                "facture", "reçu", "tva", "montant"]
    text_lower = text.lower()
    kw_count = sum(1 for kw in keywords if kw in text_lower)
    if kw_count >= 3:
        score += 15
        fields["has_keywords"] = True
    elif kw_count >= 1:
        score += 8
        fields["has_keywords"] = True

    # IBAN detection (max 15 points)
    if _re.search(r"[A-Z]{2}\d{2}\s?\d{4}\s?\d{4}", text.upper()):
        fields["has_iban"] = True
        score += 15

    is_valid = score >= 30
    _val_logger.info("OCR validation: score=%d, valid=%s, len=%d, fields=%s", score, is_valid, tlen, fields)
    return {"is_valid": is_valid, "score": min(score, 100), "fields": fields}


def detect_amounts(text: str) -> list[float]:
    """Extract all monetary amounts from OCR text (German/European format)."""
    results = []
    for m in _re.finditer(r"(\d{1,3}(?:\.\d{3})*,\d{2})", text):
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            val = float(raw)
            if 0.01 <= val <= 999999:
                results.append(val)
        except ValueError:
            pass
    for m in _re.finditer(r"(?<!\d)(\d{1,6}\.\d{2})(?!\d)", text):
        try:
            val = float(m.group(1))
            if 0.01 <= val <= 999999 and val not in results:
                results.append(val)
        except ValueError:
            pass
    return sorted(set(results), reverse=True)


def detect_dates(text: str) -> list[str]:
    """Extract all dates from OCR text, return as YYYY-MM-DD."""
    results = []
    for m in _re.finditer(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if 1 <= int(d) <= 31 and 1 <= int(mo) <= 12:
            results.append(f"{y}-{mo.zfill(2)}-{d.zfill(2)}")
    for m in _re.finditer(r"(\d{1,2})[./](\d{1,2})[./](\d{2})(?!\d)", text):
        d, mo, y = m.group(1), m.group(2), "20" + m.group(3)
        if 1 <= int(d) <= 31 and 1 <= int(mo) <= 12:
            results.append(f"{y}-{mo.zfill(2)}-{d.zfill(2)}")
    for m in _re.finditer(r"(\d{4})-(\d{2})-(\d{2})", text):
        results.append(m.group(0))
    return list(dict.fromkeys(results))


def detect_vat(text: str) -> list[str]:
    """Detect VAT rates mentioned in text."""
    rates = []
    for m in _re.finditer(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", text):
        rate = m.group(1).replace(",", ".")
        try:
            val = float(rate)
            if val in (7, 19, 5.5, 10, 13, 20, 21, 25, 8.1, 3.8, 2.6, 2.1):
                rates.append(f"{val}%")
        except ValueError:
            pass
    text_lower = text.lower()
    if ("mwst" in text_lower or "ust" in text_lower) and not rates:
        rates.append("19%")
    if "tva" in text_lower and not rates:
        rates.append("20%")
    return list(dict.fromkeys(rates))


# Example:
# text = "Rechnung Nr. 12345\nDatum: 15.03.2026\nGesamt: 42,50 €\nMwSt 19%: 6,78 €"
# validate_ocr_result(text) => {"is_valid": True, "score": 85, ...}
# detect_amounts(text)      => [42.5, 6.78]
# detect_dates(text)        => ["2026-03-15"]
# detect_vat(text)          => ["19%"]
# --- ADDED END ---


# --- ADDED START: simple parse_invoice_text helper ---
import re as _re_pit

def parse_invoice_text(text: str) -> dict:
    """Extract structured data from raw OCR text using simple regex.
    Returns dict with supplier, amount, date. Missing fields → None.
    Robust to OCR noise; uses regex only; does not modify existing OCR code."""
    result = {"supplier": None, "amount": None, "date": None}
    if not text or not isinstance(text, str):
        return result

    # --- supplier: first meaningful line ---
    try:
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            # strip leading/trailing OCR noise symbols
            cleaned = _re_pit.sub(r"^[^A-Za-zÄÖÜäöüß0-9]+|[^A-Za-zÄÖÜäöüß0-9.&]+$", "", line)
            if len(cleaned) < 3:
                continue
            # must contain at least 2 letters
            letters = _re_pit.findall(r"[A-Za-zÄÖÜäöüß]", cleaned)
            if len(letters) < 2:
                continue
            result["supplier"] = cleaned[:120]
            break
    except Exception:
        pass

    # --- amount: numbers like 12.34 or 12,34 (optionally with thousands sep) ---
    try:
        amount_pattern = _re_pit.compile(
            r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3})*[.,]\d{2}|\d+[.,]\d{2})(?![\d])"
        )
        candidates = amount_pattern.findall(text)
        if candidates:
            # pick the largest numeric value as likely total
            def _to_float(s):
                s2 = s.replace(" ", "")
                # if both . and , present → last separator is decimal
                if "," in s2 and "." in s2:
                    if s2.rfind(",") > s2.rfind("."):
                        s2 = s2.replace(".", "").replace(",", ".")
                    else:
                        s2 = s2.replace(",", "")
                else:
                    s2 = s2.replace(",", ".")
                try:
                    return float(s2)
                except Exception:
                    return 0.0
            best = max(candidates, key=_to_float)
            result["amount"] = best
    except Exception:
        pass

    # --- date: common patterns dd.mm.yyyy / dd-mm-yyyy / yyyy-mm-dd / dd/mm/yy ---
    try:
        date_patterns = [
            r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b",
            r"\b(\d{4}[./-]\d{1,2}[./-]\d{1,2})\b",
        ]
        for pat in date_patterns:
            m = _re_pit.search(pat, text)
            if m:
                result["date"] = m.group(1)
                break
    except Exception:
        pass

    return result
# --- ADDED END ---


# --- ADDED START ---
def extract_best_amount(text: str):
    text_lower = text.lower()

    lines = text.split("\n")

    priority_keywords = [
        # German (highest priority)
        "betrag",
        "gesamtbetrag",
        "summe",

        # English
        "total",
        "amount due",
        "grand total",

        # French
        "montant",
        "montant réel",
        "total à payer"
    ]

    # --- MODIFIED START ---
    candidates = []
    import re
    for line in lines:
        line_lower = line.lower()
        for keyword in priority_keywords:
            if keyword in line_lower:
                matches = re.findall(r"\d+[.,]\d{2}", line)
                for m in matches:
                    try:
                        value = float(m.replace(",", "."))
                        candidates.append((keyword, value))
                    except:
                        pass

    for keyword in priority_keywords:
        for line in lines:
            if keyword in line.lower():
                matches = re.findall(r"\d+[.,]\d{2}", line)
                if matches:
                    try:
                        value = float(matches[-1].replace(",", "."))
                        return value
                    except:
                        pass

    # fallback (only if nothing found)
    if candidates:
        best = sorted(candidates, key=lambda x: x[1], reverse=True)[0]
        return best[1]
    # --- MODIFIED END ---

    return None
# --- ADDED END ---


# ════════════════════════════════════════════════════════════════
# TABLE ROW PARSER — converts messy OCR into structured rows
# ════════════════════════════════════════════════════════════════

_T_DATE = re.compile(r'(\d{1,2})[./](\d{1,2})[./](\d{2,4})')
_T_AMT = re.compile(r'-?\d[\d.]*[,]\d{2}')
_T_NR = re.compile(r'^(\d{1,4})\b')
_T_NOISE = re.compile(r'\b\d+x\b|\bx\b|[|§©®™•¶†‡]', re.IGNORECASE)


def parse_table(ocr_text: str) -> list:
    """Convert messy OCR text into structured table rows.

    Each row dict has: nr, date, description, amount, total.
    Works on invoices, receipts, and handwritten Kassenbuch scans.
    No external libraries — pure regex.
    """
    if not ocr_text:
        return []

    lines = ocr_text.strip().split('\n')
    rows = []

    for line in lines:
        line = line.strip()
        if not line or len(line) < 3:
            continue

        # Skip header lines
        lower = line.lower()
        if any(h in lower for h in ('datum', 'beschreibung', 'einnahmen', 'ausgaben', 'saldo', 'nr.')):
            continue

        # Must contain a date OR start with a number to be a valid row
        date_match = _T_DATE.search(line)
        nr_match = _T_NR.match(line)

        if not date_match and not nr_match:
            continue

        # Extract nr
        nr = int(nr_match.group(1)) if nr_match else None

        # Extract date
        date_str = None
        if date_match:
            d, m, y = date_match.group(1), date_match.group(2), date_match.group(3)
            if len(y) == 2:
                y = '20' + y
            try:
                if 1 <= int(d) <= 31 and 1 <= int(m) <= 12:
                    date_str = f'{d.zfill(2)}.{m.zfill(2)}.{y}'
            except ValueError:
                pass

        # Extract all amounts (comma-decimal German format)
        amounts = _T_AMT.findall(line)

        # Determine amount + total from position
        amount = None
        total = None
        if len(amounts) >= 2:
            amount = amounts[-2]
            total = amounts[-1]
        elif len(amounts) == 1:
            amount = amounts[0]

        # Extract description: strip nr, date, amounts from line
        desc = line
        # Remove nr from start
        if nr_match:
            desc = desc[nr_match.end():]
        # Remove date pattern (anywhere in remaining text)
        desc = _T_DATE.sub('', desc)
        # Remove all amount patterns
        for a in amounts:
            desc = desc.replace(a, '', 1)
        # Remove noise (2x, x, symbols)
        desc = _T_NOISE.sub('', desc)
        # Clean up whitespace and punctuation
        desc = re.sub(r'[.\-,;:]+$', '', desc)
        desc = re.sub(r'\s{2,}', ' ', desc).strip()
        desc = re.sub(r'^[^A-Za-zÄÖÜäöüß]+', '', desc)
        desc = re.sub(r'[^A-Za-zÄÖÜäöüß0-9.]+$', '', desc)

        rows.append({
            'nr': nr,
            'date': date_str,
            'description': desc,
            'amount': amount,
            'total': total,
        })

    # Sort by nr if available, else keep OCR order
    has_nr = any(r['nr'] is not None for r in rows)
    if has_nr:
        rows.sort(key=lambda r: (r['nr'] if r['nr'] is not None else 99999))

    return rows
