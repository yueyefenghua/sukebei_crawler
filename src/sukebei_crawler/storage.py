from __future__ import annotations

import sqlite3
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import TorrentItem
from .product_code import extract_product_code_parts

TZ = ZoneInfo("Asia/Shanghai")


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.init_schema()

    def close(self) -> None:
        self.conn.close()

    def init_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              site TEXT NOT NULL,
              title TEXT NOT NULL,
              product_code TEXT,
              product_prefix TEXT,
              product_number TEXT,
              detail_url TEXT NOT NULL,
              torrent_url TEXT,
              category TEXT,
              size_text TEXT,
              size_bytes INTEGER,
              seeders INTEGER,
              leechers INTEGER,
              completed_downloads INTEGER,
              published_at TEXT,
              search_query TEXT,
              query_params_json TEXT,
              source_url TEXT,
              first_seen_at TEXT NOT NULL,
              last_seen_at TEXT NOT NULL,
              downloaded_at TEXT,
              torrent_file_path TEXT,
              download_status TEXT NOT NULL DEFAULT 'pending',
              download_error TEXT,
              UNIQUE(site, detail_url)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS crawl_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              job_name TEXT NOT NULL,
              query_params_json TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              pages_requested INTEGER NOT NULL DEFAULT 0,
              parsed_count INTEGER NOT NULL DEFAULT 0,
              inserted_count INTEGER NOT NULL DEFAULT 0,
              updated_count INTEGER NOT NULL DEFAULT 0,
              matching_count INTEGER NOT NULL DEFAULT 0,
              error TEXT
            )
            """
        )
        self.migrate_schema()
        self.backfill_product_codes()
        self.conn.commit()

    def migrate_schema(self) -> None:
        columns = {
            str(row["name"])
            for row in self.conn.execute("PRAGMA table_info(items)").fetchall()
        }
        if "product_code" not in columns:
            self.conn.execute("ALTER TABLE items ADD COLUMN product_code TEXT")
        if "product_prefix" not in columns:
            self.conn.execute("ALTER TABLE items ADD COLUMN product_prefix TEXT")
        if "product_number" not in columns:
            self.conn.execute("ALTER TABLE items ADD COLUMN product_number TEXT")

    def upsert_items(self, items: list[TorrentItem]) -> tuple[int, int]:
        inserted = 0
        updated = 0
        for item in items:
            if self.upsert_item(item):
                inserted += 1
            else:
                updated += 1
        self.conn.commit()
        return inserted, updated

    def upsert_item(self, item: TorrentItem) -> bool:
        existing = self.conn.execute(
            "SELECT id FROM items WHERE site = ? AND detail_url = ?",
            (item.site, item.detail_url),
        ).fetchone()
        data = asdict(item)
        timestamp = now_iso()
        if existing is None:
            self.conn.execute(
                """
                INSERT INTO items (
                  site, title, product_code, product_prefix, product_number, detail_url, torrent_url, category, size_text, size_bytes,
                  seeders, leechers, completed_downloads, published_at, search_query,
                  query_params_json, source_url, first_seen_at, last_seen_at
                ) VALUES (
                  :site, :title, :product_code, :product_prefix, :product_number, :detail_url, :torrent_url, :category, :size_text, :size_bytes,
                  :seeders, :leechers, :completed_downloads, :published_at, :search_query,
                  :query_params_json, :source_url, :first_seen_at, :last_seen_at
                )
                """,
                {**data, "first_seen_at": timestamp, "last_seen_at": timestamp},
            )
            return True

        self.conn.execute(
            """
            UPDATE items SET
              title = :title,
              product_code = :product_code,
              product_prefix = :product_prefix,
              product_number = :product_number,
              torrent_url = :torrent_url,
              category = :category,
              size_text = :size_text,
              size_bytes = :size_bytes,
              seeders = :seeders,
              leechers = :leechers,
              completed_downloads = :completed_downloads,
              published_at = :published_at,
              search_query = :search_query,
              query_params_json = :query_params_json,
              source_url = :source_url,
              last_seen_at = :last_seen_at
            WHERE site = :site AND detail_url = :detail_url
            """,
            {**data, "last_seen_at": timestamp},
        )
        return False

    def backfill_product_codes(self) -> None:
        rows = self.conn.execute(
            """
            SELECT id, title FROM items
            WHERE product_code IS NULL OR product_code = ''
               OR product_prefix IS NULL OR product_prefix = ''
               OR product_number IS NULL OR product_number = ''
            """
        ).fetchall()
        for row in rows:
            parts = extract_product_code_parts(str(row["title"]))
            if parts:
                self.conn.execute(
                    """
                    UPDATE items
                    SET product_code = ?,
                        product_prefix = ?,
                        product_number = ?
                    WHERE id = ?
                    """,
                    (parts.code, parts.prefix, parts.number, int(row["id"])),
                )

    def all_items(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM items ORDER BY completed_downloads DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def recent_runs(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM crawl_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def download_candidates(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM items
            WHERE torrent_url IS NOT NULL
              AND (downloaded_at IS NULL OR download_status != 'downloaded')
            ORDER BY completed_downloads DESC, id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def mark_downloaded(self, item_id: int, file_path: Path) -> None:
        self.conn.execute(
            """
            UPDATE items
            SET download_status = 'downloaded',
                downloaded_at = ?,
                torrent_file_path = ?,
                download_error = NULL
            WHERE id = ?
            """,
            (now_iso(), str(file_path), item_id),
        )
        self.conn.commit()

    def mark_failed(self, item_id: int, error: str) -> None:
        self.conn.execute(
            """
            UPDATE items
            SET download_status = 'failed',
                download_error = ?
            WHERE id = ?
            """,
            (error[:1000], item_id),
        )
        self.conn.commit()

    def start_crawl_run(self, job_name: str, query_params_json: str) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO crawl_runs (job_name, query_params_json, started_at)
            VALUES (?, ?, ?)
            """,
            (job_name, query_params_json, now_iso()),
        )
        self.conn.commit()
        return int(cursor.lastrowid)

    def finish_crawl_run(
        self,
        run_id: int,
        *,
        pages_requested: int,
        parsed_count: int,
        inserted_count: int,
        updated_count: int,
        matching_count: int,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE crawl_runs
            SET finished_at = ?,
                pages_requested = ?,
                parsed_count = ?,
                inserted_count = ?,
                updated_count = ?,
                matching_count = ?,
                error = ?
            WHERE id = ?
            """,
            (
                now_iso(),
                pages_requested,
                parsed_count,
                inserted_count,
                updated_count,
                matching_count,
                error,
                run_id,
            ),
        )
        self.conn.commit()
