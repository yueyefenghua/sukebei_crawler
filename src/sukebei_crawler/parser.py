from __future__ import annotations

import json
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import TorrentItem
from .product_code import extract_product_code_parts
from .size import parse_size_to_bytes


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_listing(
    html_text: str,
    *,
    base_url: str,
    source_url: str,
    site: str,
    search_query: str | None,
    query_params: dict,
) -> tuple[list[TorrentItem], str | None]:
    soup = BeautifulSoup(html_text, "html.parser")
    rows = soup.select("table.torrent-list tbody tr")

    items: list[TorrentItem] = []
    for row in rows:
        item = row_to_item(
            row,
            base_url=base_url,
            source_url=source_url,
            site=site,
            search_query=search_query,
            query_params=query_params,
        )
        if item is not None:
            items.append(item)

    next_link = soup.select_one("ul.pagination li.next a[href]")
    next_url = urljoin(base_url, next_link["href"]) if next_link else None
    return items, next_url


def row_to_item(
    row: Tag,
    *,
    base_url: str,
    source_url: str,
    site: str,
    search_query: str | None,
    query_params: dict,
) -> TorrentItem | None:
    cells = row.find_all("td", recursive=False)
    if len(cells) < 8:
        return None

    category = extract_category(cells[0])
    name_link = cells[1].select_one('a[href^="/view/"]')
    if name_link is None:
        return None

    detail_href = name_link.get("href")
    title = str(name_link.get("title") or name_link.get_text(" ", strip=True)).strip()
    if not title or not detail_href:
        return None

    torrent_link = cells[2].select_one('a[href$=".torrent"]')
    torrent_url = urljoin(base_url, torrent_link["href"]) if torrent_link else None

    size_text = cell_text(cells[3]) or None
    product_parts = extract_product_code_parts(title)
    return TorrentItem(
        site=site,
        title=title,
        product_code=product_parts.code if product_parts else None,
        product_prefix=product_parts.prefix if product_parts else None,
        product_number=product_parts.number if product_parts else None,
        detail_url=urljoin(base_url, str(detail_href)),
        torrent_url=torrent_url,
        category=category,
        size_text=size_text,
        size_bytes=parse_size_to_bytes(size_text),
        published_at=cell_text(cells[4]) or None,
        seeders=parse_int(cell_text(cells[5])),
        leechers=parse_int(cell_text(cells[6])),
        completed_downloads=parse_int(cell_text(cells[7])),
        search_query=search_query,
        query_params_json=json.dumps(query_params, ensure_ascii=False, sort_keys=True),
        source_url=source_url,
    )


def extract_category(cell: Tag) -> str | None:
    link = cell.find("a")
    if isinstance(link, Tag):
        title = link.get("title")
        if title:
            return str(title)
    return cell_text(cell) or None


def cell_text(cell: Tag) -> str:
    return cell.get_text(" ", strip=True)
