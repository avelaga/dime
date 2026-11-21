"""Turn statement PDFs into masked layout skeletons, safe to share for parser development.

Masking rules:
  - Every digit becomes 9            (11/04/2026 -> 99/99/9999, $1,234.56 -> $9,999.99)
  - Every word NOT on a short list of standard statement terms is masked letter by letter,
    keeping only its case pattern     (JOHN SMITH -> XXXX XXXXX, Starbucks -> Xxxxxxxxx)
  - Punctuation and spacing are kept, because column positions, $, -, *, /
    are what the parsers need.

Output goes to redacted/skeleton_N.txt. Original filenames are never written out
(they can contain account digits). Review the files yourself before sharing them.

Usage:  .venv/bin/python tools/redact_skeleton.py [folder_with_pdfs]
"""

import re
import sys
from pathlib import Path

import pdfplumber

# Standard statement vocabulary only. Deliberately excludes anything that could be part of a
# name, street, or city (no "Park", "Main", "Center", state names, etc.).
ALLOWED_WORDS = {
    # issuers / networks / card products
    "chase", "citi", "citibank", "citicards", "bank", "america", "visa", "mastercard",
    "freedom", "sapphire", "unlimited", "flex", "preferred", "reserve", "ink", "slate",
    "double", "premier", "custom", "customized", "rewards", "cash", "travel", "costco",
    "amazon", "prime", "signature", "platinum", "world", "elite",
    # structure / sections
    "account", "accounts", "summary", "activity", "detail", "details", "information",
    "statement", "statements", "page", "of", "continued", "section", "important", "notice",
    "notices", "news", "messages", "message", "your", "you", "we", "our", "us",
    "transaction", "transactions", "trans", "post", "posting", "posted", "date", "dates",
    "description", "merchant", "name", "amount", "amounts", "reference", "ref", "number",
    "category", "type", "location", "card", "cards", "ending", "in", "member", "since",
    "cardmember", "cardholder", "primary", "authorized", "user", "users", "holder",
    # money terms
    "payment", "payments", "purchase", "purchases", "credit", "credits", "debit", "debits",
    "fee", "fees", "interest", "charge", "charges", "charged", "balance", "balances",
    "previous", "new", "transfer", "transfers", "advance", "advances", "adjustment",
    "adjustments", "return", "returns", "refund", "refunds", "other", "total", "totals",
    "minimum", "due", "past", "late", "limit", "available", "line", "opening", "closing",
    "open", "close", "closed", "billing", "cycle", "period", "days", "day", "year", "to",
    "date", "ytd", "foreign", "exchange", "rate", "rates", "currency", "annual", "apr",
    "percentage", "variable", "fixed", "standard", "promotional", "promo", "subject",
    "expires", "expiration", "points", "point", "earned", "redeemed", "redeem", "bonus",
    "base", "miles", "back", "dollars", "dollar", "plan", "plans", "installment",
    "autopay", "automatic", "pay", "paid", "thank", "online", "electronic", "check",
    "mobile", "app", "phone", "service", "customer", "contact", "mail", "send",
    "warning", "if", "make", "only", "the", "and", "or", "an", "for", "on", "at",
    "by", "from", "with", "this", "that", "is", "are", "be", "not", "no", "per",
    "as", "it", "all", "each", "more", "less", "than", "up", "end", "begin", "beginning",
    "earned", "estimated", "time", "times", "months", "month", "years", "would", "save",
    "savings", "pending", "net", "gross", "tax", "taxes", "usd", "com", "www", "http",
    "https", "inc", "llc", "cr", "dr",
    # dates
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov",
    "dec", "january", "february", "march", "april", "june", "july", "august", "september",
    "october", "november", "december", "mon", "tue", "wed", "thu", "fri", "sat", "sun",
}

WORD_RE = re.compile(r"[A-Za-z]+")


def mask_word(match: re.Match) -> str:
    word = match.group(0)
    if word.lower() in ALLOWED_WORDS:
        return word
    return "".join("X" if c.isupper() else "x" for c in word)


def mask_text(text: str) -> str:
    text = re.sub(r"\d", "9", text)
    text = WORD_RE.sub(mask_word, text)
    # Mask any non-ASCII letters (accented names, etc.)
    return "".join(c if c.isascii() or not c.isalpha() else "x" for c in text)


def skeletonize(pdf_path: Path) -> tuple[str, int, list[int]]:
    out, char_counts = [], []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            raw = page.extract_text(layout=True) or ""
            char_counts.append(len(page.chars))
            lines = [ln.rstrip() for ln in mask_text(raw).splitlines()]
            body = "\n".join(ln for ln in lines if ln.strip())
            out.append(f"===== PAGE {i} (width={page.width:.0f}, chars={len(page.chars)}) =====\n{body}")
        return "\n\n".join(out) + "\n", len(pdf.pages), char_counts


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    pdfs = sorted(p for p in root.rglob("*.pdf") if ".venv" not in p.parts and "redacted" not in p.parts)
    if not pdfs:
        print("No PDFs found.")
        return
    out_dir = Path(__file__).resolve().parent.parent / "redacted"
    out_dir.mkdir(exist_ok=True)
    for n, pdf in enumerate(pdfs, start=1):
        text, pages, counts = skeletonize(pdf)
        target = out_dir / f"skeleton_{n}.txt"
        target.write_text(text)
        scanned = [i + 1 for i, c in enumerate(counts) if c == 0]
        note = f"  WARNING: pages {scanned} have no text layer (scanned image?)" if scanned else ""
        # Filename shown on YOUR terminal only so you know which is which; not written to the output.
        print(f"{pdf.name}  ->  redacted/{target.name}  ({pages} pages){note}")
    print("\nReview the files in redacted/ before sharing. Anything personal left unmasked? Tell me which word.")


if __name__ == "__main__":
    main()
