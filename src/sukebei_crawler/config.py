from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class AppConfig:
    raw: dict[str, Any]
    config_path: Path

    @property
    def base_url(self) -> str:
        return str(self.raw["site"]["base_url"]).rstrip("/")

    @property
    def db_path(self) -> Path:
        return Path(self.raw["storage"]["db_path"])

    @property
    def download_dir(self) -> Path:
        return Path(self.raw["download"]["output_dir"])

    @property
    def filters(self) -> dict[str, Any]:
        return dict(self.raw["query"].get("filters", {}))

    @property
    def search_query(self) -> str:
        return str(self.filters.get("q", "") or "")


DEFAULTS: dict[str, Any] = {
    "site": {
        "base_url": "https://sukebei.nyaa.si",
        "user_agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "accept_language": "en-US,en;q=0.9",
    },
    "query": {"filters": {"f": 2, "c": "2_0", "q": ""}},
    "crawl": {
        "max_pages": 1,
        "request_delay_seconds": 5,
        "request_jitter_seconds": 3,
        "timeout_seconds": 20,
        "stop_on_block_status": True,
        "retry_count": 2,
    },
    "conditions": {
        "min_completed_downloads": None,
        "min_size": None,
        "max_size": None,
        "title_include": [],
        "title_exclude": [],
    },
    "storage": {"db_path": "./data/items.sqlite"},
    "download": {
        "output_dir": "./downloads",
        "request_delay_seconds": 5,
        "request_jitter_seconds": 3,
        "retry_count": 2,
        "overwrite_existing": False,
    },
}


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    parsed = parse_yaml(config_path.read_text(encoding="utf-8"))
    raw = merge_defaults(DEFAULTS, parsed)
    cfg = AppConfig(raw=raw, config_path=config_path)
    validate_config(cfg)
    return cfg


def merge_defaults(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            result[key] = merge_defaults(value, overrides.get(key, {}))
        else:
            result[key] = overrides.get(key, value)
    for key, value in overrides.items():
        if key not in result:
            result[key] = value
    return result


def parse_yaml(text: str) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML config: {exc}") from exc
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ConfigError("Config root must be a mapping")
    return parsed


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Backward-compatible alias for tests and older imports."""
    return parse_yaml(text)


def validate_config(cfg: AppConfig) -> None:
    parsed = urlparse(cfg.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError("site.base_url must be a valid http(s) URL")

    crawl = cfg.raw["crawl"]
    download = cfg.raw["download"]
    if int(crawl["max_pages"]) <= 0:
        raise ConfigError("crawl.max_pages must be greater than 0")
    if float(crawl["request_delay_seconds"]) < 5:
        raise ConfigError("crawl.request_delay_seconds must be at least 5")
    if float(download["request_delay_seconds"]) < 5:
        raise ConfigError("download.request_delay_seconds must be at least 5")
    if int(crawl["retry_count"]) < 0 or int(download["retry_count"]) < 0:
        raise ConfigError("retry_count cannot be negative")

    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.download_dir.mkdir(parents=True, exist_ok=True)
    Path("logs").mkdir(parents=True, exist_ok=True)
