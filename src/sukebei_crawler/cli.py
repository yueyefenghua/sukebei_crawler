from __future__ import annotations

import argparse
import csv
import json
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
            for job in cfg.raw.get("search_jobs") or []:
                job.setdefault("filters", {})["q"] = args.q

        if cfg.search_query == "":
            print("warning: default query.filters.q is empty; crawling without a keyword filter")

        if args.command == "crawl":
            return cmd_crawl(cfg)
        if args.command == "list":
            return cmd_list(cfg, args=args)
        if args.command == "download":
            return cmd_download(cfg, yes=args.yes, limit=args.limit)
        if args.command == "export":
            return cmd_export(cfg, args=args)
        if args.command == "runs":
            return cmd_runs(cfg, limit=args.limit)
        if args.command == "serve":
            from .server import serve

            return serve(cfg, host=args.host, port=args.port)
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
    add_filter_args(list_cmd)
    list_cmd.add_argument("--sort", choices=["downloads", "seeders", "size", "date", "id"], default="downloads")

    download = subparsers.add_parser("download", help="Preview or download matching .torrent files.")
    download.add_argument("--yes", action="store_true", help="Actually download files. Without this, preview only.")
    download.add_argument("--limit", type=int, default=50, help="Maximum candidate rows to process.")

    export = subparsers.add_parser("export", help="Export matching saved items.")
    export.add_argument("--format", choices=["csv", "json"], default="csv")
    export.add_argument("--output", help="Output path. Defaults to stdout.")
    export.add_argument("--limit", type=int, default=0, help="Maximum rows to export. 0 means no limit.")
    add_filter_args(export)
    export.add_argument("--sort", choices=["downloads", "seeders", "size", "date", "id"], default="downloads")

    runs = subparsers.add_parser("runs", help="Show recent crawl runs.")
    runs.add_argument("--limit", type=int, default=20)

    serve = subparsers.add_parser("serve", help="Start a local read-only web dashboard with manual torrent download.")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    return parser


def add_filter_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prefix", help="Filter by product prefix, for example VNDS.")
    parser.add_argument("--code", help="Filter by full product code, for example VNDS-3440.")
    parser.add_argument("--not-downloaded", action="store_true", help="Only show items not marked downloaded.")
    parser.add_argument("--min-seeders", type=int, help="Minimum seeders.")


def build_search_url(cfg: AppConfig, filters: dict) -> str:
    params = {key: value for key, value in filters.items() if value is not None}
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

    total_parsed = 0
    total_inserted = 0
    total_updated = 0
    matching = 0
    pages_requested = 0

    try:
        for job_index, job in enumerate(cfg.search_jobs):
            polite_sleep(float(crawl["request_delay_seconds"]), float(crawl["request_jitter_seconds"]))
            result = crawl_job(cfg, storage, client, job)
            pages_requested += result["pages_requested"]
            total_parsed += result["parsed"]
            total_inserted += result["inserted"]
            total_updated += result["updated"]
            matching += result["matching"]
    finally:
        client.close()
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


def crawl_job(cfg: AppConfig, storage: Storage, client: HttpClient, job: dict) -> dict[str, int]:
    crawl = cfg.raw["crawl"]
    filters = dict(job["filters"])
    job_name = str(job["name"])
    search_query = str(filters.get("q", "") or "")
    current_url: str | None = build_search_url(cfg, filters)
    previous_url: str | None = None
    run_id = storage.start_crawl_run(job_name, json.dumps(filters, ensure_ascii=False, sort_keys=True))

    parsed = 0
    inserted_total = 0
    updated_total = 0
    matching = 0
    pages_requested = 0
    error: str | None = None

    try:
        for page_num in range(1, int(crawl["max_pages"]) + 1):
            if current_url is None:
                break
            if page_num > 1:
                polite_sleep(float(crawl["request_delay_seconds"]), float(crawl["request_jitter_seconds"]))

            print(f"fetching job={job_name} page={page_num}: {current_url}")
            response = client.get(current_url, referer=previous_url)
            pages_requested += 1
            items, next_url = parse_listing(
                response.text,
                base_url=cfg.base_url,
                source_url=current_url,
                site=cfg.base_url,
                search_query=search_query,
                query_params=filters,
            )
            if not items:
                print(f"warning: parsed 0 items from {current_url}")
                break
            inserted, updated = storage.upsert_items(items)
            parsed += len(items)
            inserted_total += inserted
            updated_total += updated
            matching += sum(1 for item in items if item_matches(item, cfg.raw["conditions"]))
            previous_url = current_url
            current_url = next_url
    except Exception as exc:
        error = str(exc)
        raise
    finally:
        storage.finish_crawl_run(
            run_id,
            pages_requested=pages_requested,
            parsed_count=parsed,
            inserted_count=inserted_total,
            updated_count=updated_total,
            matching_count=matching,
            error=error,
        )

    return {
        "pages_requested": pages_requested,
        "parsed": parsed,
        "inserted": inserted_total,
        "updated": updated_total,
        "matching": matching,
    }


