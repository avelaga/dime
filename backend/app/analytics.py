"""Analysis queries. Spending = everything except Transfers (payments, excluded). Refunds net out
inside their category; interest and fees count as spending under Fees & Charges."""

import re
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from .db import rows


# ---------------------------------------------------------------- helpers
def month_range(lo: str, hi: str) -> list[str]:
    y, m = int(lo[:4]), int(lo[5:7])
    out = []
    while f"{y:04d}-{m:02d}" <= hi:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def prev_month(ym: str) -> str:
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


def _d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


# ---------------------------------------------------------------- coverage
def _month_days(m: str) -> range:
    y, mo = int(m[:4]), int(m[5:7])
    return range(date(y, mo, 1).toordinal(), date(y, mo, monthrange(y, mo)[1]).toordinal() + 1)


def coverage(conn) -> dict:
    """Per card x calendar month: full | zero | partial | missing | inactive.
    A month is complete only when every open card is accounted for on every day of it, either by a
    statement or by a known no-activity gap (issuers skip the statement when nothing happened):
      * inferred: a statement closing at $0 followed by one opening at $0 means nothing posted between;
      * confirmed: the user marked that card-month as "no activity" (table no_activity).
    "zero" = accounted for, but only by a no-activity gap (no statement that month)."""
    accounts = rows(conn, """SELECT id, name, issuer, last4s, opened_on, closed_on FROM accounts
                             WHERE type = 'credit_card' ORDER BY issuer, name""")
    stmts = rows(conn, """SELECT account_id, period_start, period_end, previous_balance, new_balance
                          FROM statements ORDER BY account_id, period_start""")
    overrides: dict[int, set[str]] = defaultdict(set)
    for r in conn.execute("SELECT account_id, month FROM no_activity"):
        overrides[r["account_id"]].add(r["month"])
    if not stmts or not accounts:
        return {"months": [], "accounts": [dict(a, cells={}, no_activity=[]) for a in accounts], "complete": {}}
    months = month_range(min(s["period_start"] for s in stmts)[:7], max(s["period_end"] for s in stmts)[:7])

    stmt_days: dict[int, set[int]] = defaultdict(set)
    zero_days: dict[int, set[int]] = defaultdict(set)
    by_acct: dict[int, list[dict]] = defaultdict(list)
    for s in stmts:
        stmt_days[s["account_id"]].update(range(_d(s["period_start"]).toordinal(), _d(s["period_end"]).toordinal() + 1))
        by_acct[s["account_id"]].append(s)
    for aid, ss in by_acct.items():
        for a, b in zip(ss, ss[1:]):
            if a["new_balance"] == 0 and b["previous_balance"] == 0:
                zero_days[aid].update(range(_d(a["period_end"]).toordinal() + 1, _d(b["period_start"]).toordinal()))
    for aid, ms in overrides.items():
        for m in ms:
            zero_days[aid].update(_month_days(m))

    complete = {m: True for m in months}
    for a in accounts:
        cells = {}
        opened, closed = _d(a["opened_on"]), _d(a["closed_on"])
        for m in months:
            mdays = _month_days(m)
            lo = max(mdays.start, opened.toordinal()) if opened else mdays.start
            hi = min(mdays.stop - 1, closed.toordinal()) if closed else mdays.stop - 1
            if lo > hi:
                cells[m] = "inactive"
                continue
            days = range(lo, hi + 1)
            n_stmt = sum(1 for d in days if d in stmt_days[a["id"]])
            n_ok = sum(1 for d in days if d in stmt_days[a["id"]] or d in zero_days[a["id"]])
            if n_ok == len(days):
                cells[m] = "full" if n_stmt else "zero"
            else:
                cells[m] = "partial" if n_ok else "missing"
            if cells[m] not in ("full", "zero"):
                complete[m] = False
        a["cells"] = cells
        a["no_activity"] = sorted(overrides[a["id"]])
    return {"months": months, "accounts": accounts, "complete": complete}


