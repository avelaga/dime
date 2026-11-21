"""FastAPI app: accounts, statement upload, transactions, analysis. Local-only (binds to 127.0.0.1)."""

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analytics, db, llm, recurring
from .categories import PARENT_OF, TAXONOMY, merchant_key
from .parsers import ISSUERS, ParseError, parse_pdf

app = FastAPI(title="Dime")
db.init()
with db.tx() as _c:
    recurring.sync(_c)


# ---------------------------------------------------------------- accounts
class AccountIn(BaseModel):
    name: str
    issuer: str
    last4s: str = ""
    opened_on: str | None = None
    closed_on: str | None = None


def _clean_last4s(s: str) -> str:
    return ",".join(sorted({p.strip() for p in s.split(",") if p.strip().isdigit() and len(p.strip()) == 4}))


@app.get("/api/accounts")
def list_accounts():
    with db.tx() as c:
        return db.rows(c, """SELECT a.*, COUNT(s.id) statements, MIN(s.period_start) first_period, MAX(s.period_end) last_period
                             FROM accounts a LEFT JOIN statements s ON s.account_id = a.id
                             WHERE a.type = 'credit_card' GROUP BY a.id ORDER BY a.issuer, a.name""")


@app.post("/api/accounts")
def create_account(a: AccountIn):
    if a.issuer not in ISSUERS:
        raise HTTPException(400, "issuer must be chase, citi or bofa")
    with db.tx() as c:
        cur = c.execute("INSERT INTO accounts(name, issuer, last4s, opened_on, closed_on) VALUES (?,?,?,?,?)",
                        (a.name.strip(), a.issuer, _clean_last4s(a.last4s), a.opened_on or None, a.closed_on or None))
        return {"id": cur.lastrowid}


@app.put("/api/accounts/{aid}")
def update_account(aid: int, a: AccountIn):
    with db.tx() as c:
        c.execute("UPDATE accounts SET name=?, issuer=?, last4s=?, opened_on=?, closed_on=? WHERE id=?",
                  (a.name.strip(), a.issuer, _clean_last4s(a.last4s), a.opened_on or None, a.closed_on or None, aid))
    return {"ok": True}


@app.delete("/api/accounts/{aid}")
def delete_account(aid: int):
    with db.tx() as c:
        c.execute("DELETE FROM accounts WHERE id=?", (aid,))
    return {"ok": True}


# ---------------------------------------------------------------- statements
def _import(c, file_hash: str, account_id: int, force: bool) -> dict:
    st = parse_pdf(db.UPLOAD_DIR / f"{file_hash}.pdf")
    acct = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not acct:
        raise HTTPException(404, "account not found")
    if acct["issuer"] != st.issuer:
        return {"status": "error", "message": f"This is a {ISSUERS[st.issuer]} statement but the account is {ISSUERS[acct['issuer']]}."}
    base = {"hash": file_hash, "issuer": st.issuer, "last4": st.last4, "account_id": account_id,
            "period_start": st.period_start.isoformat(), "period_end": st.period_end.isoformat()}
    if c.execute("SELECT 1 FROM statements WHERE account_id=? AND period_end=?", (account_id, st.period_end.isoformat())).fetchone():
        return {**base, "status": "duplicate", "message": "A statement for this card and period is already imported."}
    diff = st.reconciliation_diff
    if diff and not force:
        return {**base, "status": "unreconciled", "diff": diff,
                "message": f"Parsed transactions are off by ${diff / 100:,.2f} from the statement's balance. Not imported."}
    if st.last4 and st.last4 not in acct["last4s"].split(","):
        c.execute("UPDATE accounts SET last4s=? WHERE id=?", (_clean_last4s(f"{acct['last4s']},{st.last4}"), account_id))
    sid = c.execute("""INSERT INTO statements(account_id, period_start, period_end, previous_balance, new_balance,
                       summary, reconciled, recon_diff, file_hash) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (account_id, st.period_start.isoformat(), st.period_end.isoformat(), st.previous_balance,
                     st.new_balance, json.dumps(st.summary), int(diff == 0), diff, file_hash)).lastrowid
    for t in st.transactions:
        key = merchant_key(t.description)
        c.execute("INSERT OR IGNORE INTO merchants(key) VALUES (?)", (key,))
        c.execute("""INSERT INTO transactions(statement_id, account_id, trans_date, post_date, description, merchant_key, amount, kind)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (sid, account_id, t.trans_date.isoformat(), t.post_date.isoformat() if t.post_date else None,
                   t.description, key, t.amount, t.kind))
    return {**base, "status": "imported", "transactions": len(st.transactions), "reconciled": diff == 0}


