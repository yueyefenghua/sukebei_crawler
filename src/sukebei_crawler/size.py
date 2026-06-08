from __future__ import annotations

import re


SIZE_RE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]i?B)\s*$", re.IGNORECASE)

POWERS = {
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


def parse_size_to_bytes(value: str | None) -> int | None:
    if not value:
        return None
    match = SIZE_RE.match(value)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    return int(amount * POWERS[unit])
