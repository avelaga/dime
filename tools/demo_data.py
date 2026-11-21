"""Generate a fully synthetic demo database (no real data) to try Dime or take screenshots.

  .venv/bin/python tools/demo_data.py                 # writes demo-data/finance.db (gitignored)
  cd backend && FINANCE_DATA_DIR=../demo-data ../.venv/bin/uvicorn app.main:app --port 8001

Covers every feature: four cards with ~2 years of reconciled statements, income with a raise and a bonus, fixed
bank expenses, subscriptions (incl. a price increase and a new one), annual renewals, a tagged trip, a partially
reimbursed work trip, a one-off purchase and an inferred no-activity month.
"""

import os
import random
import shutil
import sys
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo-data"
if DEMO.exists():
    shutil.rmtree(DEMO)
os.environ["FINANCE_DATA_DIR"] = str(DEMO)
sys.path.insert(0, str(ROOT / "backend"))

from app import db, recurring  # noqa: E402
from app.categories import merchant_key  # noqa: E402

random.seed(42)
TODAY = date(2026, 11, 21) if date.today() < date(2026, 11, 21) else date.today()
START = date(2025, 1, 1)

# (raw descriptor, display name, category, typical $, visits per month, card)
EVERYDAY = [
    ("TRADER JOE S #552 SAN MATEO CA", "Trader Joe's", "Groceries", 62, 4.0, "Citi Cash Back"),
    ("WHOLEFDS SMT 10234 SAN MATEO CA", "Whole Foods", "Groceries", 48, 2.0, "Citi Cash Back"),
    ("SQ *BLUE BOTTLE COFFEE OAKLAND CA", "Blue Bottle Coffee", "Coffee Shops", 7, 6.0, "Chase Everyday"),
    ("CHIPOTLE 2231 SAN MATEO CA", "Chipotle", "Fast Food", 14, 2.5, "Chase Everyday"),
    ("SWEETGREEN SAN MATEO CA", "Sweetgreen", "Restaurants", 17, 2.0, "Chase Everyday"),
    ("TST* NOPA SAN FRANCISCO CA", "Nopa", "Restaurants", 85, 0.7, "Chase Travel"),
    ("DOORDASH*THAI HOUSE SAN FRANCISCO CA", "DoorDash", "Food Delivery", 38, 1.6, "Chase Everyday"),
    ("SHELL OIL 57444 SAN MATEO CA", "Shell", "Gas & Fuel", 55, 2.0, "BofA Rewards"),
    ("UBER *TRIP HELP.UBER.COM CA", "Uber", "Rideshare & Taxi", 21, 1.5, "Chase Travel"),
    ("AMZN MKTP US*2K3LM1 AMZN.COM/BILL WA", "Amazon", "Online Shopping", 42, 3.0, "Chase Everyday"),
    ("TARGET 00012 SAN MATEO CA", "Target", "General Merchandise", 58, 1.2, "Citi Cash Back"),
    ("COSTCO WHSE #0423 REDWOOD CITY CA", "Costco", "General Merchandise", 165, 0.6, "Citi Cash Back"),
    ("UNIQLO SF UNION SQ SAN FRANCISCO CA", "Uniqlo", "Clothing", 70, 0.4, "Chase Everyday"),
    ("CVS/PHARMACY #9921 SAN MATEO CA", "CVS Pharmacy", "Pharmacy", 18, 0.8, "BofA Rewards"),
    ("THE HOME DEPOT #1835 SAN CARLOS CA", "Home Depot", "Home Improvement", 64, 0.5, "BofA Rewards"),
    ("AMC METREON 16 SAN FRANCISCO CA", "AMC Theatres", "Movies & Events", 32, 0.5, "Chase Travel"),
    ("CLIPPER TRANSIT SAN FRANCISCO CA", "Clipper", "Public Transit", 25, 1.0, "Citi Cash Back"),
    ("SFMTA PARKING SAN FRANCISCO CA", "SFMTA Parking", "Parking & Tolls", 12, 1.5, "BofA Rewards"),
]
# (descriptor, name, category, monthly $ by date [(from, amount)], card, start, end)
SUBSCRIPTIONS = [
    ("NETFLIX.COM LOS GATOS CA", "Netflix", "Streaming & Subscriptions", [(START, 15.49), (date(2026, 2, 1), 17.99)], "Chase Everyday", START, None),
    ("SPOTIFY USA NEW YORK NY", "Spotify", "Streaming & Subscriptions", [(START, 11.99)], "Chase Everyday", START, None),
    ("APPLE.COM/BILL ICLOUD CUPERTINO CA", "iCloud+", "Streaming & Subscriptions", [(START, 2.99)], "Chase Everyday", START, None),
    ("NYTIMES*NYTDIGITAL NEW YORK NY", "New York Times", "Streaming & Subscriptions", [(START, 4.00), (date(2026, 1, 1), 25.00)], "Citi Cash Back", START, None),
    ("PLANET FITNESS #1123 SAN MATEO CA", "Planet Fitness", "Gym & Fitness", [(START, 24.99)], "BofA Rewards", START, date(2026, 5, 31)),
    ("VERIZON WRLS P2P VERIZON.COM", "Verizon", "Phone", [(START, 70.00)], "Chase Everyday", START, None),
    ("HEADSPACE INC SANTA MONICA CA", "Headspace", "Streaming & Subscriptions", [(START, 12.99)], "Chase Everyday", date(2026, 8, 1), None),
]
ANNUAL = [  # (descriptor, name, category, $, card, month, day)
    ("AMAZON PRIME*MEMBERSHIP AMZN.COM/BILL", "Amazon Prime", "Streaming & Subscriptions", 139.00, "Chase Everyday", 3, 14),
    ("CA DMV VEHREG SACRAMENTO CA", "CA DMV Vehicle Registration", "Government Fees", 312.00, "BofA Rewards", 6, 2),
    ("ACME HOME INSURANCE CO", "Acme Home Insurance", "Insurance", 980.00, "Citi Cash Back", 1, 9),
]
CARDS = [("Chase Travel", "chase", 15, "1111"), ("Chase Everyday", "chase", 28, "2222"),
         ("Citi Cash Back", "citi", 5, "3333"), ("BofA Rewards", "bofa", 20, "4444")]