# ---------------------------------------------------------------- income
PAYMENTS_PER_MONTH = {"monthly": 1, "semimonthly": 2, "biweekly": 26 / 12}


def income_by_month(conn, months: list[str]) -> dict[str, int]:
    """Take-home pay per calendar month (biweekly is averaged at 26 paychecks / 12 months)."""
    out = {m: 0 for m in months}
    current = date.today().strftime("%Y-%m")
    for r in conn.execute("SELECT * FROM income"):
        for m in months:
            if r["frequency"] == "once":
                if m == r["start_month"]:
                    out[m] += r["amount"]
            elif r["start_month"] <= m <= (r["end_month"] or current):
                out[m] += round(r["amount"] * PAYMENTS_PER_MONTH.get(r["frequency"], 1))
    return out


def has_income(conn) -> bool:
    return conn.execute("SELECT 1 FROM income LIMIT 1").fetchone() is not None


# ---------------------------------------------------------------- spending aggregates
def _spend(conn, include_one_off: bool, extra: str = "", params=()) -> list[dict]:
    sql = "SELECT month, parent, cat, SUM(amount) AS total FROM v_spend WHERE 1=1"
    if not include_one_off:
        sql += " AND one_off = 0"
    return rows(conn, sql + extra + " GROUP BY month, parent, cat", params)


def month_view(conn, ym: str | None, include_one_off: bool = True) -> dict:
    cov = coverage(conn)
    data = _spend(conn, include_one_off)
    by_month: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    for r in data:
        by_month[r["month"]][(r["parent"], r["cat"])] = r["total"]
    data_months = sorted(by_month)
    if not data_months:
        return {"month": None, "months": []}
    complete = cov["complete"]
    if ym is None:  # default: latest complete month, else latest month with data
        done = [m for m in data_months if complete.get(m)]
        ym = done[-1] if done else data_months[-1]

    pm = prev_month(ym)
    earlier = [m for m in data_months if m < ym]
    basis = [m for m in earlier if complete.get(m)][-6:] or earlier[-6:]

    def tree(month_list: list[str]) -> dict[tuple[str, str], float]:
        acc: dict[tuple[str, str], float] = defaultdict(float)
        for m in month_list:
            for k, v in by_month.get(m, {}).items():
                acc[k] += v
        return {k: v / max(len(month_list), 1) for k, v in acc.items()}

    cur, prev, avg = tree([ym]), tree([pm]), tree(basis)
    parents: dict[str, dict] = {}
    for (p, c) in set(cur) | set(prev) | set(avg):
        node = parents.setdefault(p, {"parent": p, "total": 0, "prev": 0, "avg": 0, "children": []})
        child = {"name": c, "total": cur.get((p, c), 0), "prev": prev.get((p, c), 0), "avg": round(avg.get((p, c), 0))}
        node["children"].append(child)
        for f in ("total", "prev", "avg"):
            node[f] += child[f]
    plist = sorted(parents.values(), key=lambda n: -max(n["total"], 0))
    for n in plist:
        n["children"].sort(key=lambda c: -c["total"])

    # Merchant lists are about card spending; fixed manual expenses are summarized separately.
    top_txns = rows(conn, """SELECT id, trans_date, merchant, description, amount, cat, account_name FROM v_spend
                             WHERE month = ? AND amount > 0 AND kind != 'manual' ORDER BY amount DESC LIMIT 8""", (ym,))
    top_merchants = rows(conn, """SELECT merchant, cat, SUM(amount) total, COUNT(*) n FROM v_spend
                                  WHERE month = ? AND kind != 'manual' GROUP BY merchant ORDER BY total DESC LIMIT 8""", (ym,))
    manual = rows(conn, """SELECT merchant, cat, SUM(amount) total FROM v_spend WHERE month = ? AND kind = 'manual'
                           GROUP BY merchant ORDER BY total DESC""", (ym,))
    return {
        "month": ym, "complete": bool(complete.get(ym)),
        "prev_month": pm, "prev_complete": bool(complete.get(pm)), "prev_has_data": pm in by_month,
        "avg_months": basis,
        "total": sum(n["total"] for n in plist), "prev_total": sum(n["prev"] for n in plist),
        "avg_total": round(sum(n["avg"] for n in plist)),
        "parents": plist, "top_transactions": top_txns, "top_merchants": top_merchants,
        "manual": manual, "manual_total": sum(m["total"] for m in manual),
        "reimbursed_total": conn.execute("SELECT COALESCE(SUM(reimbursed), 0) FROM v_spend WHERE month = ?",
                                         (ym,)).fetchone()[0],
        **_cashflow_month(conn, ym, pm),
        "months": [{"month": m, "complete": bool(complete.get(m))} for m in data_months],
    }


