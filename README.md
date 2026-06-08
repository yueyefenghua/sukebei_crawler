# Sukebei Crawler

低频 CLI 采集工具，用于按配置抓取列表页资源信息，保存到 SQLite，并在确认后下载符合条件的 `.torrent` 文件。

## 快速开始

安装依赖：

```bash
python3 -m pip install .
```

复制示例配置：

```bash
cp config.example.yaml config.yaml
```

采集列表页：

```bash
python3 -m sukebei_crawler --config config.yaml crawl
```

查看符合条件的资源：

```bash
python3 -m sukebei_crawler --config config.yaml list --limit 20
```

预览待下载的 `.torrent`：

```bash
python3 -m sukebei_crawler --config config.yaml download --limit 20
```

确认下载：

```bash
python3 -m sukebei_crawler --config config.yaml download --limit 20 --yes
```

临时覆盖关键词：

```bash
python3 -m sukebei_crawler --config config.yaml crawl --q fhd
```

## 行为说明

- `crawl` 会保存所有解析成功的资源，不只保存符合筛选条件的资源。
- `list` 和 `download` 会按 `config.yaml` 里的 `conditions` 过滤。
- `download` 没有 `--yes` 时只预览，不会写入 `.torrent` 文件。
- 程序默认不并发请求，带请求间隔、随机抖动、有限重试和封禁状态停止。
- 自动创建 `data/`、`downloads/`、`logs/` 目录。

## 验证

```bash
python3 -m pytest -q
```

## 文档

- [CLI 使用手册](docs/cli-manual.md)
- [功能计划](docs/crawler-plan.md)
