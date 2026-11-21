"""Two-level category taxonomy, merchant-key normalization, and keyword fallback rules."""

import re

TAXONOMY: dict[str, list[str]] = {
    "Food & Dining": ["Groceries", "Restaurants", "Fast Food", "Coffee Shops", "Food Delivery", "Alcohol & Bars"],
    "Shopping": ["General Merchandise", "Online Shopping", "Clothing", "Electronics & Software",
                 "Home & Furnishings", "Hobbies & Sporting Goods", "Books"],
    "Auto & Transport": ["Gas & Fuel", "Parking & Tolls", "Rideshare & Taxi", "Public Transit",
                         "Auto Service & Parts", "Auto Insurance", "Auto Loan & Lease"],
    "Bills & Utilities": ["Phone", "Internet & Cable", "Utilities", "Streaming & Subscriptions", "Insurance"],
    "Health & Fitness": ["Pharmacy", "Doctor & Dental", "Gym & Fitness", "Vision"],
    "Travel": ["Air Travel", "Hotels & Lodging", "Rental Car", "Travel Other"],
    "Entertainment": ["Movies & Events", "Games", "Activities"],
    "Personal Care": ["Hair & Beauty", "Personal Care Other"],
    "Home": ["Home Improvement", "Home Services", "Rent & Mortgage"],
    "Pets": ["Pet Food & Supplies", "Veterinary"],
    "Education": ["Tuition & Courses"],
    "Gifts & Donations": ["Gifts", "Charity"],
    "Business & Services": ["Shipping & Postal", "Professional Services", "Business Expenses"],
    "Taxes & Government": ["Taxes", "Government Fees"],
    "Fees & Charges": ["Interest Charged", "Card Fees"],
    "Transfers": ["Credit Card Payment", "Rewards Redemption", "Exclude from Spending"],
    "Uncategorized": ["Uncategorized"],
}
PARENT_OF = {child: parent for parent, kids in TAXONOMY.items() for child in kids}
# Categories the LLM may assign (never payments/fees/interest; those come from the statement itself).
LLM_CATEGORIES = [c for p, kids in TAXONOMY.items() if p not in ("Transfers", "Fees & Charges") for c in kids]
NON_SPENDING_PARENTS = ("Transfers",)

KIND_CATEGORY = {"payment": "Credit Card Payment", "reward": "Rewards Redemption",
                 "interest": "Interest Charged", "fee": "Card Fees"}

US_STATES = set("""AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ
NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC PR""".split())
PROCESSOR_PREFIX = re.compile(
    r"^(SQ ?\*|TST ?\*|SP ?\*|SP |PAYPAL ?\*|PP ?\*|DD ?\*|PY ?\*|IC ?\*|BT ?\*|CKO ?\*|FS ?\*|GOOGLE ?\*|WPY ?\*)")


def merchant_key(description: str) -> str:
    """Stable grouping key: drop processor prefixes, store numbers, reference codes, trailing state."""
    s = description.upper().strip()
    s = PROCESSOR_PREFIX.sub("", s)
    s = re.sub(r"\*\S*\d\S*", " ", s)          # AMZN MKTP US*2K3LM1 -> AMZN MKTP US
    s = re.sub(r"#\s*\S+", " ", s)              # store numbers
    s = re.sub(r"\S*\d\S*", " ", s)             # any token containing digits (phones, ids)
    s = re.sub(r"[*]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -.,/")
    parts = s.split(" ")
    if len(parts) > 1 and parts[-1] in US_STATES:
        s = " ".join(parts[:-1])
    return s or description.upper().strip()


# Fallback keyword rules (used only when the local LLM is unavailable).
KEYWORD_RULES: list[tuple[str, str]] = [
    (r"UBER\s*EATS|DOORDASH|GRUBHUB|POSTMATES|CAVIAR", "Food Delivery"),
    (r"\bUBER\b|\bLYFT\b|TAXI|WAYMO", "Rideshare & Taxi"),
    (r"STARBUCKS|PEET|BLUE BOTTLE|PHILZ|DUNKIN|COFFEE|CAFE", "Coffee Shops"),
    (r"MCDONALD|CHIPOTLE|TACO BELL|BURGER|WENDY|SUBWAY|IN-N-OUT|CHICK-FIL|PANDA EXPRESS", "Fast Food"),
    (r"TRADER JOE|SAFEWAY|WHOLE FOODS|KROGER|SPROUTS|ALBERTSONS|RALPHS|H-E-B|PUBLIX|ALDI|GROCERY|MARKET", "Groceries"),
    (r"SHELL|CHEVRON|ARCO|EXXON|MOBIL|VALERO|76\b|SUNOCO|COSTCO GAS|FUEL", "Gas & Fuel"),
    (r"NETFLIX|SPOTIFY|HULU|DISNEY|HBO|MAX\.COM|YOUTUBE|APPLE\.COM/BILL|PARAMOUNT|PEACOCK", "Streaming & Subscriptions"),
    (r"AMAZON|AMZN", "Online Shopping"),
    (r"TARGET|WALMART|COSTCO|SAM'S CLUB", "General Merchandise"),
    (r"AIRLINE|DELTA|UNITED|SOUTHWEST|ALASKA AIR|JETBLUE|AMERICAN AIR", "Air Travel"),
    (r"HOTEL|MARRIOTT|HILTON|HYATT|AIRBNB|VRBO|INN\b", "Hotels & Lodging"),
    (r"CVS|WALGREENS|RITE AID|PHARMACY", "Pharmacy"),
    (r"COMCAST|XFINITY|SPECTRUM|INTERNET", "Internet & Cable"),
    (r"AT&T|VERIZON|T-MOBILE|MINT MOBILE|GOOGLE FI", "Phone"),
    (r"PARKING|PARK\b|TOLL|FASTRAK", "Parking & Tolls"),
    (r"RESTAURANT|GRILL|PIZZA|SUSHI|KITCHEN|BISTRO|TAQUERIA|THAI|RAMEN", "Restaurants"),
    (r"HOME DEPOT|LOWE'S|LOWES|ACE HARDWARE", "Home Improvement"),
    (r"USPS|UPS STORE|FEDEX", "Shipping & Postal"),
]


def keyword_category(key: str) -> str | None:
    for pattern, cat in KEYWORD_RULES:
        if re.search(pattern, key):
            return cat
    return None
