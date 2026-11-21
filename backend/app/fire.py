"""FIRE (financial independence) tracking.

FI number = yearly spending in retirement / safe withdrawal rate. Everything is in today's dollars, so the
growth assumption is a *real* (after-inflation) return. Inputs come from data the app already has:

* spending: average of the last 12 complete months (with or without one-offs, user's choice), or a
  yearly override;
* retirement spending: that average minus fixed expenses with an end month (car loan, mortgage…), since
  those stop before or during retirement;
* monthly savings: current income (all active income entries, so 401(k) entries count) minus spending,
  growing by each fixed expense's amount once it ends;
* invested balance: the latest snapshot the user logged.
"""

from datetime import date

from .analytics import PAYMENTS_PER_MONTH, coverage, month_range
from .db import rows

DEFAULTS = {"return_pct": 5.0, "swr_pct": 4.0, "basis": "actual", "birth_year": None, "retire_spend": None,
            "current_spend": None}
STEP = {"monthly": 1, "quarterly": 3, "yearly": 12}
MAX_MONTHS = 12 * 60


def get_settings(conn) -> dict:
    s = dict(DEFAULTS)
    for r in conn.execute("SELECT key, value FROM settings WHERE key LIKE 'fire.%'"):
        k, v = r["key"][5:], r["value"]
        if k not in DEFAULTS:
            continue
        if v is None or v == "":
            s[k] = None
        elif k == "basis":
            s[k] = v if v in ("actual", "typical") else "actual"
        else:
            s[k] = float(v) if k.endswith("_pct") else int(v)
    return s


def save_settings(conn, values: dict) -> None:
    for k, v in values.items():
        if k in DEFAULTS:
            conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                         (f"fire.{k}", None if v is None else str(v)))


def _add_months(ym: str, n: int) -> str:
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def _project(balance: float, start: str, target: float, monthly_rate: float, savings: float,
             step_ups: list[tuple[str, float]], horizon: int | None = None) -> tuple[str | None, list[dict]]:
    """Month-by-month: grow, then add savings (+ any fixed expense that has ended). Returns (FI month, path)."""
    fi_month, path = None, []
    n = horizon or MAX_MONTHS
    for i in range(n + 1):
        m = _add_months(start, i)
        path.append({"month": m, "balance": round(balance)})
        if fi_month is None and balance >= target > 0:
            fi_month = m
            if horizon is None:
                break
        contrib = savings + sum(amt for end, amt in step_ups if end < m)
        balance = balance * (1 + monthly_rate) + contrib
    return fi_month, path


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def view(conn) -> dict:
    s = get_settings(conn)
    today = date.today().strftime("%Y-%m")

    # Spending basis: last 12 complete months.
    complete = [m for m, ok in coverage(conn)["complete"].items() if ok and m <= today][-12:]
    def avg(one_off: bool) -> float:
        if not complete:
            return 0
        q = "SELECT COALESCE(SUM(amount), 0) FROM v_spend WHERE month IN (%s)" % ",".join("?" * len(complete))
        if not one_off:
            q += " AND one_off = 0"
        return conn.execute(q, complete).fetchone()[0] / len(complete)
    spend = {"actual": avg(True), "typical": avg(False)}
    # A current-spending override (yearly) replaces the statement average for savings and retirement math.
    monthly_spend = s["current_spend"] / 12 if s["current_spend"] else spend[s["basis"]]

    # Fixed expenses still running; the ones with an end month drop out of retirement spending.
    fixed = []
    for r in rows(conn, "SELECT * FROM recurring ORDER BY amount DESC"):
        if r["start_month"] > today or (r["end_month"] and r["end_month"] < today):
            continue
        fixed.append({"name": r["name"], "category": r["category"], "end_month": r["end_month"],
                      "monthly": r["amount"] / STEP.get(r["frequency"], 1)})
    ending = [f for f in fixed if f["end_month"]]
    auto_retire = max(monthly_spend - sum(f["monthly"] for f in ending), 0)
    retire_monthly = s["retire_spend"] / 12 if s["retire_spend"] else auto_retire

    # Current monthly income (every ongoing entry active this month, 401(k) entries included).
    income = sum(r["amount"] * PAYMENTS_PER_MONTH.get(r["frequency"], 1) for r in rows(conn, "SELECT * FROM income")
                 if r["frequency"] != "once" and r["start_month"] <= today <= (r["end_month"] or today))
    savings = income - monthly_spend

    balances = rows(conn, "SELECT month, amount FROM fire_balances ORDER BY month")
    latest = balances[-1] if balances else None
    start, balance = (latest["month"], latest["amount"]) if latest else (today, 0)

    swr, ret = s["swr_pct"] / 100, s["return_pct"] / 100
    target = retire_monthly * 12 / swr if swr > 0 else 0
    rate = (1 + ret) ** (1 / 12) - 1
    step_ups = [(f["end_month"], f["monthly"]) for f in ending]

    fi_month, _ = _project(balance, start, target, rate, savings, step_ups)
    horizon = min(max(_months_between(start, fi_month) + 36 if fi_month else 240, 120), MAX_MONTHS)
    _, path = _project(balance, start, target, rate, savings, step_ups, horizon)

    def scenario(label: str, d_save=0.0, d_spend=0.0, ret_pct=None, swr_pct=None) -> dict:
        r_ = ((1 + (ret_pct if ret_pct is not None else s["return_pct"]) / 100) ** (1 / 12)) - 1
        w = (swr_pct if swr_pct is not None else s["swr_pct"]) / 100
        t = max(retire_monthly - d_spend, 0) * 12 / w
        fm, _ = _project(balance, start, t, r_, savings + d_save + d_spend, step_ups)
        return {"label": label, "fi_month": fm, "target": round(t),
                "delta_months": (_months_between(fi_month, fm) if fi_month and fm else None)}

    scenarios = [
        scenario("Save $500/mo more", d_save=50000),
        scenario("Spend $500/mo less (now and in retirement)", d_spend=50000),
        scenario(f"Returns 1 pt lower ({s['return_pct'] - 1:g}%)", ret_pct=s["return_pct"] - 1),
        scenario(f"Returns 1 pt higher ({s['return_pct'] + 1:g}%)", ret_pct=s["return_pct"] + 1),
        scenario("Safer withdrawal rate (3.5%)", swr_pct=3.5),
    ] if target > 0 else []

    return {
        "settings": s, "today": today,
        "basis_months": complete,
        "spend": {k: round(v) for k, v in spend.items()},
        "monthly_spend": round(monthly_spend), "monthly_spend_auto": round(spend[s["basis"]]),
        "fixed": [dict(f, monthly=round(f["monthly"])) for f in fixed],
        "retire_monthly": round(retire_monthly), "retire_monthly_auto": round(auto_retire),
        "income": round(income), "savings": round(savings),
        "savings_after_debts": round(savings + sum(f["monthly"] for f in ending)),
        "balances": balances, "start": start, "balance": balance,
        "target": round(target), "progress": (balance / target) if target else None,
        "fi_month": fi_month,
        "fi_age": (int(fi_month[:4]) - s["birth_year"]) if fi_month and s["birth_year"] else None,
        "path": path, "scenarios": scenarios,
    }
