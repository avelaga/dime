"""Bulk-import statement folders into the local database.

Each sub-folder is one card: the first word is the issuer (chase | citi | bofa), the rest is your nickname,
e.g. "chase travel card/". Cards are created if missing; every PDF inside is imported (already-imported
files are skipped). Output is privacy-safe: no names, account numbers or descriptions.

  .venv/bin/python tools/import_folders.py [root] [--confirm-no-activity YEAR]

--confirm-no-activity YEAR: you're asserting that every statement for YEAR is present, so any month in YEAR
without a statement (before each card's latest statement) had no activity. Those card-months are marked
"no activity ($0)" so they count as complete. The newest month per card is left alone: its statement may just
not be issued yet.
"""

import hashlib
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import analytics, db, llm  # noqa: E402
from app.main import _import  # noqa: E402  (also initializes the DB)
from app.parsers import ISSUERS, ParseError, parse_pdf  # noqa: E402

ALIASES = {"bofa": "bofa", "boa": "bofa", "bankofamerica": "bofa", "chase": "chase", "citi": "citi", "citibank": "citi"}
SKIP = {".venv", "node_modules", "frontend", "backend", "data", "tools", "redacted", ".git"}


def main() -> None:
    args = sys.argv[1:]
    year = None
    if "--confirm-no-activity" in args:
        i = args.index("--confirm-no-activity")
        year = args[i + 1]
        del args[i:i + 2]
    root = Path(args[0] if args else ROOT).resolve()

    for folder in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in SKIP and not p.name.startswith(".")):
        pdfs = sorted(folder.glob("*.pdf")) + sorted(folder.glob("*.PDF"))
        if not pdfs:
            continue
        first, *rest = folder.name.split()
        issuer = ALIASES.get(first.lower())
        if not issuer or not rest:
            print(f"skip '{folder.name}': first word must be chase, citi or bofa, followed by a nickname")
            continue
        name = " ".join(w.capitalize() for w in rest)
        with db.tx() as c:
            row = c.execute("SELECT id FROM accounts WHERE issuer=? AND lower(name)=lower(?)", (issuer, name)).fetchone()
            aid = row["id"] if row else c.execute(
                "INSERT INTO accounts(name, issuer) VALUES (?,?)", (name, issuer)).lastrowid
        counts: dict[str, int] = {}
        for pdf in pdfs:
            data = pdf.read_bytes()
            h = hashlib.sha256(data).hexdigest()
            dest = db.UPLOAD_DIR / f"{h}.pdf"
            if not dest.exists():
                shutil.copyfile(pdf, dest)
            with db.tx() as c:
                if c.execute("SELECT 1 FROM statements WHERE file_hash=?", (h,)).fetchone():
                    status = "already imported"
                else:
                    try:
                        st = parse_pdf(dest)
                        if st.issuer != issuer:
                            status = f"wrong issuer ({ISSUERS[st.issuer]})"
                        else:
                            status = _import(c, h, aid, force=False)["status"]
                    except ParseError as e:
                        status = f"error: {e}"
            counts[status] = counts.get(status, 0) + 1
        print(f"{ISSUERS[issuer]:16} {name:24} {counts}")

    if year:
        with db.tx() as c:
            cov = analytics.coverage(c)
            marked = 0
            for a in cov["accounts"]:
                last = c.execute("SELECT MAX(period_end) FROM statements WHERE account_id=?", (a["id"],)).fetchone()[0]
                if not last:
                    continue
                for m, state in a["cells"].items():
                    if m.startswith(year) and m < last[:7] and state in ("missing", "partial"):
                        c.execute("INSERT OR IGNORE INTO no_activity(account_id, month) VALUES (?,?)", (a["id"], m))
                        marked += 1
        print(f"marked {marked} card-month(s) in {year} as no activity ($0, no statement issued)")

    print("categorizing merchants with the local model…", flush=True)
    llm.start()
    time.sleep(0.5)
    while llm.status["running"]:
        time.sleep(1)
    print(f"done: {llm.status['done']} merchants ({llm.status['mode']}){' error: ' + llm.status['error'] if llm.status['error'] else ''}")


if __name__ == "__main__":
    main()
