"""Per-issuer parsers for Chase, Citi, and Bank of America credit card statements."""

import re
from datetime import date

from .common import (MONEY, ParsedStatement, ParseError, Txn, add_unitemized_totals, classify,
                     find_money, mdy, require, resolve_mmdd, to_cents)

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}


def _section_for(line: str, headers: dict[str, str], prefix: bool = False) -> str | None:
    """prefix=True also matches a header followed by side-column text on the same line
    (e.g. "Standard Purchases <rewards side-column text>"). Only multi-word headers, to stay strict."""
    key = re.sub(r"\s*\(?continued\)?\s*$", "", line.strip(), flags=re.I).lower()
    if key in headers:
        return headers[key]
    if prefix:
        for h, sec in headers.items():
            if " " in h and key.startswith(h + " ") and not re.search(r"\$\d", key):
                return sec
    return None


def _signed(amount: int, section: str) -> int:
    # Anything listed under payments/credits reduces the balance regardless of how it's printed.
    return -abs(amount) if section == "payments" else amount


# ---------------------------------------------------------------- Chase
CHASE_HEADERS = {
    "payments and other credits": "payments",
    "purchase": "purchases", "purchases": "purchases",
    "fees charged": "fees",
    "interest charged": "interest",
    "cash advances": "cash_advance", "cash advance": "cash_advance",
    "balance transfers": "balance_transfer", "balance transfer": "balance_transfer",
}
CHASE_TXN = re.compile(r"^(\d\d/\d\d)\s+(.+?)\s+(-?[\d,]*\d?\.\d\d)$")


def parse_chase(text: str) -> ParsedStatement:
    m = require(re.search(r"Opening/Closing Date\s+(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)", text),
                "Chase opening/closing date")
    start, end = mdy(m.group(1)), mdy(m.group(2))
    last4 = re.search(r"Account Number:\s*(?:X+\s*)+(\d{4})", text)
    st = ParsedStatement(
        issuer="chase", last4=last4.group(1) if last4 else None,
        period_start=start, period_end=end,
        previous_balance=require(find_money(text, r"Previous Balance"), "previous balance"),
        new_balance=require(find_money(text, r"(?<!\w)New Balance"), "new balance"),
    )
    st.summary = {k: v for k, v in {
        "payments": find_money(text, r"Payment, Credits"),
        "purchases": find_money(text, r"(?<![\w ])Purchases"),
        "fees": find_money(text, r"Fees Charged"),
        "interest": find_money(text, r"Interest Charged"),
    }.items() if v is not None}

    section = None
    for line in text.splitlines():
        sec = _section_for(line, CHASE_HEADERS)
        if sec:
            section = sec
            continue
        if not section:
            continue
        tm = CHASE_TXN.match(line.strip())
        if tm:
            d = resolve_mmdd(tm.group(1), end)
            amt = _signed(to_cents(tm.group(3)), section)
            desc = tm.group(2).strip()
            st.transactions.append(Txn(d, d, desc, amt, classify(desc, amt, section)))
    add_unitemized_totals(st, st.summary.get("fees"), st.summary.get("interest"))
    return st


# ---------------------------------------------------------------- Citi
CITI_HEADERS = {
    "payments, credits and adjustments": "payments",
    "standard purchases": "purchases", "purchases": "purchases",
    "fees charged": "fees",
    "interest charged": "interest",
    "cash advances": "cash_advance", "standard advances": "cash_advance",
    "balance transfers": "balance_transfer",
}
# Older layouts append rewards side-column text after the amount, so take the first $amount on the line.
CITI_TXN = re.compile(r"^(?:(\d\d/\d\d)\s+)?(\d\d/\d\d)\s+(.+?)\s+(-?\$[\d,]*\d?\.\d\d)(?:\s+.*)?$")
CITI_DATE_START = re.compile(r"^\d\d/\d\d\s+\S")


CITI_PERIOD = r"Billing Period:\s*(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)"