def _actual_spend(conn, months: list[str]) -> dict[str, int]:
    """Real spending per month (one-offs included): savings must reflect what actually left your accounts."""
    q = "SELECT month, SUM(amount) t FROM v_spend WHERE month IN (%s) GROUP BY month" % ",".join("?" * len(months))
    got = {r["month"]: r["t"] for r in conn.execute(q, months)}
    return {m: got.get(m, 0) or 0 for m in months}


def _cashflow_month(conn, ym: str, pm: str) -> dict:
    if not has_income(conn):
        return {"income": None}
    inc, sp = income_by_month(conn, [ym, pm]), _actual_spend(conn, [ym, pm])
    return {"income": inc[ym], "actual_spent": sp[ym], "saved": inc[ym] - sp[ym],
            "prev_income": inc[pm], "prev_saved": inc[pm] - sp[pm]}


def _cashflow_year(conn, span: list[str]) -> dict:
    if not has_income(conn):
        return {"income": None}
    inc, sp = income_by_month(conn, span), _actual_spend(conn, span)
    total, spent = sum(inc.values()), sum(sp.values())
    return {"income": total, "actual_spent": spent, "saved": total - spent,
            "monthly_cashflow": [{"month": m, "income": inc[m], "spent": sp[m], "saved": inc[m] - sp[m]} for m in span]}

def trends(conn, include_one_off: bool = True, parent: str | None = None) -> dict:
    cov = coverage(conn)
    extra, params = ("", ())
    if parent:
        extra, params = " AND parent = ?", (parent,)
    data = _spend(conn, include_one_off, extra, params)
    key = "cat" if parent else "parent"
    series_tot: dict[str, int] = defaultdict(int)
    by_month: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in data:
        by_month[r["month"]][r[key]] += r["total"]
        series_tot[r[key]] += r["total"]
    months = sorted(set(by_month) | set(cov["months"]))
    if months:
        months = month_range(months[0], months[-1])
    return {
        "series": sorted(series_tot, key=lambda s: -series_tot[s]),
        "months": [{"month": m, "complete": bool(cov["complete"].get(m)),
                    "total": sum(by_month[m].values()), "values": dict(by_month[m])} for m in months],
    }


