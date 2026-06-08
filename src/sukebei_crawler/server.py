from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import AppConfig
from .downloader import download_items
from .filters import item_matches
from .http_client import BLOCK_STATUS, HttpClient
from .storage import Storage


def serve(cfg: AppConfig, *, host: str, port: int) -> int:
    class Handler(DashboardHandler):
        config = cfg

    httpd = HTTPServer((host, port), Handler)
    print(f"serving dashboard at http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("stopped")
    return 0


class DashboardHandler(BaseHTTPRequestHandler):
    config: AppConfig

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.render_index(parse_qs(parsed.query), message=None)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/download":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        form = parse_qs(self.rfile.read(length).decode("utf-8"))
        item_id = int((form.get("id") or ["0"])[0])
        message = self.download_one(item_id)
        self.render_index({}, message=message)

    def render_index(self, query: dict[str, list[str]], message: str | None) -> None:
        conditions = dict(self.config.raw["conditions"])
        prefix = first(query, "prefix")
        code = first(query, "code")
        not_downloaded = first(query, "not_downloaded")
        if prefix:
            conditions["product_prefix_include"] = [prefix]
        if code:
            conditions["product_code_include"] = [code]
        if not_downloaded:
            conditions["only_not_downloaded"] = True

        storage = Storage(self.config.db_path)
        try:
            items = [item for item in storage.all_items() if item_matches(item, conditions)][:200]
            runs = storage.recent_runs(limit=5)
        finally:
            storage.close()

        body = self.build_page(items, runs, prefix=prefix, code=code, not_downloaded=bool(not_downloaded), message=message)
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def build_page(
        self,
        items: list[dict],
        runs: list[dict],
        *,
        prefix: str,
        code: str,
        not_downloaded: bool,
        message: str | None,
    ) -> str:
        rows = "\n".join(self.item_row(item) for item in items)
        run_rows = "\n".join(
            "<tr>"
            f"<td>{run['id']}</td><td>{esc(run['job_name'])}</td><td>{run['pages_requested']}</td>"
            f"<td>{run['parsed_count']}</td><td>{run['inserted_count']}</td><td>{run['updated_count']}</td>"
            f"<td>{esc(run['error'] or '-')}</td>"
            "</tr>"
            for run in runs
        )
        checked = "checked" if not_downloaded else ""
        notice = f"<p class='notice'>{esc(message)}</p>" if message else ""
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Sukebei Crawler</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; vertical-align: top; }}
    th {{ background: #f3f5f7; text-align: left; }}
    input, button {{ padding: 6px 8px; margin-right: 8px; }}
    .notice {{ background: #eef7ee; border: 1px solid #b9dfb9; padding: 8px; }}
    .title {{ max-width: 560px; }}
  </style>
</head>
<body>
  <h1>Sukebei Crawler</h1>
  {notice}
  <form method="get" action="/">
    <label>番号前缀 <input name="prefix" value="{esc(prefix)}" placeholder="VNDS"></label>
    <label>完整番号 <input name="code" value="{esc(code)}" placeholder="VNDS-3440"></label>
    <label><input type="checkbox" name="not_downloaded" value="1" {checked}> 未下载</label>
    <button type="submit">筛选</button>
  </form>
  <h2>资源</h2>
  <table>
    <thead>
      <tr><th>ID</th><th>番号</th><th>前缀</th><th>完成</th><th>做种</th><th>大小</th><th>状态</th><th>标题</th><th>操作</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>最近采集</h2>
  <table>
    <thead><tr><th>ID</th><th>任务</th><th>页数</th><th>解析</th><th>新增</th><th>更新</th><th>错误</th></tr></thead>
    <tbody>{run_rows}</tbody>
  </table>
</body>
</html>"""

    def item_row(self, item: dict) -> str:
        disabled = "disabled" if item.get("download_status") == "downloaded" else ""
        action = (
            f"<form method='post' action='/download'>"
            f"<input type='hidden' name='id' value='{int(item['id'])}'>"
            f"<button type='submit' {disabled}>下载种子</button>"
            "</form>"
        )
        return (
            "<tr>"
            f"<td>{item['id']}</td>"
            f"<td>{esc(item.get('product_code') or '-')}</td>"
            f"<td>{esc(item.get('product_prefix') or '-')}</td>"
            f"<td>{item.get('completed_downloads') or '-'}</td>"
            f"<td>{item.get('seeders') or '-'}</td>"
            f"<td>{esc(item.get('size_text') or '-')}</td>"
            f"<td>{esc(item.get('download_status') or '-')}</td>"
            f"<td class='title'><a href='{esc(item.get('detail_url') or '#')}'>{esc(item.get('title') or '')}</a></td>"
            f"<td>{action}</td>"
            "</tr>"
        )

    def download_one(self, item_id: int) -> str:
        storage = Storage(self.config.db_path)
        try:
            matches = [item for item in storage.download_candidates() if int(item["id"]) == item_id]
            if not matches:
                return f"没有可下载候选: id={item_id}"
            download_cfg = self.config.raw["download"]
            client = HttpClient(
                user_agent=str(self.config.raw["site"]["user_agent"]),
                accept_language=str(self.config.raw["site"].get("accept_language", "en-US,en;q=0.9")),
                timeout_seconds=int(self.config.raw["crawl"]["timeout_seconds"]),
                retry_count=int(download_cfg["retry_count"]),
                block_status=BLOCK_STATUS,
            )
            try:
                success, failed = download_items(
                    items=matches,
                    storage=storage,
                    client=client,
                    output_dir=Path(download_cfg["output_dir"]),
                    delay_seconds=0,
                    jitter_seconds=0,
                    overwrite_existing=bool(download_cfg["overwrite_existing"]),
                )
            finally:
                client.close()
            return f"下载完成: success={success}, failed={failed}"
        finally:
            storage.close()

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return


def first(query: dict[str, list[str]], key: str) -> str:
    return (query.get(key) or [""])[0].strip()


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)