def cents(x: float) -> int:
    return int(round(x * 100))


def add_months(d: date, n: int) -> date:
    y, m = d.year + (d.month - 1 + n) // 12, (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, monthrange(y, m)[1]))


def main() -> None:
    db.init()
    txns: list[tuple] = []  # (card, date, descriptor, name, category, cents, kind, extra)

    def buy(card, d, desc, name, cat, amt, kind="purchase", **extra):
        if START <= d <= TODAY:
            txns.append((card, d, desc, name, cat, cents(amt) if kind != "payment" else amt, kind, extra))

    # Everyday spending: gentle growth + December bump.
    d = START
    while d <= TODAY:
        mult = (1 + 0.06 * ((d - START).days / 365)) * (1.35 if d.month == 12 else 1)
        for desc, name, cat, amt, per_month, card in EVERYDAY:
            if random.random() < per_month / 30.4:
                buy(card, d, desc, name, cat, max(3, random.gauss(amt * mult, amt * 0.25)))
        d += timedelta(days=1)

    for desc, name, cat, prices, card, s, e in SUBSCRIPTIONS:
        m = date(s.year, s.month, 9)
        while m <= TODAY and (e is None or m <= e):
            price = [p for since, p in prices if since <= m][-1]
            buy(card, m, desc, name, cat, price)
            m = add_months(m, 1)
    for desc, name, cat, amt, card, month, day in ANNUAL:
        for y in (2025, 2026):
            buy(card, date(y, month, day), desc, name, cat, amt)
    buy("Chase Travel", date(2025, 7, 1), "ANNUAL MEMBERSHIP FEE", "Annual Membership Fee", "Card Fees", 95, kind="fee")
    buy("Chase Travel", date(2026, 7, 1), "ANNUAL MEMBERSHIP FEE", "Annual Membership Fee", "Card Fees", 95, kind="fee")

    # One-offs: a laptop and a two-week Japan trip (booked ahead + on the ground).
    buy("Chase Everyday", date(2026, 2, 17), "APPLE STORE #R014 SAN FRANCISCO CA", "Apple Store", "Electronics & Software", 2499.00, one_off=1)
    trip = dict(one_off=1, tag="Japan 2025")
    buy("Chase Travel", date(2025, 8, 3), "ANA AIRLINES 2052834477 TOKYO", "ANA", "Air Travel", 1386.40, **trip)
    for i, (d0, amt) in enumerate([(date(2025, 8, 20), 612.00), (date(2025, 8, 21), 455.10)]):
        buy("Chase Travel", d0, f"BOOKING.COM HOTEL {i} AMSTERDAM", "Booking.com", "Hotels & Lodging", amt, **trip)
    buy("Chase Travel", date(2025, 10, 6), "JR EAST RAIL PASS TOKYO", "JR East", "Public Transit", 342.00, **trip)
    for k in range(14):
        day = date(2025, 10, 8) + timedelta(days=k)
        buy("Chase Travel", day, "ICHIRAN SHIBUYA TOKYO", "Ichiran Ramen", "Restaurants", random.uniform(12, 30), **trip)
        buy("Chase Travel", day, "7-ELEVEN TOKYO", "7-Eleven Japan", "Groceries", random.uniform(4, 14), **trip)
        if k % 3 == 0:
            buy("Chase Travel", day, "TEAMLAB PLANETS TOKYO", "teamLab", "Activities", random.uniform(25, 45), **trip)
    # Work conference: flight + hotel, reimbursed (hotel fully, flight partly).
    buy("Chase Travel", date(2026, 4, 2), "UNITED 0162345 HOUSTON TX", "United Airlines", "Air Travel", 486.20, reimbursed=cents(400))
    buy("Chase Travel", date(2026, 4, 21), "HILTON AUSTIN AUSTIN TX", "Hilton", "Hotels & Lodging", 732.80, reimbursed=cents(732.80))
    # A refund and a reward redemption, for realism.
    buy("Chase Everyday", date(2026, 3, 3), "AMZN MKTP US*RETURN AMZN.COM/BILL WA", "Amazon", "Online Shopping", -46.15, kind="refund")
    buy("Citi Cash Back", date(2026, 6, 12), "THANKYOU PTS REDEEMED", "Rewards", "Rewards Redemption", -50.00, kind="reward")

    # BofA Rewards sits unused for one cycle in Aug 2025 (paid to $0, no statement issued -> inferred "0").
    idle = ("BofA Rewards", date(2025, 7, 21), date(2025, 9, 20))
    txns = [t for t in txns if not (t[0] == idle[0] and idle[1] <= t[1] <= idle[2])]

    with db.tx() as c:
        for name, issuer, close_day, last4 in CARDS:
            aid = c.execute("INSERT INTO accounts(name, issuer, last4s) VALUES (?,?,?)", (name, issuer, last4)).lastrowid
            mine = sorted((t for t in txns if t[0] == name), key=lambda t: t[1])
            end = date(2024, 12, close_day)
            balance, n = 0, 0
            while True:
                start, end = end + timedelta(days=1), add_months(end, 1)
                if end > TODAY:
                    break
                prev = balance
                rows = [t for t in mine if start <= t[1] <= end]
                if not rows and prev == 0 and n:
                    continue  # nothing happened this cycle: issuers send no statement (Dime infers a $0 gap)
                if prev:
                    rows.append((name, min(start + timedelta(days=10), end), "AUTOMATIC PAYMENT - THANK YOU",
                                 "Payment", None, -prev, "payment", {}))
                total = sum(t[5] for t in rows)
                balance = prev + total
                n += 1
                sid = c.execute("""INSERT INTO statements(account_id, period_start, period_end, previous_balance, new_balance,
                                   summary, reconciled, recon_diff, file_hash) VALUES (?,?,?,?,?,'{}',1,0,?)""",
                                (aid, start.isoformat(), end.isoformat(), prev, balance, f"demo-{last4}-{n}")).lastrowid
                for _, d0, desc, disp, cat, amt, kind, extra in rows:
                    key = merchant_key(desc)
                    if cat:
                        c.execute("INSERT OR IGNORE INTO merchants(key, display_name, category, source) VALUES (?,?,?, 'llm')",
                                  (key, disp, cat))
                    c.execute("""INSERT INTO transactions(statement_id, account_id, trans_date, post_date, description,
                                 merchant_key, amount, kind, one_off, tag, reimbursed) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                              (sid, aid, d0.isoformat(), d0.isoformat(), desc, key, amt, kind,
                               extra.get("one_off", 0), extra.get("tag"), extra.get("reimbursed", 0)))

        for row in [("Rent", "Rent & Mortgage", 210000, "monthly", 1, "2025-01", None),
                    ("Car loan", "Auto Loan & Lease", 45000, "monthly", 5, "2025-01", None),
                    ("PG&E + water", "Utilities", 18000, "monthly", 12, "2025-01", None),
                    ("Car insurance", "Auto Insurance", 12000, "monthly", 15, "2025-01", None)]:
            c.execute("""INSERT INTO recurring(name, category, amount, frequency, day_of_month, start_month, end_month)
                         VALUES (?,?,?,?,?,?,?)""", row)
        recurring.sync(c)
        for row in [("Paycheck", 310000, "biweekly", "2025-01", "2026-02"),
                    ("Paycheck (after raise)", 345000, "biweekly", "2026-03", None),
                    ("Annual bonus", 500000, "once", "2026-03", None)]:
            c.execute("INSERT INTO income(name, amount, frequency, start_month, end_month) VALUES (?,?,?,?,?)", row)
        n_t = c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        n_s = c.execute("SELECT COUNT(*) FROM statements").fetchone()[0]
    print(f"demo database: {DEMO / 'finance.db'}  ({n_s} statements, {n_t} transactions)")


if __name__ == "__main__":
    main()
