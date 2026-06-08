# Sukebei Crawler CLI 功能计划

## 1. 目标

构建一个低频、可配置的 CLI 爬虫工具，用于从目标站点列表页采集资源信息，按配置条件筛选后保存到 SQLite，并支持后续下载符合条件的 `.torrent` 文件。

工具第一版只做以下事情：

- 根据配置拼接搜索 URL。
- 抓取列表页。
- 解析资源标题、详情页、种子下载链接、文件大小、下载完成次数等字段。
- 按配置规则筛选。
- 将采集结果保存到 SQLite。
- 支持手动执行 `.torrent` 下载。

不做自动定时任务。定时执行由 Linux `cron` 或其他计划任务系统负责。

## 2. 合规与访问压力控制

工具应作为低频采集器使用，不能对目标服务器产生明显压力。

默认策略：

- 不并发请求。
- 每次请求之间加入固定延迟，默认不少于 15 秒，并带随机抖动。
- 每个搜索任务第一页请求前也先等待一次，避免程序启动后立即请求。
- 页面采集和 `.torrent` 下载分别配置请求间隔。
- 支持请求间隔抖动，例如在基础延迟上随机增加 0 到 3 秒，避免机械式固定频率。
- 支持最大页数限制。
- 遇到 `429`、`403`、`503` 等响应时停止或长时间退避。
- 默认不自动下载种子文件，需显式开启下载命令。
- 每个资源只保存一次，避免重复采集和重复下载。
- 下载 `.torrent` 时同样使用延迟和失败重试限制。
- 不使用代理池、不绕过验证码、不绕过封禁、不做反爬规避。

### 浏览器兼容请求

工具可以设置普通浏览器请求中常见的 HTTP 头，目的是提高兼容性，不是绕过目标站点限制。

建议请求头：

```text
User-Agent: Mozilla/5.0 ... Safari/537.36
Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8
Accept-Language: en-US,en;q=0.9
Accept-Encoding: gzip, deflate, br
Referer: 上一次列表页或详情页 URL
```

实现要求：

- `User-Agent` 允许在配置文件里设置。
- `Referer` 按正常浏览路径设置，例如列表页请求为空或首页，下载 `.torrent` 时使用资源详情页或列表页。
- 保持同一个 HTTP session，复用 cookie。
- 不伪造登录态。
- 不自动处理验证码。
- 如果站点返回明确限制访问的状态码，停止本轮任务。

### 请求重试与退避

普通网络失败可以有限重试：

- 列表页请求最多重试 2 次。
- `.torrent` 下载最多重试 2 次。
- 重试等待时间逐次增加，例如 10 秒、30 秒。
- 遇到 `429`、`403`、`503` 时不立即重复轰炸请求，停止本轮任务或进入长退避。
- 下载单个 `.torrent` 失败时记录失败状态，不影响后续候选继续下载。
- 如果连续多个下载都出现封禁类状态码，停止整个下载任务。

使用边界：

- 只下载用户有权获取、保存或分发的内容。
- 工具不负责后续 BT 下载，只下载 `.torrent` 文件。

## 3. 配置设计

建议使用 YAML 配置文件，例如 `config.yaml`。

```yaml
site:
  base_url: "https://sukebei.nyaa.si"
  user_agent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
  accept_language: "en-US,en;q=0.9"

query:
  filters:
    f: 2
    c: "2_0"
    q: "fhd"

# 可选：配置后 crawl 会逐个任务采集并统一入库去重。
search_jobs:
  - name: "fhd-vnds"
    filters:
      f: 2
      c: "2_0"
      q: "fhd VNDS"
  - name: "fhd-mkmp"
    filters:
      f: 2
      c: "2_0"
      q: "fhd MKMP"

crawl:
  max_pages: 3
  request_delay_seconds: 15
  request_jitter_seconds: 10
  timeout_seconds: 20
  stop_on_block_status: true
  retry_count: 2

conditions:
  min_completed_downloads: 100
  min_seeders: 10
  max_age_days:
  only_not_downloaded: false
  min_size: "500 MiB"
  max_size: "20 GiB"
  product_code_include: []
  product_code_exclude: []
  product_prefix_include: ["VNDS", "MKMP"]
  product_prefix_exclude: []
  title_include: []
  title_exclude: []

storage:
  db_path: "./data/items.sqlite"

download:
  output_dir: "./downloads"
  request_delay_seconds: 15
  request_jitter_seconds: 10
  retry_count: 2
  overwrite_existing: false
```