def cmd_list(cfg: AppConfig, *, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        conditions = conditions_with_overrides(cfg.raw["conditions"], args)
        items = sorted_items([item for item in storage.all_items() if item_matches(item, conditions)], args.sort)
    finally:
        storage.close()

    for item in items[: args.limit]:
        print(format_item(item))
    print_summary({"matching": len(items), "shown": min(len(items), args.limit)})
    return 0


def conditions_with_overrides(base: dict, args: argparse.Namespace) -> dict:
    conditions = dict(base)
    if getattr(args, "prefix", None):
        conditions["product_prefix_include"] = [args.prefix]
    if getattr(args, "code", None):
        conditions["product_code_include"] = [args.code]
    if getattr(args, "not_downloaded", False):
        conditions["only_not_downloaded"] = True
    if getattr(args, "min_seeders", None) is not None:
        conditions["min_seeders"] = args.min_seeders
    return conditions


def sorted_items(items: list[dict], sort_key: str) -> list[dict]:
    key_map = {
        "downloads": "completed_downloads",
        "seeders": "seeders",
        "size": "size_bytes",
        "date": "published_at",
        "id": "id",
    }
    key = key_map[sort_key]
    return sorted(items, key=lambda item: item.get(key) or 0, reverse=True)


def cmd_export(cfg: AppConfig, *, args: argparse.Namespace) -> int:
    storage = Storage(cfg.db_path)
    try:
        conditions = conditions_with_overrides(cfg.raw["conditions"], args)
        items = sorted_items([item for item in storage.all_items() if item_matches(item, conditions)], args.sort)
        if args.limit:
            items = items[: args.limit]
    finally:
        storage.close()

    fields = [
        "id",
        "product_code",
        "product_prefix",
        "product_number",
        "completed_downloads",
        "seeders",
        "leechers",
        "size_text",
        "published_at",
        "download_status",
        "title",
        "detail_url",
        "torrent_url",
    ]
    output = Path(args.output) if args.output else None
    if args.format == "json":
        content = json.dumps(items, ensure_ascii=False, indent=2)
        if output:
            output.write_text(content + "\n", encoding="utf-8")
        else:
            print(content)
        return 0

    if output:
        with output.open("w", newline="", encoding="utf-8") as handle:
            write_csv(handle, fields, items)
    else:
        write_csv(sys.stdout, fields, items)
    return 0


def write_csv(handle, fields: list[str], items: list[dict]) -> None:
    writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        writer.writerow(item)


def cmd_runs(cfg: AppConfig, *, limit: int) -> int:
    storage = Storage(cfg.db_path)
    try:
        runs = storage.recent_runs(limit=limit)
    finally:
        storage.close()
    for run in runs:
        print(
            f"[{run['id']}] job={run['job_name']} pages={run['pages_requested']} "
            f"parsed={run['parsed_count']} inserted={run['inserted_count']} updated={run['updated_count']} "
            f"matching={run['matching_count']} error={run['error'] or '-'}"
        )
    print_summary({"shown": len(runs)})
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
        try:
            success, failed = download_items(
                items=candidates,
                storage=storage,
                client=client,
                output_dir=Path(download_cfg["output_dir"]),
                delay_seconds=float(download_cfg["request_delay_seconds"]),
                jitter_seconds=float(download_cfg["request_jitter_seconds"]),
                overwrite_existing=bool(download_cfg["overwrite_existing"]),
            )
        finally:
            client.close()
        print_summary({"download_success": success, "download_failed": failed})
        return 0 if failed == 0 else 1
    finally:
        storage.close()


def format_item(item: dict) -> str:
    completed = item.get("completed_downloads")
    size = item.get("size_text") or "-"
    seeders = item.get("seeders")
    product_code = item.get("product_code") or "-"
    product_prefix = item.get("product_prefix") or "-"
    return f"[{item['id']}] code={product_code} prefix={product_prefix} completed={completed} seeders={seeders} size={size} title={item['title']}"


def print_summary(values: dict[str, int]) -> None:
    print("summary:")
    for key, value in values.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    raise SystemExit(main())