def yearly(conn, include_one_off: bool = True) -> dict:
    cov = coverage(conn)
    data = _spend(conn, include_one_off)
    years: dict[str, dict] = {}
    month_parent: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in data:
        month_parent[r["month"]][r["parent"]] += r["total"]
    for m, parents in month_parent.items():
        y = years.setdefault(m[:4], {"year": m[:4], "total": 0, "by_parent": defaultdict(int),
                                     "months_with_data": set(), "complete_months": 0})
        y["months_with_data"].add(m)
        for p, v in parents.items():
            y["total"] += v
            y["by_parent"][p] += v
    for y in years.values():
        y["complete_months"] = sum(1 for m in y["months_with_data"] if cov["complete"].get(m))
        y["months_with_data"] = len(y["months_with_data"])
        y["avg_per_month"] = round(y["total"] / max(y["months_with_data"], 1))
        y["by_parent"] = dict(y["by_parent"])

    # Year-to-date comparison: same calendar months across years, cut at the latest year's last data month.
    ytd = None
    if years:
        latest = max(years)
        last_mm = max(int(m[5:7]) for m in month_parent if m.startswith(latest))
        ytd = {"through_month": last_mm, "years": {}}
        for y in sorted(years):
            tot, bp = 0, defaultdict(int)
            for mm in range(1, last_mm + 1):
                for p, v in month_parent.get(f"{y}-{mm:02d}", {}).items():
                    tot += v
                    bp[p] += v
            ytd["years"][y] = {"total": tot, "by_parent": dict(bp)}
    return {"years": [years[y] for y in sorted(years)], "ytd": ytd}


