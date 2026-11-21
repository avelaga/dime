"""Merchant categorization with a local Ollama model (falls back to keyword rules).

Only merchant keys are sent to the model: normalized descriptions with every token containing a
digit already stripped (see categories.merchant_key). No account numbers or names leave this module.
"""

import json
import os
import threading
import urllib.request

from . import db
from .categories import LLM_CATEGORIES, keyword_category

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "qwen3.6:35b")
BATCH = 40

status = {"running": False, "done": 0, "total": 0, "error": None, "model": MODEL, "mode": None}
_lock = threading.Lock()

PROMPT = """You categorize US credit card transactions. For each merchant string, return:
- "merchant": a short, clean, human-readable merchant name (e.g. "SQ BLUE BOTTLE COFFEE OAKLAND" -> "Blue Bottle Coffee", "AMZN MKTP US" -> "Amazon").
  Drop city names, store numbers and processor prefixes. Use the same name for the same business.
- "category": exactly one category from this list:
{categories}

Guidance: Costco/Target/Walmart -> General Merchandise (unless clearly gas). Amazon -> Online Shopping.
App stores and software subscriptions -> Streaming & Subscriptions. Unknown local businesses: make your best guess
from the name; use "Uncategorized" only if there is truly no signal.

Return JSON: {{"results": [{{"i": <index>, "merchant": "...", "category": "..."}}]}} with one entry per input.

Inputs:
{inputs}"""


def ollama_available() -> bool:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=2) as r:
            models = [m["name"] for m in json.load(r).get("models", [])]
        return MODEL in models
    except Exception:
        return False


def _ask(keys: list[str]) -> dict[str, tuple[str, str]]:
    schema = {
        "type": "object",
        "properties": {"results": {"type": "array", "items": {
            "type": "object",
            "properties": {"i": {"type": "integer"}, "merchant": {"type": "string"},
                           "category": {"type": "string", "enum": LLM_CATEGORIES}},
            "required": ["i", "merchant", "category"]}}},
        "required": ["results"],
    }
    body = {
        "model": MODEL, "stream": False, "think": False, "format": schema,
        "options": {"temperature": 0},
        "messages": [{"role": "user", "content": PROMPT.format(
            categories="\n".join(f"- {c}" for c in LLM_CATEGORIES),
            inputs="\n".join(f"{i}. {k}" for i, k in enumerate(keys)))}],
    }
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        content = json.load(r)["message"]["content"]
    out = {}
    for item in json.loads(content).get("results", []):
        i = item.get("i")
        if isinstance(i, int) and 0 <= i < len(keys):
            cat = item.get("category") if item.get("category") in LLM_CATEGORIES else "Uncategorized"
            out[keys[i]] = ((item.get("merchant") or keys[i]).strip()[:80], cat)
    return out


def _run() -> None:
    try:
        use_llm = ollama_available()
        status.update(total=0, done=0, error=None, mode="llm" if use_llm else "keyword")
        # Loop until nothing is pending: uploads that land mid-run get picked up too.
        seen: set[str] = set()
        while True:
            with db.tx() as conn:
                keys = [r["key"] for r in conn.execute(
                    "SELECT key FROM merchants WHERE source = 'pending' OR (source = 'keyword' AND ?) ORDER BY key",
                    (int(use_llm),)) if r["key"] not in seen]
            if not keys:
                break
            seen.update(keys)
            status["total"] += len(keys)
            _categorize(keys, use_llm)
    except Exception as e:
        status["error"] = str(e)
    finally:
        status["running"] = False


def _categorize(keys: list[str], use_llm: bool) -> None:
    for start in range(0, len(keys), BATCH):
        batch = keys[start:start + BATCH]
        results: dict[str, tuple[str, str, str]] = {}
        if use_llm:
            try:
                results = {k: (*v, "llm") for k, v in _ask(batch).items()}
            except Exception as e:  # keep going with keyword rules for this batch
                status["error"] = f"LLM error: {e}"
        for k in batch:
            if k not in results:
                cat = keyword_category(k)
                results[k] = (k.title(), cat or "Uncategorized", "keyword")
        with db.tx() as conn:
            for k, (name, cat, src) in results.items():
                # Never overwrite a user's manual choice.
                conn.execute("UPDATE merchants SET display_name=?, category=?, source=? "
                             "WHERE key=? AND source != 'user'", (name, cat, src, k))
        status["done"] += len(batch)


def start() -> bool:
    with _lock:
        if status["running"]:
            return False
        status["running"] = True
    threading.Thread(target=_run, daemon=True).start()
    return True