### 查询过滤器

`query.filters` 中的字段会直接作为 URL query 参数。

例如：

```yaml
query:
  filters:
    f: 2
    c: "2_0"
    q: "fhd"
```

会生成类似：

```text
https://sukebei.nyaa.si/?f=2&c=2_0&q=fhd
```

`q` 是关键词字段，可以通过配置文件修改，也可以后续支持 CLI 参数覆盖。

如果配置了 `search_jobs`，`crawl` 会忽略单个默认查询的执行入口，逐个执行 `search_jobs` 里的任务，所有结果统一写入 SQLite，并通过 `UNIQUE(site, detail_url)` 去重。`query.filters` 仍可作为默认单任务配置保留。

### 站点原生筛选边界

站点本身支持通过 `q` 做文本关键词搜索，也可以把多个关键词放在同一个 `q` 中缩小结果范围。

例如搜索标题中包含 `fhd` 和 `VNDS` 的资源：

```text
https://sukebei.nyaa.si/?f=2&c=2_0&q=fhd+VNDS
```

或：

```text
https://sukebei.nyaa.si/?f=2&c=2_0&q=fhd%20VNDS
```

站点原生支持的主要条件：

- `q`：关键词文本搜索。
- `c`：分类。
- `f`：过滤类型，例如 No filter、No remakes、Trusted only。
- `s`：排序字段，例如 date、size、seeders、leechers、downloads。
- `o`：排序方向，例如 asc、desc。
- `p`：页码。

站点不支持结构化字段筛选，例如：

```text
product_prefix = VNDS
product_number > 3000
product_code = VNDS-3440
completed_downloads > 1000
size between 1 GiB and 5 GiB
```

这些字段需要采集回 SQLite 后由本地工具过滤。

推荐策略：

- 站点侧用 `q="fhd VNDS"`、`q="fhd MKMP"` 这类组合关键词减少结果数量。
- 本地侧用 `product_prefix`、`product_number`、`completed_downloads`、`size_bytes` 做精确过滤。
- 当单个关键词结果过多、触碰站点页码上限时，按番号前缀或更细关键词拆成多个采集批次。

### 配置校验

程序启动时需要先校验配置：

- `site.base_url` 必须是合法 URL。
- `crawl.max_pages` 必须大于 0。
- `crawl.request_delay_seconds` 和 `download.request_delay_seconds` 默认不小于 10，建议保持 15 或更高。
- `crawl.retry_count` 和 `download.retry_count` 不能小于 0。
- `conditions.min_size` 和 `conditions.max_size` 同时存在时，`min_size` 不能大于 `max_size`。
- `query.filters.q` 可以为空，但为空时应明确输出提示，避免误以为正在按关键词搜索。
- `storage.db_path`、`download.output_dir` 所在目录不存在时自动创建。

## 4. 文件大小过滤

文件大小需要统一转换成字节后再比较，避免字符串比较错误。

需要支持的常见单位：

- `KiB`
- `MiB`
- `GiB`
- `TiB`
- `KB`
- `MB`
- `GB`
- `TB`

内部保存字段建议同时保留：

- 原始页面文本：例如 `1.4 GiB`
- 标准化字节数：例如 `1503238553`

配置中的 `min_size` 和 `max_size` 也需要解析成字节。

如果页面上的大小单位无法识别：

- 保存原始文本。
- `size_bytes` 记为空。
- 大小过滤条件存在时，该条资源默认不通过筛选。

