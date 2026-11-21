"""Entry point: detect the issuer of a statement PDF and parse it."""

import pdfplumber

from .common import ParsedStatement, ParseError, Txn
from .issuers import parse_bofa, parse_chase, parse_citi

ISSUERS = {"chase": "Chase", "citi": "Citi", "bofa": "Bank of America"}


def _visible(obj) -> bool:
    # Some statements (older Citi) overlay invisible ~0.2pt text on top of real text, which
    # interleaves with it during extraction. Drop characters too small to be visible.
    return obj.get("object_type") != "char" or obj.get("size", 10) >= 2


def extract_text(path, layout: bool = False, visible_only: bool = False) -> str:
    with pdfplumber.open(path) as pdf:
        # dedupe_chars fixes bold headings that render every glyph twice (Chase).
        return "\n".join(((p.filter(_visible) if visible_only else p).dedupe_chars().extract_text(layout=layout) or "")
                         for p in pdf.pages)


def detect_issuer(text: str) -> str:
    low = text.lower()
    if "chase.com" in low or "cardmember service" in low and "chase" in low:
        return "chase"
    if "citi.com" in low or "citi cards" in low:
        return "citi"
    if "bank of america" in low:
        return "bofa"
    raise ParseError("Unrecognized statement: expected Chase, Citi, or Bank of America")


def parse_pdf(path) -> ParsedStatement:
    text = extract_text(path)
    if len(text.strip()) < 200:
        raise ParseError("PDF has no text layer (scanned image?)")
    issuer = detect_issuer(text)
    if issuer == "citi":
        st = parse_citi(text, extract_text(path, visible_only=True))
    else:
        st = {"chase": parse_chase, "bofa": parse_bofa}[issuer](text)
    st.transactions = [t for t in st.transactions if t.amount != 0]  # e.g. BofA's $0.00 interest lines
    return st


__all__ = ["parse_pdf", "ParsedStatement", "ParseError", "Txn", "ISSUERS"]
