# CLI 使用手册

## 1. 安装

在项目根目录执行：

```bash
python3 -m pip install .
```

安装后可以使用两种方式运行：

```bash
python3 -m sukebei_crawler --help
```

或：

```bash
sukebei-crawler --help
```

## 2. 准备配置文件

复制示例配置：

```bash
cp config.example.yaml config.yaml
```

常用配置项：

```yaml
query:
  filters:
    f: 2
    c: "2_0"
    q: "fhd"

crawl:
  max_pages: 1
  request_delay_seconds: 5
  request_jitter_seconds: 3

conditions:
  min_completed_downloads: 100
  min_size: "500 MiB"
  max_size: "20 GiB"

storage:
  db_path: "./data/items.sqlite"

download:
  output_dir: "./downloads"
```

说明：

- `query.filters` 会被拼成 URL 查询参数。
- `q` 是关键词。
- `max_pages` 控制最多抓取多少页。
- `request_delay_seconds` 是基础请求间隔，默认不允许小于 5 秒。
- `request_jitter_seconds` 是随机额外等待时间。
- `conditions` 控制 `list` 和 `download` 的筛选条件。
- `storage.db_path` 是 SQLite 数据库位置。
- `download.output_dir` 是 `.torrent` 文件保存目录。

## 3. 采集数据

```bash
python3 -m sukebei_crawler --config config.yaml crawl
```

行为：

- 根据 `config.yaml` 生成搜索 URL。
- 抓取最多 `crawl.max_pages` 页。
- 解析列表页资源。
- 保存到 SQLite。
- 输出采集摘要。

示例输出：

```text
fetching page 1: https://sukebei.nyaa.si/?f=2&c=2_0&q=fhd
summary:
  pages_requested: 1
  parsed: 75
  inserted: 75
  updated: 0
  matching_conditions: 75
```

临时覆盖关键词：

```bash
python3 -m sukebei_crawler --config config.yaml crawl --q fhd
```

注意：

- `crawl` 会保存所有解析成功的资源。
- `conditions` 不会限制入库，只影响统计、查看和下载候选。
- 重复采集同一资源不会重复插入，会更新下载数、做种数等动态字段。

## 4. 查看数据

```bash
python3 -m sukebei_crawler --config config.yaml list --limit 20
```

行为：

- 从 SQLite 读取已采集数据。
- 按 `conditions` 筛选。
- 按完成下载数降序展示。

示例输出：

```text
[61] code=FNS-216 completed=5775 seeders=194 size=6.4 GiB title=...
summary:
  matching: 75
  shown: 20
```

如果需要直接查数据库：

```bash
sqlite3 data/items.sqlite
```

常用 SQL：

```sql
SELECT id, completed_downloads, seeders, size_text, title
FROM items
ORDER BY completed_downloads DESC
LIMIT 20;
```

查看番号：

```sql
SELECT id, product_code, completed_downloads, title
FROM items
WHERE product_code IS NOT NULL
ORDER BY completed_downloads DESC
LIMIT 20;
```

## 5. 预览下载

默认下载命令只预览，不会写入 `.torrent` 文件：

```bash
python3 -m sukebei_crawler --config config.yaml download --limit 20
```

行为：

- 从 SQLite 找出符合 `conditions` 的资源。
- 排除已经成功下载的资源。
- 显示候选列表。
- 不下载文件。

## 6. 确认下载

确认下载需要加 `--yes`：

```bash
python3 -m sukebei_crawler --config config.yaml download --limit 20 --yes
```

行为：

- 下载符合条件且未下载过的 `.torrent` 文件。
- 保存到 `download.output_dir`。
- 成功后更新 `download_status='downloaded'`。
- 失败后更新 `download_status='failed'` 和 `download_error`。

默认不会覆盖已有文件，除非配置：

```yaml
download:
  overwrite_existing: true
```

## 7. 筛选规则

支持的主要筛选条件：

```yaml
conditions:
  min_completed_downloads: 100
  min_size: "500 MiB"
  max_size: "20 GiB"
  title_include: []
  title_exclude: []
```

说明：

- `min_completed_downloads`：完成下载次数最小值。
- `min_size`：文件大小下限。
- `max_size`：文件大小上限。
- `title_include`：标题必须包含的关键词列表。
- `title_exclude`：标题不能包含的关键词列表。

支持的大小单位：

- `KiB`
- `MiB`
- `GiB`
- `TiB`
- `KB`
- `MB`
- `GB`
- `TB`

## 8. 数据目录

程序会自动创建：

```text
data/
downloads/
logs/
```

默认数据库：

```text
data/items.sqlite
```

默认种子文件目录：

```text
downloads/
```

## 9. 定时任务

程序本身不负责定时执行，可以用 Linux `cron`。

每天凌晨 2 点采集：

```cron
0 2 * * * cd /home/song/project/sukebei && python3 -m sukebei_crawler --config config.yaml crawl >> logs/crawl.log 2>&1
```

每天凌晨 2 点采集，2 点 30 分预览下载候选：

```cron
0 2 * * * cd /home/song/project/sukebei && python3 -m sukebei_crawler --config config.yaml crawl >> logs/crawl.log 2>&1
30 2 * * * cd /home/song/project/sukebei && python3 -m sukebei_crawler --config config.yaml download >> logs/download-preview.log 2>&1
```

不建议默认把 `download --yes` 放进 cron，除非筛选条件已经确认稳定。

## 10. 排错

查看帮助：

```bash
python3 -m sukebei_crawler --help
python3 -m sukebei_crawler crawl --help
python3 -m sukebei_crawler list --help
python3 -m sukebei_crawler download --help
```

依赖缺失时重新安装：

```bash
python3 -m pip install .
```

配置文件不存在时：

```text
config error: Config file not found: config.yaml
```

解决：

```bash
cp config.example.yaml config.yaml
```

请求被限制时，程序会停止本轮任务，不会持续重试。可以降低 `max_pages`，增加 `request_delay_seconds` 后再运行。