def year_view(conn, year: str | None, include_one_off: bool = True) -> dict:
    """Monthly-view equivalent for a whole year (to date): category tree, comparison against the same
    calendar months of the prior year, monthly average, per-month totals, top merchants and purchases."""
    cov = coverage(conn)
    data = _spend(conn, include_one_off)
    by_month: dict[str, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for r in data:
        by_month[r["month"]][(r["parent"], r["cat"])] += r["total"]
    years = sorted({m[:4] for m in by_month})
    if not years:
        return {"year": None, "years": []}
    if year not in years:
        year = years[-1]
    months = sorted(m for m in by_month if m.startswith(year))
    through = int(months[-1][5:7])
    span = [f"{year}-{mm:02d}" for mm in range(int(months[0][5:7]), through + 1)]
    prior = str(int(year) - 1)
    prior_span = [f"{prior}-{m[5:7]}" for m in span]
    prev_has_data = any(m in by_month for m in prior_span)

    def tree(month_list: list[str]) -> dict[tuple[str, str], int]:
        acc: dict[tuple[str, str], int] = defaultdict(int)
        for m in month_list:
            for k, v in by_month.get(m, {}).items():
                acc[k] += v
        return acc

    cur, prev = tree(span), tree(prior_span)
    n = max(len(span), 1)
    parents: dict[str, dict] = {}
    for (p, c) in set(cur) | set(prev):
        node = parents.setdefault(p, {"parent": p, "total": 0, "prev": 0, "avg": 0, "children": []})
        child = {"name": c, "total": cur.get((p, c), 0), "prev": prev.get((p, c), 0), "avg": round(cur.get((p, c), 0) / n)}
        node["children"].append(child)
        for f in ("total", "prev", "avg"):
            node[f] += child[f]
    plist = sorted(parents.values(), key=lambda x: -max(x["total"], 0))
    for x in plist:
        x["children"].sort(key=lambda c: -c["total"])

    lo, hi = f"{span[0]}-01", f"{span[-1]}-31"
    one_off = "" if include_one_off else " AND one_off = 0"
    top_txns = rows(conn, f"""SELECT id, trans_date, merchant, amount, cat, account_name FROM v_spend
                              WHERE trans_date BETWEEN ? AND ? AND amount > 0 AND kind != 'manual'{one_off}
                              ORDER BY amount DESC LIMIT 10""", (lo, hi))
    top_merchants = rows(conn, f"""SELECT merchant, cat, SUM(amount) total, COUNT(*) n FROM v_spend
                                   WHERE trans_date BETWEEN ? AND ? AND kind != 'manual'{one_off}
                                   GROUP BY merchant ORDER BY total DESC LIMIT 10""", (lo, hi))
    manual_total = conn.execute(f"SELECT COALESCE(SUM(amount),0) FROM v_spend WHERE trans_date BETWEEN ? AND ? AND kind='manual'",
                                (lo, hi)).fetchone()[0]
    reimbursed = conn.execute("SELECT COALESCE(SUM(reimbursed),0) FROM v_spend WHERE trans_date BETWEEN ? AND ?",
                              (lo, hi)).fetchone()[0]
    one_offs = conn.execute("SELECT COALESCE(SUM(amount),0) FROM v_spend WHERE trans_date BETWEEN ? AND ? AND one_off = 1",
                            (lo, hi)).fetchone()[0]
    total = sum(x["total"] for x in plist)
    return {
        "year": year, "years": years, "months": span, "prior": prior, "prev_has_data": prev_has_data,
        "incomplete_months": [m for m in span if not cov["complete"].get(m)],
        "monthly": [{"month": m, "total": sum(by_month.get(m, {}).values()), "complete": bool(cov["complete"].get(m))} for m in span],
        "total": total, "prev_total": sum(x["prev"] for x in plist), "avg_per_month": round(total / n),
        "manual_total": manual_total, "reimbursed_total": reimbursed, "one_off_total": one_offs if include_one_off else 0,
        "parents": plist, "top_transactions": top_txns, "top_merchants": top_merchants,
        **_cashflow_year(conn, span),
    }


# ---------------------------------------------------------------- yearly subscriptions
_YEARLY_CATS = {"Streaming & Subscriptions", "Insurance", "Auto Insurance", "Gym & Fitness", "Internet & Cable", "Phone"}
_YEARLY_KW = re.compile(r"ANNUAL|MEMBERSHIP|RENEW|YEARLY|VEHREG|VEH REG|REGISTRATION|DUES|LICEN[CS]E|SUBSCRIPTION", re.I)


def yearly_subscriptions(conn) -> list[dict]:
    """Charges that recur once a year: easy to forget because they only show up annually.
    confirmed = charged ~12 months apart at a similar amount; likely = one charge in the last year that looks like
    a subscription, insurance policy, registration or card annual fee. The user can confirm (yearly=1) or dismiss (0)."""
    today = date.today()
    txns = rows(conn, """SELECT v.merchant, v.merchant_key, v.cat, v.kind, v.trans_date, v.amount, v.description,
                                v.account_name, m.yearly
                         FROM v_spend v LEFT JOIN merchants m ON m.key = v.merchant_key
                         WHERE v.kind IN ('purchase','fee') AND v.tag IS NULL AND v.amount >= 500
                         ORDER BY v.trans_date""")
    by: dict[str, list[dict]] = defaultdict(list)
    for t in txns:
        by[t["merchant"]].append(t)
    out = []
    for name, items in by.items():
        verdict = next((i["yearly"] for i in items if i["yearly"] is not None), None)
        if verdict == 0:
            continue
        dates = [date.fromisoformat(i["trans_date"]) for i in items]
        last, last_d = items[-1], dates[-1]
        recent = [d for d in dates if (today - d).days <= 365]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        confirmed = any(335 <= g <= 395 and abs(items[k + 1]["amount"] - items[k]["amount"]) <= 0.25 * items[k]["amount"]
                        for k, g in enumerate(gaps))
        monthly = len(recent) >= 3 or any(g < 300 for g in gaps[-2:])
        reason = None
        if confirmed and not monthly:
            reason = "Charged about 12 months apart"
        elif verdict == 1:
            reason = "Marked yearly by you"
        elif len(recent) == 1 and not monthly:
            if last["kind"] == "fee" and "ANNUAL" in last["description"].upper():
                reason = "Card annual fee"
            elif _YEARLY_KW.search(last["description"]):
                reason = "Looks like an annual renewal"
            elif last["cat"] in _YEARLY_CATS:
                reason = f"One {last['cat'].lower()} charge in the last year"
        if not reason:
            continue
        try:
            nxt = last_d.replace(year=last_d.year + 1)
        except ValueError:  # Feb 29
            nxt = last_d + timedelta(days=365)
        days = (nxt - today).days
        out.append({
            "merchant": name, "merchant_key": last["merchant_key"], "category": last["cat"], "account": last["account_name"],
            "amount": last["amount"], "last_date": last["trans_date"], "next_date": nxt.isoformat(), "days_until": days,
            "status": "confirmed" if confirmed or verdict == 1 else "likely", "reason": reason,
            "renewal": "overdue" if days < -30 else "soon" if days <= 60 else "later",
        })
    out.sort(key=lambda x: x["days_until"])
    return out


# ---------------------------------------------------------------- insights
def insights(conn) -> dict:
    latest_row = conn.execute("SELECT MAX(trans_date) FROM transactions WHERE kind != 'manual'").fetchone()[0]
    if not latest_row:
        return {"recurring": [], "anomalies": [], "duplicates": [], "new_merchants": [], "fees": [], "top_merchants": []}
    latest = date.fromisoformat(latest_row)

    purchases = rows(conn, """SELECT id, merchant, merchant_key, account_id, account_name, trans_date, amount, cat, parent
                               FROM v_spend WHERE kind = 'purchase' ORDER BY merchant, trans_date""")
    by_merchant: dict[str, list[dict]] = defaultdict(list)
    for p in purchases:
        by_merchant[p["merchant"]].append(p)

    # Recurring charges: >=3 charges in distinct months, regular interval, consistent amount.
    # Also catch brand-new subscriptions early: exactly 2 same-price charges ~a month apart, the latest recent.
    recurring = []
    for name, items in by_merchant.items():
        recent = items[-12:]
        n_months = len({i["trans_date"][:7] for i in recent})
        dates = sorted({date.fromisoformat(i["trans_date"]) for i in recent})
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        if not gaps:
            continue
        amounts = [i["amount"] for i in recent]
        med = median(amounts)
        is_new = False
        if n_months == 2:
            if not (len(recent) == 2 and 25 <= gaps[0] <= 35 and abs(amounts[1] - amounts[0]) <= 0.05 * amounts[0]
                    and (latest - dates[-1]).days <= 45):
                continue
            is_new = True
        elif n_months < 3:
            continue
        g = median(gaps)
        period = "monthly" if 25 <= g <= 35 else "yearly" if 350 <= g <= 380 else "weekly" if 6 <= g <= 8 else None
        if not period:
            continue
        if sum(1 for a in amounts if abs(a - med) <= max(0.15 * med, 200)) < 0.6 * len(amounts):  # tolerate plan upgrades
            continue
        # Ignore one-off purchases at the same merchant (e.g. buying a device from the same company that bills a small monthly subscription).
        sub = [i for i in recent if abs(i["amount"] - med) <= max(0.25 * med, 200)]
        last = sub[-1]
        dates = sorted({date.fromisoformat(i["trans_date"]) for i in sub})
        # Most recent price change in the past year (e.g. Netflix $15.49 -> $17.99).
        change, change_date = 0, None
        for a, b in zip(items, items[1:]):
            if abs(b["amount"] - a["amount"]) >= max(50, 0.02 * a["amount"]) and \
                    (latest - date.fromisoformat(b["trans_date"])).days <= 365:
                change, change_date = b["amount"] - a["amount"], b["trans_date"]
        if period != "yearly" and change and abs(change) > 0.5 * med:
            change, change_date = 0, None  # a one-off odd charge, not a price change
        cur = last["amount"] if abs(last["amount"] - med) <= 0.25 * med else med
        recurring.append({
            "merchant": name, "category": last["cat"], "period": period, "count": len(items),
            "typical_amount": round(med), "last_amount": last["amount"], "last_date": last["trans_date"],
            "price_change": change, "price_change_date": change_date,
            # Cost at the CURRENT price (e.g. after a price increase), unless the last charge was an odd one.
            "monthly_cost": round(cur * 30.44 / g), "annual_cost": round(cur * 365.25 / g),
            "active": (latest - dates[-1]).days <= g * 1.5 + 5,
            "account": last["account_name"],
            "first_date": items[0]["trans_date"],
            # "new": only 2 charges so far, or first seen within ~4 months of the latest data: did you mean to sign up?
            "is_new": is_new or (latest - date.fromisoformat(items[0]["trans_date"])).days <= 120,
            "fixed_price": all(abs(a - med) <= 0.05 * med for a in amounts),
        })
    recurring.sort(key=lambda r: (not r["active"], -r["monthly_cost"]))

    # Unusually large charges for a merchant you visit regularly.
    anomalies = []
    for name, items in by_merchant.items():
        if len(items) < 4:
            continue
        for i, it in enumerate(items):
            others = [x["amount"] for j, x in enumerate(items) if j != i]
            med = median(others)
            if it["amount"] > 2.5 * med and it["amount"] - med > 5000:
                anomalies.append({**it, "reason": f"{it['amount'] / med:.1f}x your usual at this merchant",
                                  "typical": round(med)})
    # Biggest single purchases in the last 90 days.
    cutoff = (latest - timedelta(days=90)).isoformat()
    big = sorted((p for p in purchases if p["trans_date"] >= cutoff), key=lambda p: -p["amount"])[:5]
    for b in big:
        if b["amount"] >= 25000 and not any(a["id"] == b["id"] for a in anomalies):
            anomalies.append({**b, "reason": "Large purchase (last 90 days)", "typical": None})
    anomalies.sort(key=lambda a: a["trans_date"], reverse=True)

    # Possible duplicate charges: same card, merchant and amount on the same day, $5+.
    duplicates = []
    by_key: dict[tuple, list[dict]] = defaultdict(list)
    for p in purchases:
        by_key[(p["account_id"], p["merchant_key"], p["amount"])].append(p)
    for items in by_key.values():
        items.sort(key=lambda x: x["trans_date"])
        for a, b in zip(items, items[1:]):
            if a["trans_date"] == b["trans_date"] and a["amount"] >= 500:  # same card, merchant, amount and day; ignore tiny repeats (transit taps)
                duplicates.append({"merchant": a["merchant"], "amount": a["amount"], "dates": [a["trans_date"], b["trans_date"]],
                                   "account": a["account_name"], "ids": [a["id"], b["id"]]})

    # New merchants in the most recent 30 days of data.
    first_seen = {name: items[0] for name, items in by_merchant.items()}
    new_cut = (latest - timedelta(days=30)).isoformat()
    new_merchants = sorted(
        ({"merchant": n, "first_date": f["trans_date"], "amount": f["amount"], "category": f["cat"]}
         for n, f in first_seen.items() if f["trans_date"] >= new_cut and len(first_seen) > 0),
        key=lambda x: -x["amount"])
    if len({p["trans_date"][:7] for p in purchases}) < 3:
        new_merchants = []  # meaningless until there's some history

    fees = rows(conn, """SELECT month, SUM(CASE WHEN kind='interest' THEN amount ELSE 0 END) interest,
                                SUM(CASE WHEN kind='fee' OR description LIKE '%FOREIGN TRANSACTION%' THEN amount ELSE 0 END) fees
                         FROM v_txn WHERE kind IN ('fee','interest') OR description LIKE '%FOREIGN TRANSACTION%'
                         GROUP BY month ORDER BY month""")
    year_ago = (latest - timedelta(days=365)).isoformat()
    top_merchants = rows(conn, """SELECT merchant, cat, SUM(amount) total, COUNT(*) n FROM v_spend
                                  WHERE trans_date > ? AND kind != 'manual' GROUP BY merchant ORDER BY total DESC LIMIT 15""",
                         (year_ago,))
    return {"recurring": recurring, "anomalies": anomalies[:30], "duplicates": duplicates,
            "new_merchants": new_merchants[:20], "fees": fees, "top_merchants": top_merchants,
            "latest_date": latest_row, "annual_renewals": yearly_subscriptions(conn)}
