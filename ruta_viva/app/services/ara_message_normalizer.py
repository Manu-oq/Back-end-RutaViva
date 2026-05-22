from __future__ import annotations

import re
import unicodedata

from app.core.ara_constants import TYPO_REPLACEMENTS


def normalize_message(message: str) -> str:
    normalized = message.lower().strip()
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFD", normalized)
        if unicodedata.category(character) != "Mn"
    )
    normalized = re.sub(r"\s+", " ", normalized)
    for typo, replacement in TYPO_REPLACEMENTS.items():
        normalized = re.sub(rf"\b{re.escape(typo)}\b", replacement, normalized)
    return normalized
