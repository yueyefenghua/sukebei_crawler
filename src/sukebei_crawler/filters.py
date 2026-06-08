from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import TorrentItem
from .size import parse_size_to_bytes


TZ = ZoneInfo("Asia/Shanghai")


def item_matches(item: TorrentItem | dict, conditions: dict) -> bool:
    getter = item.get if isinstance(item, dict) else lambda key, default=None: getattr(item, key, default)

    min_completed = conditions.get("min_completed_downloads")
    completed = getter("completed_downloads")
    if min_completed is not None:
        if completed is None or int(completed) < int(min_completed):
            return False

    min_seeders = conditions.get("min_seeders")
    seeders = getter("seeders")
    if min_seeders is not None:
        if seeders is None or int(seeders) < int(min_seeders):
            return False

    if conditions.get("only_not_downloaded"):
        if getter("download_status") == "downloaded" or getter("downloaded_at"):
            return False

    min_size = parse_size_to_bytes(conditions.get("min_size")) if conditions.get("min_size") else None
    max_size = parse_size_to_bytes(conditions.get("max_size")) if conditions.get("max_size") else None
    size_bytes = getter("size_bytes")
    if min_size is not None and (size_bytes is None or int(size_bytes) < min_size):
        return False
    if max_size is not None and (size_bytes is None or int(size_bytes) > max_size):
        return False

    max_age_days = conditions.get("max_age_days")
    if max_age_days is not None:
        published_at = parse_published_at(str(getter("published_at", "") or ""))
        if published_at is None:
            return False
        if published_at < datetime.now(TZ) - timedelta(days=int(max_age_days)):
            return False

    product_prefix = str(getter("product_prefix", "") or "").upper()
    product_code = str(getter("product_code", "") or "").upper()
    code_include = [str(value).upper() for value in conditions.get("product_code_include", [])]
    code_exclude = [str(value).upper() for value in conditions.get("product_code_exclude", [])]
    prefix_include = [str(value).upper() for value in conditions.get("product_prefix_include", [])]
    prefix_exclude = [str(value).upper() for value in conditions.get("product_prefix_exclude", [])]
    if code_include and product_code not in code_include:
        return False
    if code_exclude and product_code in code_exclude:
        return False
    if prefix_include and product_prefix not in prefix_include:
        return False
    if prefix_exclude and product_prefix in prefix_exclude:
        return False

    title = str(getter("title", "") or "").lower()
    includes = [str(value).lower() for value in conditions.get("title_include", [])]
    excludes = [str(value).lower() for value in conditions.get("title_exclude", [])]
    if includes and not all(value in title for value in includes):
        return False
    if excludes and any(value in title for value in excludes):
        return False

    return True


def parse_published_at(value: str) -> datetime | None:
    value = value.strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TZ)
    return parsed
