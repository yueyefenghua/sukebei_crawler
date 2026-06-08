from __future__ import annotations

import re


PRODUCT_CODE_RE = re.compile(r"\b([A-Z0-9]{2,10}(?:-[A-Z0-9]{2,10})?-\d{2,8})\b", re.IGNORECASE)


def extract_product_code(title: str | None) -> str | None:
    if not title:
        return None
    match = PRODUCT_CODE_RE.search(title)
    if not match:
        return None
    return match.group(1).upper()
