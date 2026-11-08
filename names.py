"""Name normalisation for matching MPM approver names against master data."""
from __future__ import annotations

import re
import unicodedata

# Academic/professional titles dropped before matching (compared without dots). Extend here.
_TITLES = {
    "DR", "DRS", "DRA", "IR", "PROF", "H", "HJ",
    "SKOM", "ST", "SE", "SSI", "SH", "SPD",
    "MKOM", "MT", "MM", "MSI", "MBA", "MSC", "ME",
    "BSC", "PHD", "CISA", "CISSP", "PMP",
}


def normalize_name(name: str | None) -> str:
    """Upper-case, drop titles and punctuation-only separators, collapse whitespace."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name)).upper()
    tokens = [t for t in re.split(r"[\s,]+", s) if t]
    kept = [t for t in tokens if t.replace(".", "") not in _TITLES]
    return " ".join(kept)
