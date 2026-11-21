"""SQLite storage. Amounts are integer cents; dates are ISO strings."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .categories import TAXONOMY

DATA_DIR = Path(os.environ.get("FINANCE_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DB_PATH = DATA_DIR / "finance.db"
UPLOAD_DIR = DATA_DIR / "uploads"

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts(
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  issuer TEXT NOT NULL,                 -- chase | citi | bofa
  last4s TEXT NOT NULL DEFAULT '',      -- comma separated (card replacements); stored locally only
  type TEXT NOT NULL DEFAULT 'credit_card',
  opened_on TEXT, closed_on TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS statements(
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  period_start TEXT NOT NULL, period_end TEXT NOT NULL,
  previous_balance INTEGER NOT NULL, new_balance INTEGER NOT NULL,
  summary TEXT, reconciled INTEGER NOT NULL, recon_diff INTEGER NOT NULL,
  file_hash TEXT NOT NULL UNIQUE,
  uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(account_id, period_end));
CREATE TABLE IF NOT EXISTS recurring(        -- fixed expenses paid outside the cards (mortgage, insurance…)
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, category TEXT NOT NULL, amount INTEGER NOT NULL,
  frequency TEXT NOT NULL DEFAULT 'monthly',  -- monthly | quarterly | yearly
  day_of_month INTEGER NOT NULL DEFAULT 1,
  start_month TEXT NOT NULL, end_month TEXT);  -- YYYY-MM, end inclusive (NULL = ongoing)
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  statement_id INTEGER REFERENCES statements(id) ON DELETE CASCADE,   -- NULL for manual entries
  recurring_id INTEGER REFERENCES recurring(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  trans_date TEXT NOT NULL, post_date TEXT,
  description TEXT NOT NULL, merchant_key TEXT NOT NULL,
  amount INTEGER NOT NULL, kind TEXT NOT NULL,
  category TEXT,                         -- per-transaction override (NULL = use merchant rule)
  one_off INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS income(            -- take-home pay (after tax), entered manually
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL, amount INTEGER NOT NULL,      -- cents per payment
  frequency TEXT NOT NULL DEFAULT 'monthly',        -- monthly | semimonthly | biweekly | once
  start_month TEXT NOT NULL, end_month TEXT);       -- YYYY-MM, end inclusive (NULL = ongoing); 'once' = start_month only
CREATE TABLE IF NOT EXISTS no_activity(       -- "no statement was issued: $0 that month" (user-confirmed)
  account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  month TEXT NOT NULL,
  PRIMARY KEY(account_id, month));
CREATE INDEX IF NOT EXISTS ix_txn_date ON transactions(trans_date);
CREATE INDEX IF NOT EXISTS ix_txn_key ON transactions(merchant_key);
CREATE TABLE IF NOT EXISTS merchants(
  key TEXT PRIMARY KEY,
  display_name TEXT,
  category TEXT,
  source TEXT NOT NULL DEFAULT 'pending'); -- pending | llm | keyword | user
CREATE TABLE IF NOT EXISTS categories(name TEXT PRIMARY KEY, parent TEXT NOT NULL, ord INTEGER);
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);   -- small user preferences (FIRE assumptions…)
CREATE TABLE IF NOT EXISTS fire_balances(     -- invested-assets snapshots for FIRE tracking (401k, IRA, brokerage…)
  month TEXT PRIMARY KEY,                     -- YYYY-MM
  amount INTEGER NOT NULL);                   -- cents
"""

# Columns added after the first release: (table, column, definition).
MIGRATIONS = [
    ("transactions", "reimbursed", "INTEGER NOT NULL DEFAULT 0"),  # cents paid back to you (work expenses etc.)
    ("transactions", "tag", "TEXT"),  # trip / event name grouping one-off spending, e.g. "Summer trip"
    ("merchants", "yearly", "INTEGER"),  # user verdict on "is this a yearly subscription": 1 yes, 0 no, NULL auto
]

# `amount` in the views is NET of reimbursements, so every analysis counts only what you actually paid.
VIEWS = """
DROP VIEW IF EXISTS v_txn;
CREATE VIEW v_txn AS
SELECT t.id, t.statement_id, t.recurring_id, t.account_id, t.trans_date, t.post_date, t.description,
  t.merchant_key, t.amount - t.reimbursed AS amount, t.amount AS gross_amount, t.reimbursed,
  t.kind, t.category, t.one_off, t.tag, a.name AS account_name,
  substr(t.trans_date, 1, 7) AS month,
  COALESCE(m.display_name, t.merchant_key) AS merchant,
  COALESCE(t.category,
           CASE t.kind WHEN 'payment' THEN 'Credit Card Payment'
                       WHEN 'reward' THEN 'Rewards Redemption'
                       WHEN 'interest' THEN 'Interest Charged'
                       WHEN 'fee' THEN 'Card Fees' END,
           m.category, 'Uncategorized') AS cat
FROM transactions t
JOIN accounts a ON a.id = t.account_id
LEFT JOIN merchants m ON m.key = t.merchant_key;
DROP VIEW IF EXISTS v_spend;
CREATE VIEW v_spend AS
SELECT v.*, COALESCE(c.parent, 'Uncategorized') AS parent
FROM v_txn v LEFT JOIN categories c ON c.name = v.cat
WHERE COALESCE(c.parent, '') != 'Transfers';
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        for table, col, ddl in MIGRATIONS:
            if col not in {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
        conn.executescript(VIEWS)
        conn.execute("DELETE FROM categories")
        conn.executemany("INSERT INTO categories(name, parent, ord) VALUES (?,?,?)",
                         [(c, p, i) for i, (p, kids) in enumerate(TAXONOMY.items()) for c in kids])


@contextmanager
def tx():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def rows(conn, sql: str, params=()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]
