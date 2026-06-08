from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .http_client import BlockedStatus, HttpClient, polite_sleep
from .storage import Storage


INVALID_FILENAME_RE = re.compile(r"[\\/\x00-\x1f]+")


def safe_torrent_filename(item: dict) -> str:
    title = str(item.get("title") or "").strip()
    title = INVALID_FILENAME_RE.sub("_", title)
    title = title.replace("..", "_")
    title = re.sub(r"\s+", " ", title).strip(" .")
    if not title:
        title = f"item-{item['id']}"
    digest = hashlib.sha1(str(item.get("detail_url") or item["id"]).encode("utf-8")).hexdigest()[:10]
    max_title_len = 180 - len(digest) - len(".torrent") - 1
    title = title[:max_title_len].strip(" .") or f"item-{item['id']}"
    return f"{title}-{digest}.torrent"


def download_items(
    *,
    items: list[dict],
    storage: Storage,
    client: HttpClient,
    output_dir: Path,
    delay_seconds: float,
    jitter_seconds: float,
    overwrite_existing: bool,
) -> tuple[int, int]:
    success = 0
    failed = 0
    block_failures = 0

    for index, item in enumerate(items):
        if index > 0:
            polite_sleep(delay_seconds, jitter_seconds)

        item_id = int(item["id"])
        target = output_dir / safe_torrent_filename(item)
        if target.exists() and not overwrite_existing:
            storage.mark_downloaded(item_id, target)
            success += 1
            continue

        try:
            response = client.get(str(item["torrent_url"]), referer=str(item.get("detail_url") or ""))
            target.write_bytes(response.body)
            storage.mark_downloaded(item_id, target)
            success += 1
            block_failures = 0
            print(f"downloaded: {target}")
        except BlockedStatus as exc:
            failed += 1
            block_failures += 1
            storage.mark_failed(item_id, str(exc))
            print(f"blocked: item={item_id} status={exc.status}")
            if block_failures >= 2:
                print("stopping download because multiple block statuses were returned")
                break
        except Exception as exc:  # noqa: BLE001
            failed += 1
            block_failures = 0
            storage.mark_failed(item_id, str(exc))
            print(f"failed: item={item_id} error={exc}")

    return success, failed
