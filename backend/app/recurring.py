"""Manually entered fixed expenses paid outside the cards (mortgage, insurance, utilities).

Each recurring item is materialized into ordinary transactions (kind='manual', no statement) on a
pseudo account, one per period up to the current month, so every analysis treats them like any
other spending. Regenerated whenever an item changes and once a day as months roll over.
"""

from calendar import monthrange
from datetime import date

from .analytics import month_range

STEP = {"monthly": 1, "quarterly": 3, "yearly": 12}
_synced_on: date | None = None


def manual_account_id(conn) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE type = 'manual'").fetchone()
    if row:
        return row["id"]
    return conn.execute("INSERT INTO accounts(name, issuer, type) VALUES ('Bank (manual)', 'manual', 'manual')").lastrowid


def _materialize(conn, item, today: date, account_id: int) -> None:
    conn.execute("DELETE FROM transactions WHERE recurring_id = ?", (item["id"],))
    key = f"MANUAL:{item['id']}"
    conn.execute("""INSERT INTO merchants(key, display_name, category, source) VALUES (?,?,?, 'user')
                    ON CONFLICT(key) DO UPDATE SET display_name=excluded.display_name, category=excluded.category""",
                 (key, item["name"], item["category"]))
    current = today.strftime("%Y-%m")
    last = min(item["end_month"] or current, current)
    if item["start_month"] > last:
        return
    step = STEP.get(item["frequency"], 1)
    for i, m in enumerate(month_range(item["start_month"], last)):
        if i % step:
            continue
        y, mo = int(m[:4]), int(m[5:7])
        d = date(y, mo, min(item["day_of_month"], monthrange(y, mo)[1])).isoformat()
        conn.execute("""INSERT INTO transactions(statement_id, recurring_id, account_id, trans_date, post_date,
                        description, merchant_key, amount, kind, category) VALUES (NULL,?,?,?,?,?,?,?, 'manual', ?)""",
                     (item["id"], account_id, d, d, item["name"], key, item["amount"], item["category"]))


def sync(conn, recurring_id: int | None = None) -> None:
    global _synced_on
    today = date.today()
    acct = manual_account_id(conn)
    sql, params = "SELECT * FROM recurring", ()
    if recurring_id is not None:
        sql, params = sql + " WHERE id = ?", (recurring_id,)
    for item in conn.execute(sql, params).fetchall():
        _materialize(conn, item, today, acct)
    if recurring_id is None:
        _synced_on = today


def sync_if_stale(conn) -> None:
    """New month -> new rows. Cheap no-op otherwise."""
    if _synced_on != date.today():
        sync(conn)
        conn.commit()


def delete(conn, recurring_id: int) -> None:
    conn.execute("DELETE FROM transactions WHERE recurring_id = ?", (recurring_id,))
    conn.execute("DELETE FROM merchants WHERE key = ?", (f"MANUAL:{recurring_id}",))
    conn.execute("DELETE FROM recurring WHERE id = ?", (recurring_id,))