## 5. 采集字段

列表页每条资源建议保存以下字段：

| 字段 | 说明 |
| --- | --- |
| `title` | 标题 |
| `product_code` | 从标题提取的番号，例如 `FNS-216` |
| `product_prefix` | 番号前缀，例如 `FNS`、`VNDS`，可用于按厂商或系列搜索 |
| `product_number` | 番号数字编码，例如 `216`、`3440` |
| `detail_url` | 详情页链接 |
| `torrent_url` | `.torrent` 下载链接 |
| `category` | 分类 |
| `size_text` | 页面原始文件大小文本 |
| `size_bytes` | 转换后的字节数 |
| `seeders` | 做种数 |
| `leechers` | 下载中数量 |
| `completed_downloads` | 下载完成次数 |
| `published_at` | 页面显示的发布时间 |
| `search_query` | 本次搜索关键词 |
| `query_params_json` | 本次搜索过滤参数 |
| `source_url` | 所属列表页 URL |
| `first_seen_at` | 首次采集时间 |
| `last_seen_at` | 最近一次采集时间 |
| `downloaded_at` | `.torrent` 下载时间 |
| `torrent_file_path` | 本地种子文件路径 |
| `download_status` | 下载状态 |
| `download_error` | 最近一次下载失败原因 |

采集批次表 `crawl_runs` 保存每次任务执行情况：

| 字段 | 说明 |
| --- | --- |
| `job_name` | 搜索任务名 |
| `query_params_json` | 本次任务查询参数 |
| `started_at` | 开始时间 |
| `finished_at` | 结束时间 |
| `pages_requested` | 请求页数 |
| `parsed_count` | 解析条数 |
| `inserted_count` | 新增条数 |
| `updated_count` | 更新条数 |
| `matching_count` | 符合当前条件条数 |
| `error` | 错误信息 |

## 6. SQLite 表设计

建议第一版使用单表 `items`。

```sql
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
);
```

```sql
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
);
```

更新逻辑：

- 如果 `detail_url` 不存在，插入新记录。
- 如果 `detail_url` 已存在，更新动态字段，例如 `seeders`、`leechers`、`completed_downloads`、`last_seen_at`。
- 不覆盖 `first_seen_at`。
- 不重复下载已存在且已标记 `downloaded_at` 的资源。
- 下载失败时写入 `download_status='failed'` 和 `download_error`。
- 下载成功时写入 `download_status='downloaded'`、`downloaded_at` 和 `torrent_file_path`。

时间字段规范：

- `first_seen_at`、`last_seen_at`、`downloaded_at` 使用 ISO 8601 字符串。
- 内部时间建议统一使用本地时区 `Asia/Shanghai`，后续如有跨服务器部署需求再切换 UTC。
- `published_at` 第一版可以保存页面原始文本，后续再增加标准化解析字段。

## 7. 分页规则

分页不要靠猜测 URL 参数硬拼。

第一版规则：

- 第 1 页使用配置生成的搜索 URL。
- 后续页面优先从 HTML 里解析分页区的 `Next` 链接。
- 如果没有 `Next` 链接，停止采集。
- 如果达到 `crawl.max_pages`，停止采集。
- 每次请求前都应用 `crawl.request_delay_seconds + 随机抖动`，包括每个任务的第一页。
- 每一页保存 `source_url`，方便追踪来源。

如果页面结构变化，无法解析分页链接：

- 已解析到的当前页资源正常保存。
- 输出明确错误信息。
- 停止继续翻页。

## 8. 解析失败处理

页面解析需要有明确失败策略：

- 如果列表页完全解析不到资源，输出提示并记录日志。
- 如果单条资源标题或详情页缺失，跳过该条。
- 如果单条资源没有 `.torrent` 下载链接，允许保存基础信息，但不进入下载候选。
- 如果下载完成次数无法解析，`completed_downloads` 记为空，存在最小完成次数条件时不通过筛选。
- 如果文件大小无法识别，保留 `size_text`，`size_bytes` 记为空，存在大小条件时不通过筛选。
- 解析异常不能导致数据库中已有数据被删除。

