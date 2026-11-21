"""Shared types and helpers for statement parsers.

Amounts are integer cents. Sign convention: positive = charge (increases balance),
negative = payment/credit (decreases balance). A statement is valid when
previous_balance + sum(transactions) == new_balance.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

MONEY = r"[-+]?\$?[\d,]*\d?\.\d\d"
PAYMENT_RE = re.compile(r"\b(PAYMENT|AUTOPAY|AUTO PAY|AUTOMATIC PAYMENT|PYMT|THANK YOU)\b|ONLINE/MOBILE RECURRING", re.I)
# Rewards redemptions aren't refunds: counting them would understate spending.
REWARD_RE = re.compile(r"THANKYOU (PTS|POINTS)|POINTS REDEEMED|REDEMPTION|STATEMENT CREDIT|CASH ?BACK REWARD|REWARDS? CREDIT", re.I)


@dataclass
class Txn:
    trans_date: date
    post_date: date | None
    description: str
    amount: int  # cents
    kind: str  # purchase | refund | payment | reward | fee | interest | cash_advance | balance_transfer | manual


@dataclass
class ParsedStatement:
    issuer: str
    last4: str | None
    period_start: date
    period_end: date
    previous_balance: int
    new_balance: int
    summary: dict[str, int] = field(default_factory=dict)
    transactions: list[Txn] = field(default_factory=list)

    @property
    def reconciliation_diff(self) -> int:
        return self.previous_balance + sum(t.amount for t in self.transactions) - self.new_balance


class ParseError(Exception):
    pass


def to_cents(s: str) -> int:
    s = s.strip()
    neg = s.startswith("-") or s.startswith("(") or s.endswith("-")
    digits = re.sub(r"[^\d.]", "", s)
    if not digits:
        raise ParseError(f"bad amount {s!r}")
    value = round(float(digits) * 100)
    return -value if neg else value


def mdy(s: str) -> date:
    """Parse MM/DD/YY or MM/DD/YYYY."""
    m, d, y = s.split("/")
    y = int(y)
    if y < 100:
        y += 2000
    return date(y, int(m), int(d))


def resolve_mmdd(mmdd: str, period_end: date) -> date:
    """Attach a year to an MM/DD date using the statement closing date."""
    m, d = (int(x) for x in mmdd.split("/"))
    for year in (period_end.year, period_end.year - 1):
        try:
            candidate = date(year, m, d)
        except ValueError:  # Feb 29 in a non-leap year
            continue
        if candidate <= period_end + timedelta(days=7):
            return candidate
    raise ParseError(f"cannot resolve date {mmdd}")


def find_money(text: str, label_regex: str) -> int | None:
    m = re.search(label_regex + r"[ :]+(" + MONEY + ")", text, re.I)
    return to_cents(m.group(1)) if m else None


def require(value, what: str):
    if value is None:
        raise ParseError(f"could not find {what}")
    return value


def classify(description: str, amount: int, section: str) -> str:
    """section is one of: payments, purchases, fees, interest, cash_advance, balance_transfer."""
    if section == "fees":
        return "fee"
    if section == "interest":
        return "interest"
    if section in ("cash_advance", "balance_transfer"):
        return section
    if amount < 0:
        if REWARD_RE.search(description):
            return "reward"
        return "payment" if PAYMENT_RE.search(description) else "refund"
    if re.search(r"INTEREST CHARGE", description, re.I):
        return "interest"
    return "purchase"


def add_unitemized_totals(st: ParsedStatement, fees: int | None, interest: int | None) -> None:
    """Some issuers (Citi) report fees/interest only as totals. If the statement does not balance
    and those totals weren't itemized, add them as transactions on the closing date."""
    for kind, total, label in (("fee", fees, "FEES CHARGED (statement total)"),
                               ("interest", interest, "INTEREST CHARGED (statement total)")):
        if total and not any(t.kind == kind for t in st.transactions):
            st.transactions.append(Txn(st.period_end, st.period_end, label, total, kind))
