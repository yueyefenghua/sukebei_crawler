from __future__ import annotations

import re
from dataclasses import dataclass


PRODUCT_CODE_RE = re.compile(r"\b([A-Z0-9]{2,10}(?:-[A-Z0-9]{2,10})?-\d{2,8})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ProductCodeParts:
    code: str
    prefix: str
    number: str


def extract_product_code(title: str | None) -> str | None:
    parts = extract_product_code_parts(title)
    return parts.code if parts else None


def extract_product_code_parts(title: str | None) -> ProductCodeParts | None:
    if not title:
        return None
    match = PRODUCT_CODE_RE.search(title)
    if not match:
        return None
    code = match.group(1).upper()
    prefix, number = code.rsplit("-", 1)
    return ProductCodeParts(code=code, prefix=prefix, number=number)