def parse_citi(text: str, visible_text: str = "") -> ParsedStatement:
    # Older Citi layouts carry most text in a tiny (0.2pt) text layer, with the billing-period dates
    # drawn in a normal-size layer on top, so plain extraction interleaves them. If the period isn't
    # readable in the full text, take the first date range from the visible-only text.
    m = re.search(CITI_PERIOD, text) or re.search(r"(\d\d/\d\d/\d\d)\s*-\s*(\d\d/\d\d/\d\d)", visible_text)
    m = require(m, "Citi billing period")
    start, end = mdy(m.group(1)), mdy(m.group(2))
    if not (0 < (end - start).days < 40):
        raise ParseError("Citi billing period looks wrong")
    last4 = re.search(r"Account number ending in:?\s*(\d{4})", text, re.I)
    st = ParsedStatement(
        issuer="citi", last4=last4.group(1) if last4 else None,
        period_start=start, period_end=end,
        previous_balance=require(find_money(text, r"Previous balance"), "previous balance"),
        # "New balance as of 06/01/26:" also exists; the summary line has the amount right after.
        new_balance=require(find_money(text, r"New balance"), "new balance"),
    )
    fees = find_money(text, r"(?m)^\s*Fees")
    interest = find_money(text, r"(?m)^\s*Interest")
    st.summary = {k: v for k, v in {
        "payments": find_money(text, r"(?m)^\s*Payments"),
        "credits": find_money(text, r"(?m)^\s*Credits"),
        "purchases": find_money(text, r"(?m)^\s*Purchases"),
        "fees": fees, "interest": interest,
    }.items() if v is not None}

    section = None
    in_activity = False
    pending: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"Trans\.?\s+Post", s) or re.match(r"date\s+date\s+Description", s, re.I):
            in_activity = True
        sec = _section_for(s, CITI_HEADERS, prefix=True)
        if sec and in_activity:
            section = sec
            continue
        if not section:
            continue
        tm = CITI_TXN.match(s)
        if not tm and pending:
            # Wrapped description: the amount sits at the end of the continuation line.
            tm = CITI_TXN.match(pending + " " + s) if not CITI_DATE_START.match(s) else None
            pending = None if tm or CITI_DATE_START.match(s) else pending
        if not tm and CITI_DATE_START.match(s):
            pending = s
            continue
        if tm:
            pending = None
            post = resolve_mmdd(tm.group(2), end)
            trans = resolve_mmdd(tm.group(1), end) if tm.group(1) else post
            amt = _signed(to_cents(tm.group(4)), section)
            desc = tm.group(3).strip()
            st.transactions.append(Txn(trans, post, desc, amt, classify(desc, amt, section)))
    add_unitemized_totals(st, fees, interest)
    return st


# ---------------------------------------------------------------- Bank of America
BOFA_HEADERS = {
    "payments and other credits": "payments",
    "purchases and adjustments": "purchases",
    "fees charged": "fees", "fees": "fees",
    "interest charged": "interest",
    "cash advances": "cash_advance", "bank cash advances": "cash_advance",
    "balance transfers": "balance_transfer",
}
BOFA_TXN = re.compile(r"^(\d\d/\d\d)\s+(\d\d/\d\d)\s+(.+?)\s+(-?[\d,]*\d?\.\d\d)$")
BOFA_PERIOD = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2})\s*-\s*([A-Z][a-z]+)\s+(\d{1,2}),\s*(\d{4})")


def parse_bofa(text: str) -> ParsedStatement:
    m = require(BOFA_PERIOD.search(text), "BofA statement period")
    sm, sd, em, ed, ey = m.groups()
    end = date(int(ey), MONTHS[em.lower()], int(ed))
    smon = MONTHS[sm.lower()]
    start = date(int(ey) - (1 if smon > end.month else 0), smon, int(sd))
    last4 = re.search(r"Account\s*(?:#|Number:)\s*(?:\d{4}\s+){3}(\d{4})", text)
    st = ParsedStatement(
        issuer="bofa", last4=last4.group(1) if last4 else None,
        period_start=start, period_end=end,
        previous_balance=require(find_money(text, r"Previous Balance"), "previous balance"),
        new_balance=require(find_money(text, r"New Balance Total"), "new balance"),
    )
    fees = find_money(text, r"Fees Charged")
    interest = find_money(text, r"(?<!TOTAL )Interest Charged")
    st.summary = {k: v for k, v in {
        "payments": find_money(text, r"Payments and Other Credits"),
        "purchases": find_money(text, r"Purchases and Adjustments"),
        "fees": fees, "interest": interest,
    }.items() if v is not None}

    section = None
    for line in text.splitlines():
        s = line.strip()
        sec = _section_for(s, BOFA_HEADERS)
        if sec:
            section = sec
            continue
        tm = BOFA_TXN.match(s)
        if tm and section:
            trans = resolve_mmdd(tm.group(1), end)
            post = resolve_mmdd(tm.group(2), end)
            # Strip trailing "Reference Number" and "Account Number" columns.
            desc = re.sub(r"\s+\d{4,}\s+\d{4}$", "", tm.group(3).strip())
            amt = _signed(to_cents(tm.group(4)), section)
            st.transactions.append(Txn(trans, post, desc, amt, classify(desc, amt, section)))
    add_unitemized_totals(st, fees, interest)
    return st
