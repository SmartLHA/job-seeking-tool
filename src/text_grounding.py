from __future__ import annotations

import re
import unicodedata


def normalize_grounding_text(text: str) -> str:
    folded = unicodedata.normalize("NFKC", str(text)).casefold()
    folded = folded.translate(str.maketrans({
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00a0": " ",
    }))
    return re.sub(r"\s+", " ", folded).strip()


def quote_in_text(quote: str, source_text: str) -> bool:
    normalized_quote = normalize_grounding_text(quote)
    if not normalized_quote:
        return False
    return normalized_quote in normalize_grounding_text(source_text)
