from __future__ import annotations

from .models import TorrentItem
from .size import parse_size_to_bytes


def item_matches(item: TorrentItem | dict, conditions: dict) -> bool:
    getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)

    min_completed = conditions.get("min_completed_downloads")
    completed = getter("completed_downloads")
    if min_completed is not None:
        if completed is None or int(completed) < int(min_completed):
            return False

    min_size = parse_size_to_bytes(conditions.get("min_size")) if conditions.get("min_size") else None
    max_size = parse_size_to_bytes(conditions.get("max_size")) if conditions.get("max_size") else None
    size_bytes = getter("size_bytes")
    if min_size is not None and (size_bytes is None or int(size_bytes) < min_size):
        return False
    if max_size is not None and (size_bytes is None or int(size_bytes) > max_size):
        return False

    title = str(getter("title", "") or "").lower()
    includes = [str(value).lower() for value in conditions.get("title_include", [])]
    excludes = [str(value).lower() for value in conditions.get("title_exclude", [])]
    if includes and not all(value in title for value in includes):
        return False
    if excludes and any(value in title for value in excludes):
        return False

    return True
