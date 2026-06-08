from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlencode

from .config import AppConfig, ConfigError, load_config
from .downloader import download_items
from .filters import item_matches
from .http_client import BLOCK_STATUS, BlockedStatus, HttpClient, polite_sleep
from .parser import parse_listing
from .storage import Storage


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        cfg = load_config(args.config)
        if getattr(args, "q", None) is not None:
            cfg.raw["query"].setdefault("filters", {})["q"] = args.q

        if cfg.search_query == "":
            print("warning: query.filters.q is empty; crawling without a keyword filter")

        if args.command == "crawl":
            return cmd_crawl(cfg)
        if args.command == "list":
            return cmd_list(cfg, limit=args.limit)
        if args.command == "download":
            return cmd_download(cfg, yes=args.yes, limit=args.limit)
        parser.print_help()
        return 1
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    except BlockedStatus as exc:
        print(f"stopped: {exc}", file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sukebei-crawler")
    parser.add_argument("--config", default="config.yaml", help="Path to YAML config file.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="Crawl listing pages and save parsed items.")
    crawl.add_argument("--q", help="Override query.filters.q for this run.")

    list_cmd = subparsers.add_parser("list", help="List saved items matching configured conditions.")
    list_cmd.add_argument("--limit", type=int, default=50, help="Maximum rows to display.")

    download = subparsers.add_parser("download", help="Preview or download matching .torrent files.")
    download.add_argument("--yes", action="store_true", help="Actually download files. Without this, preview only.")
    download.add_argument("--limit", type=int, default=50, help="Maximum candidate rows to process.")

    return parser


def build_search_url(cfg: AppConfig) -> str:
    params = {key: value for key, value in cfg.filters.items() if value is not None}
    return f"{cfg.base_url}/?{urlencode(params)}"


def make_client(cfg: AppConfig, retry_count: int | None = None) -> HttpClient:
    site = cfg.raw["site"]
    crawl = cfg.raw["crawl"]
    return HttpClient(
        user_agent=str(site["user_agent"]),
        accept_language=str(site.get("accept_language", "en-US,en;q=0.9")),
        timeout_seconds=int(crawl["timeout_seconds"]),
        retry_count=int(crawl["retry_count"] if retry_count is None else retry_count),
        block_status=BLOCK_STATUS,
    )


def cmd_crawl(cfg: AppConfig) -> int:
    storage = Storage(cfg.db_path)
    client = make_client(cfg)
    crawl = cfg.raw["crawl"]
    start_url = build_search_url(cfg)
    current_url: str | None = start_url
    previous_url: str | None = None

    total_parsed = 0
    total_inserted = 0
    total_updated = 0
    matching = 0
    pages_requested = 0

    try:
        for page_num in range(1, int(crawl["max_pages"]) + 1):
            if current_url is None:
                break
            if page_num > 1:
                polite_sleep(float(crawl["request_delay_seconds"]), float(crawl["request_jitter_seconds"]))

            print(f"fetching page {page_num}: {current_url}")
            response = client.get(current_url, referer=previous_url)
            pages_requested += 1
            items, next_url = parse_listing(
                response.text,
                base_url=cfg.base_url,
                source_url=current_url,
                site=cfg.base_url,
                search_query=cfg.search_query,
                query_params=cfg.filters,
            )
            if not items:
                print(f"warning: parsed 0 items from {current_url}")
                break
            inserted, updated = storage.upsert_items(items)
            total_parsed += len(items)
            total_inserted += inserted
            total_updated += updated
            matching += sum(1 for item in items if item_matches(item, cfg.raw["conditions"]))
            previous_url = current_url
            current_url = next_url
    finally:
        storage.close()

    print_summary(
        {
            "pages_requested": pages_requested,
            "parsed": total_parsed,
            "inserted": total_inserted,
            "updated": total_updated,
            "matching_conditions": matching,
        }
    )
    return 0


def cmd_list(cfg: AppConfig, *, limit: int) -> int:
    storage = Storage(cfg.db_path)
    try:
        items = [item for item in storage.all_items() if item_matches(item, cfg.raw["conditions"])]
    finally:
        storage.close()

    for item in items[:limit]:
        print(format_item(item))
    print_summary({"matching": len(items), "shown": min(len(items), limit)})
    return 0


def cmd_download(cfg: AppConfig, *, yes: bool, limit: int) -> int:
    storage = Storage(cfg.db_path)
    try:
        candidates = [
            item
            for item in storage.download_candidates()
            if item_matches(item, cfg.raw["conditions"])
        ][:limit]
        if not candidates:
            print("no matching download candidates")
            return 0

        print("download candidates:")
        for item in candidates[:20]:
            print(format_item(item))
        if not yes:
            print("preview only. pass --yes to download .torrent files.")
            return 0

        download_cfg = cfg.raw["download"]
        client = make_client(cfg, retry_count=int(download_cfg["retry_count"]))
        success, failed = download_items(
            items=candidates,
            storage=storage,
            client=client,
            output_dir=Path(download_cfg["output_dir"]),
            delay_seconds=float(download_cfg["request_delay_seconds"]),
            jitter_seconds=float(download_cfg["request_jitter_seconds"]),
            overwrite_existing=bool(download_cfg["overwrite_existing"]),
        )
        print_summary({"download_success": success, "download_failed": failed})
        return 0 if failed == 0 else 1
    finally:
        storage.close()


def format_item(item: dict) -> str:
    completed = item.get("completed_downloads")
    size = item.get("size_text") or "-"
    seeders = item.get("seeders")
    product_code = item.get("product_code") or "-"
    return f"[{item['id']}] code={product_code} completed={completed} seeders={seeders} size={size} title={item['title']}"


def print_summary(values: dict[str, int]) -> None:
    print("summary:")
    for key, value in values.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