@app.post("/api/statements/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        data = await f.read()
        h = hashlib.sha256(data).hexdigest()
        res = {"filename": f.filename, "hash": h}
        with db.tx() as c:
            if c.execute("SELECT 1 FROM statements WHERE file_hash=?", (h,)).fetchone():
                results.append({**res, "status": "duplicate", "message": "This file was already imported."})
                continue
            path = db.UPLOAD_DIR / f"{h}.pdf"
            path.write_bytes(data)
            try:
                st = parse_pdf(path)
            except ParseError as e:
                results.append({**res, "status": "error", "message": str(e)})
                continue
            info = {"issuer": st.issuer, "last4": st.last4,
                    "period_start": st.period_start.isoformat(), "period_end": st.period_end.isoformat()}
            match = [a for a in c.execute("SELECT id, last4s FROM accounts WHERE issuer=?", (st.issuer,))
                     if st.last4 and st.last4 in a["last4s"].split(",")]
            if len(match) != 1:
                results.append({**res, **info, "status": "needs_account",
                                "message": f"Which account is the {ISSUERS[st.issuer]} card ending {st.last4}?"})
                continue
            results.append({**res, **_import(c, h, match[0]["id"], force=False)})
    if any(r["status"] == "imported" for r in results):
        llm.start()
    return results


class ImportIn(BaseModel):
    hash: str
    account_id: int
    force: bool = False


@app.post("/api/statements/import")
def import_statement(body: ImportIn):
    if not (db.UPLOAD_DIR / f"{body.hash}.pdf").exists() or not body.hash.isalnum():
        raise HTTPException(404, "upload not found; please upload the file again")
    with db.tx() as c:
        res = _import(c, body.hash, body.account_id, body.force)
    if res["status"] == "imported":
        llm.start()
    return res


@app.get("/api/statements")
def list_statements():
    with db.tx() as c:
        return db.rows(c, """SELECT s.id, s.account_id, a.name account_name, a.issuer, s.period_start, s.period_end,
                                    s.previous_balance, s.new_balance, s.reconciled, s.recon_diff, s.uploaded_at,
                                    (SELECT COUNT(*) FROM transactions t WHERE t.statement_id = s.id) transactions
                             FROM statements s JOIN accounts a ON a.id = s.account_id ORDER BY s.period_end DESC, a.name""")


@app.delete("/api/statements/{sid}")
def delete_statement(sid: int):
    with db.tx() as c:
        c.execute("DELETE FROM statements WHERE id=?", (sid,))
    return {"ok": True}


# ---------------------------------------------------------------- transactions & merchants
@app.get("/api/transactions")
def list_transactions(month: str | None = None, parent: str | None = None, category: str | None = None,
                      q: str | None = None, account_id: int | None = None, year: str | None = None,
                      merchant: str | None = None, date_from: str | None = None, date_to: str | None = None,
                      reimbursed: bool | None = None, tag: str | None = None):
    sql = """SELECT v.id, v.trans_date, v.merchant, v.merchant_key, v.description, v.amount, v.gross_amount,
                    v.reimbursed, v.kind, v.cat, v.tag,
                    COALESCE(c.parent, 'Uncategorized') parent, v.account_id, v.account_name, v.one_off,
                    v.category IS NOT NULL AS overridden, m.source category_source
             FROM v_txn v LEFT JOIN categories c ON c.name = v.cat LEFT JOIN merchants m ON m.key = v.merchant_key WHERE 1=1"""
    p: list = []
    if reimbursed is not None:
        sql += " AND v.reimbursed > 0" if reimbursed else " AND v.reimbursed = 0"
    for cond, val in (("v.month = ?", month), ("c.parent = ?", parent), ("v.cat = ?", category),
                      ("v.account_id = ?", account_id), ("substr(v.month,1,4) = ?", year), ("v.merchant = ?", merchant),
                      ("v.trans_date >= ?", date_from), ("v.trans_date <= ?", date_to), ("v.tag = ?", tag)):
        if val is not None:
            sql += f" AND {cond}"
            p.append(val)
    if q:
        sql += " AND (v.description LIKE ? OR v.merchant LIKE ?)"
        p += [f"%{q}%", f"%{q}%"]
    with db.tx() as c:
        return db.rows(c, sql + " ORDER BY v.trans_date DESC, v.id DESC LIMIT 3000", p)


class TxnPatch(BaseModel):
    category: str | None = None
    one_off: bool | None = None
    apply_to_merchant: bool = False
    reimbursed: int | None = None  # cents; clamped to 0..charge amount


class ReimburseIn(BaseModel):
    ids: list[int]
    full: bool  # True = mark each as fully reimbursed, False = clear


class TagIn(BaseModel):
    ids: list[int]
    tag: str | None  # None/"" = remove from its trip (and clear one-off)


@app.post("/api/transactions/tag")
def bulk_tag(body: TagIn):
    """Group charges into a trip/event. Tagged charges are one-off: excluded from trends on request."""
    tag = (body.tag or "").strip() or None
    with db.tx() as c:
        c.executemany("UPDATE transactions SET tag = ?, one_off = ? WHERE id = ? AND kind != 'payment'",
                      [(tag, int(tag is not None), i) for i in body.ids])
    return {"ok": True, "count": len(body.ids)}


@app.get("/api/tags")
def list_tags():
    with db.tx() as c:
        tags = db.rows(c, """SELECT tag, COUNT(*) n, SUM(amount) total, SUM(reimbursed) reimbursed,
                                    MIN(trans_date) first, MAX(trans_date) last
                             FROM v_spend WHERE tag IS NOT NULL GROUP BY tag ORDER BY first DESC""")
        for t in tags:
            t["by_category"] = db.rows(c, """SELECT parent, cat, SUM(amount) total FROM v_spend WHERE tag = ?
                                             GROUP BY parent, cat ORDER BY total DESC""", (t["tag"],))
        return tags


@app.post("/api/transactions/reimburse")
def bulk_reimburse(body: ReimburseIn):
    with db.tx() as c:
        for tid in body.ids:
            c.execute("UPDATE transactions SET reimbursed = CASE WHEN ? THEN MAX(amount, 0) ELSE 0 END "
                      "WHERE id = ? AND kind IN ('purchase','cash_advance')", (int(body.full), tid))
    return {"ok": True, "count": len(body.ids)}


@app.patch("/api/transactions/{tid}")
def patch_transaction(tid: int, body: TxnPatch):
    sent = body.model_fields_set
    if "category" in sent and body.category is not None and body.category not in PARENT_OF:
        raise HTTPException(400, "unknown category")
    with db.tx() as c:
        row = c.execute("SELECT merchant_key FROM transactions WHERE id=?", (tid,)).fetchone()
        if not row:
            raise HTTPException(404)
        if "category" in sent:
            if body.apply_to_merchant and body.category:
                # "Always categorize this merchant as X" — applies to all past and future transactions.
                c.execute("UPDATE merchants SET category=?, source='user' WHERE key=?", (body.category, row["merchant_key"]))
                c.execute("""UPDATE transactions SET category=NULL WHERE merchant_key=?
                             AND kind NOT IN ('payment','reward','fee','interest','manual')""", (row["merchant_key"],))
            else:
                c.execute("UPDATE transactions SET category=? WHERE id=?", (body.category, tid))
        if body.one_off is not None:
            c.execute("UPDATE transactions SET one_off=? WHERE id=?", (int(body.one_off), tid))
        if body.reimbursed is not None:
            c.execute("UPDATE transactions SET reimbursed = MAX(0, MIN(?, amount)) WHERE id=? AND amount > 0",
                      (body.reimbursed, tid))
    return {"ok": True}


class MerchantPatch(BaseModel):
    display_name: str | None = None
    category: str | None = None
    yearly: bool | None = None  # confirm (True) / dismiss (False) an annual-renewal suggestion


@app.patch("/api/merchants/{key:path}")
def patch_merchant(key: str, body: MerchantPatch):
    with db.tx() as c:
        if body.yearly is not None:
            # Applies to every key that shares this display name (merchants can span several raw descriptors).
            name = c.execute("SELECT COALESCE(display_name, key) FROM merchants WHERE key=?", (key,)).fetchone()
            c.execute("UPDATE merchants SET yearly=? WHERE key=? OR display_name=?",
                      (int(body.yearly), key, name[0] if name else key))
        if body.display_name:
            c.execute("UPDATE merchants SET display_name=?, source='user' WHERE key=?", (body.display_name.strip(), key))
        if body.category:
            if body.category not in PARENT_OF:
                raise HTTPException(400, "unknown category")
            c.execute("UPDATE merchants SET category=?, source='user' WHERE key=?", (body.category, key))
    return {"ok": True}


@app.get("/api/categories")
def categories():
    return [{"parent": p, "children": kids} for p, kids in TAXONOMY.items()]


@app.post("/api/categorize")
def categorize(reset: bool = False):
    if reset:  # re-run the model on everything it categorized (keeps your manual choices)
        with db.tx() as c:
            c.execute("UPDATE merchants SET source='pending' WHERE source IN ('llm','keyword')")
    return {"started": llm.start()}


@app.get("/api/categorize/status")
def categorize_status():
    with db.tx() as c:
        pending = c.execute("SELECT COUNT(*) FROM merchants WHERE source='pending'").fetchone()[0]
    return {**llm.status, "pending": pending, "llm_available": llm.ollama_available()}


# ---------------------------------------------------------------- coverage: confirmed no-activity months
class NoActivityIn(BaseModel):
    account_id: int
    month: str  # YYYY-MM
    on: bool


@app.post("/api/no-activity")
def set_no_activity(body: NoActivityIn):
    with db.tx() as c:
        if body.on:
            c.execute("INSERT OR IGNORE INTO no_activity(account_id, month) VALUES (?,?)", (body.account_id, body.month[:7]))
        else:
            c.execute("DELETE FROM no_activity WHERE account_id=? AND month=?", (body.account_id, body.month[:7]))
    return {"ok": True}


# ---------------------------------------------------------------- recurring manual expenses
class RecurringIn(BaseModel):
    name: str
    category: str
    amount: int  # cents
    frequency: str = "monthly"
    day_of_month: int = 1
    start_month: str  # YYYY-MM
    end_month: str | None = None


def _check_recurring(r: RecurringIn) -> tuple:
    if r.category not in PARENT_OF:
        raise HTTPException(400, "unknown category")
    if r.frequency not in recurring.STEP:
        raise HTTPException(400, "frequency must be monthly, quarterly or yearly")
    if r.amount <= 0 or not r.name.strip():
        raise HTTPException(400, "name and a positive amount are required")
    return (r.name.strip(), r.category, r.amount, r.frequency, max(1, min(31, r.day_of_month)),
            r.start_month[:7], (r.end_month or "")[:7] or None)


# ---------------------------------------------------------------- income (take-home pay)
class IncomeIn(BaseModel):
    name: str
    amount: int  # cents per payment
    frequency: str = "monthly"  # monthly | semimonthly | biweekly | once
    start_month: str
    end_month: str | None = None


def _check_income(r: IncomeIn) -> tuple:
    if r.frequency not in ("monthly", "semimonthly", "biweekly", "once"):
        raise HTTPException(400, "frequency must be monthly, semimonthly, biweekly or once")
    if r.amount <= 0 or not r.name.strip():
        raise HTTPException(400, "name and a positive amount are required")
    return (r.name.strip(), r.amount, r.frequency, r.start_month[:7], (r.end_month or "")[:7] or None)


@app.get("/api/income")
def list_income():
    with db.tx() as c:
        return db.rows(c, "SELECT * FROM income ORDER BY start_month DESC, amount DESC")


@app.post("/api/income")
def create_income(r: IncomeIn):
    with db.tx() as c:
        return {"id": c.execute("INSERT INTO income(name, amount, frequency, start_month, end_month) VALUES (?,?,?,?,?)",
                                _check_income(r)).lastrowid}


@app.put("/api/income/{iid}")
def update_income(iid: int, r: IncomeIn):
    with db.tx() as c:
        c.execute("UPDATE income SET name=?, amount=?, frequency=?, start_month=?, end_month=? WHERE id=?", (*_check_income(r), iid))
    return {"ok": True}


@app.delete("/api/income/{iid}")
def delete_income(iid: int):
    with db.tx() as c:
        c.execute("DELETE FROM income WHERE id=?", (iid,))
    return {"ok": True}


@app.get("/api/recurring")
def list_recurring():
    with db.tx() as c:
        return db.rows(c, "SELECT * FROM recurring ORDER BY amount DESC")


@app.post("/api/recurring")
def create_recurring(r: RecurringIn):
    vals = _check_recurring(r)
    with db.tx() as c:
        rid = c.execute("""INSERT INTO recurring(name, category, amount, frequency, day_of_month, start_month, end_month)
                           VALUES (?,?,?,?,?,?,?)""", vals).lastrowid
        recurring.sync(c, rid)
    return {"id": rid}


@app.put("/api/recurring/{rid}")
def update_recurring(rid: int, r: RecurringIn):
    vals = _check_recurring(r)
    with db.tx() as c:
        c.execute("""UPDATE recurring SET name=?, category=?, amount=?, frequency=?, day_of_month=?, start_month=?, end_month=?
                     WHERE id=?""", (*vals, rid))
        recurring.sync(c, rid)
    return {"ok": True}


@app.delete("/api/recurring/{rid}")
def delete_recurring(rid: int):
    with db.tx() as c:
        recurring.delete(c, rid)
    return {"ok": True}


# ---------------------------------------------------------------- analysis
@app.get("/api/coverage")
def get_coverage():
    with db.tx() as c:
        return analytics.coverage(c)


@app.get("/api/month")
def get_month(month: str | None = None, one_off: bool = True):
    with db.tx() as c:
        recurring.sync_if_stale(c)
        return analytics.month_view(c, month, one_off)


@app.get("/api/year")
def get_year(year: str | None = None, one_off: bool = True):
    with db.tx() as c:
        recurring.sync_if_stale(c)
        return analytics.year_view(c, year, one_off)


@app.get("/api/trends")
def get_trends(one_off: bool = True, parent: str | None = None):
    with db.tx() as c:
        recurring.sync_if_stale(c)
        return analytics.trends(c, one_off, parent)


@app.get("/api/yearly")
def get_yearly(one_off: bool = True):
    with db.tx() as c:
        recurring.sync_if_stale(c)
        return analytics.yearly(c, one_off)


@app.get("/api/insights")
def get_insights():
    with db.tx() as c:
        recurring.sync_if_stale(c)
        return analytics.insights(c)


# ---------------------------------------------------------------- built frontend (production mode)
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        # Real files from the build (logo, favicons); everything else is the single-page app.
        f = (DIST / path).resolve()
        if path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
