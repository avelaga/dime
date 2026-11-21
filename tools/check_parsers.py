"""Run the parsers over local PDFs and print a PRIVACY-SAFE report: no names, no account digits,
descriptions masked with the same rules as redact_skeleton. Safe to share.

Usage: .venv/bin/python tools/check_parsers.py [folder]   (add --show to list masked transactions)
"""

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.parsers import ParseError, parse_pdf  # noqa: E402
from redact_skeleton import mask_text  # noqa: E402


def dollars(c: int) -> str:
    return f"{c / 100:,.2f}"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    show = "--show" in sys.argv
    root = Path(args[0] if args else ROOT).resolve()
    pdfs = sorted(p for p in root.rglob("*.pdf") if ".venv" not in p.parts and "node_modules" not in p.parts)
    for n, pdf in enumerate(pdfs, 1):
        print(f"--- statement {n}")
        try:
            st = parse_pdf(pdf)
        except ParseError as e:
            print(f"  PARSE ERROR: {e}")
            continue
        kinds = Counter(t.kind for t in st.transactions)
        by_kind = Counter()
        for t in st.transactions:
            by_kind[t.kind] += t.amount
        diff = st.reconciliation_diff
        print(f"  issuer={st.issuer} last4_found={st.last4 is not None} period={st.period_start}..{st.period_end}")
        print(f"  prev={dollars(st.previous_balance)} new={dollars(st.new_balance)} txns={len(st.transactions)} {dict(kinds)}")
        print(f"  summary={ {k: dollars(v) for k, v in st.summary.items()} }")
        print(f"  parsed_by_kind={ {k: dollars(v) for k, v in by_kind.items()} }")
        print(f"  RECONCILED={'YES' if diff == 0 else 'NO'} diff={dollars(diff)}")
        dates_ok = all(st.period_start.toordinal() - 40 <= t.trans_date.toordinal() <= st.period_end.toordinal() + 1
                       for t in st.transactions)
        print(f"  dates_within_period={dates_ok}")
        if show or diff:
            for t in st.transactions:
                print(f"    {t.trans_date} {t.kind:9} {dollars(t.amount):>10}  {mask_text(t.description)}")


if __name__ == "__main__":
    main()