## 9. 筛选规则

采集和筛选要分开。

第一版规则：

- `crawl` 保存所有解析成功的资源。
- `conditions` 只用于统计“符合条件数量”和决定 `list`、`download` 候选。
- 不要只保存符合条件的资源，否则后续调整条件时会丢失历史采集数据。
- `download` 只处理符合条件、存在 `torrent_url`、未成功下载的资源。
- `list` 和 `export` 支持通过 CLI 参数临时覆盖部分筛选条件，例如 `--prefix`、`--code`、`--not-downloaded`、`--min-seeders`。

## 10. 下载文件命名

`.torrent` 文件命名规则：

- 优先使用资源标题清洗后的文本。
- 文件名追加数据库 `id` 或详情页 URL hash，避免重名。
- 扩展名固定为 `.torrent`。
- 文件名最大长度建议 180 字符。
- 移除或替换非法路径字符，例如 `/`、`\`、`..`、控制字符。
- 如果标题为空或清洗后为空，使用 `item-{id}.torrent`。
- 默认不覆盖已有文件，除非配置 `download.overwrite_existing: true`。
- 下载后需要做基础校验，文件过小、不是 bencode 字典格式、缺少常见 torrent key 时不标记为 downloaded。

## 11. CLI 命令设计

### 采集

```bash
python -m sukebei_crawler --config config.yaml crawl
```

行为：

- 读取配置。
- 按过滤器生成 URL。
- 抓取最多 `crawl.max_pages` 页。
- 解析页面资源。
- 保存到 SQLite。
- 输出本次采集数量、符合条件数量。
- 自动创建 `data/`、`downloads/`、`logs/` 等必要目录。

可选支持覆盖关键词：

```bash
python -m sukebei_crawler --config config.yaml crawl --q fhd
```

### 查询符合条件的资源

```bash
python -m sukebei_crawler --config config.yaml list
```

行为：

- 从 SQLite 中读取数据。
- 使用配置中的 `conditions` 再过滤一次。
- 输出标题、大小、下载完成次数、种子 URL 等摘要。

常用筛选：

```bash
python -m sukebei_crawler --config config.yaml list --prefix VNDS --limit 20
python -m sukebei_crawler --config config.yaml list --code VNDS-3440
python -m sukebei_crawler --config config.yaml list --not-downloaded
python -m sukebei_crawler --config config.yaml list --min-seeders 20
```

### 下载种子

```bash
python -m sukebei_crawler --config config.yaml download
```

行为：

- 从 SQLite 中找出符合条件且未下载的资源。
- 下载 `.torrent` 文件到 `download.output_dir`。
- 保存下载时间和本地文件路径。
- 下载过程中遵守延迟和失败重试限制。

建议第一版下载命令默认需要 `--yes` 才真正执行：

```bash
python -m sukebei_crawler --config config.yaml download --yes
```

没有 `--yes` 时只预览将要下载的列表。

### 导出

```bash
python -m sukebei_crawler --config config.yaml export --format csv --output exports.csv
python -m sukebei_crawler --config config.yaml export --format json --output exports.json
```

行为：

- 从 SQLite 中读取符合条件的数据。
- 支持 `--prefix`、`--code`、`--not-downloaded`、`--min-seeders` 临时筛选。
- 支持 CSV 和 JSON。

### 采集批次

```bash
python -m sukebei_crawler --config config.yaml runs --limit 20
```

行为：

- 查看最近 `crawl_runs` 记录。
- 输出任务名、页数、解析数、新增数、更新数、错误信息。

### 本地 Web 页面

```bash
python -m sukebei_crawler --config config.yaml serve
```

默认地址：

```text
http://127.0.0.1:8765
```

行为：

- 展示本地 SQLite 中的资源表格。
- 支持按番号前缀、完整番号、未下载筛选。
- 展示最近采集批次。
- 支持手动下载单个 `.torrent` 文件。

## 12. 日志与输出

第一版不需要复杂日志系统，但需要保证 cron 场景可追踪。

建议：

- CLI 标准输出打印运行摘要。
- 错误输出打印异常和失败原因。
- `logs/` 目录由用户在 cron 重定向时使用，程序只保证目录可创建。
- 摘要包括：请求页数、解析条数、新增条数、更新条数、符合条件条数、下载成功数、下载失败数。
- 下载预览时列出将要下载的前若干条，并提示需要 `--yes` 才会实际下载。
- `runs` 命令可查看结构化采集批次记录。

## 13. 第一版实施范围

第一版建议实现为最小可用版本：

1. 初始化 Python CLI 项目结构。
2. 支持读取 `config.yaml`。
3. 支持 URL 参数拼接。
4. 支持单线程、低频抓取列表页。
5. 支持解析列表页资源字段。
6. 支持文件大小单位转换。
7. 支持 `completed_downloads` 和文件大小筛选。
8. 支持 SQLite upsert 保存。
9. 支持 `list` 命令查看符合条件的资源。
10. 支持 `.torrent` 预览下载。
11. 支持 `--yes` 后实际下载 `.torrent`。
12. 支持请求头、session、请求间隔、随机抖动、有限重试和封禁状态停止。
13. 支持下载状态记录。

## 14. 验收标准

第一版完成时需要满足：

- 能读取 `config.yaml` 并生成正确搜索 URL。
- 能从样例 HTML 或真实列表页解析标题、详情页、`.torrent` 链接、大小、完成次数。
- 能把 `KiB`、`MiB`、`GiB`、`TiB`、`KB`、`MB`、`GB`、`TB` 转换为字节。
- 能将解析结果 upsert 到 SQLite。
- 重复采集不会重复插入同一资源。
- `crawl` 会保存所有解析成功资源，不只保存符合条件资源。
- `list` 只展示符合配置条件的资源。
- `download` 没有 `--yes` 时只预览，不产生 `.torrent` 文件。
- `download --yes` 时只下载未成功下载且符合条件的 `.torrent`。
- 请求之间存在配置的固定延迟和随机抖动。
- 每个搜索任务启动前存在配置的固定延迟和随机抖动。
- 遇到封禁类状态码会停止本轮任务，不持续请求。
- 下载失败会记录 `download_status` 和 `download_error`。
- `export` 能导出符合条件的数据。
- `runs` 能展示最近采集批次。
- `serve` 能启动本地页面并展示资源。

## 15. 后续可选增强

后续可以再加：

- 每个关键词独立条件。
- 详情页二次采集。
- 下载失败记录表。
- 请求缓存。
- 更完整的运行日志。
- 和 Linux `cron` 示例文档集成。

已实现的增强：

- 多搜索任务配置 `search_jobs`。
- 按番号前缀、完整番号、做种数、是否下载等本地筛选。
- CSV/JSON 导出。
- 采集批次表 `crawl_runs`。
- `.torrent` 基础内容校验。
- 本地 Web 页面查看与手动下载。

## 16. cron 示例

工具本身不负责定时运行。需要定时采集时，可以用 Linux `cron`。

示例：每天凌晨 2 点执行一次采集。

```cron
0 2 * * * cd /home/song/project/sukebei && python -m sukebei_crawler --config config.yaml crawl >> logs/crawl.log 2>&1
```

示例：每天凌晨 2 点采集，2 点 30 分预览待下载资源。

```cron
0 2 * * * cd /home/song/project/sukebei && python -m sukebei_crawler --config config.yaml crawl >> logs/crawl.log 2>&1
30 2 * * * cd /home/song/project/sukebei && python -m sukebei_crawler --config config.yaml download >> logs/download-preview.log 2>&1
```

实际下载建议不要默认放入 cron，除非已经确认筛选条件稳定可靠。
