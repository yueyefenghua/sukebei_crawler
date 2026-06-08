from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TorrentItem:
    site: str
    title: str
    product_code: str | None
    detail_url: str
    torrent_url: str | None
    category: str | None
    size_text: str | None
    size_bytes: int | None
    seeders: int | None
    leechers: int | None
    completed_downloads: int | None
    published_at: str | None
    search_query: str | None
    query_params_json: str
    source_url: str
