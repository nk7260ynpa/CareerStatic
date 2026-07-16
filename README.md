# CareerStatic

每日自動爬取 104 人力銀行的 AI 相關職缺、寫入 PostgreSQL、統計「所需工作能力」，
並以網頁儀表板呈現總結成果。

## 功能特色

- **每日排程**：每天 20:00（Asia/Taipei）自動爬取；服務啟動時若當日尚未爬取會自動補跑。
- **多關鍵字聯集**：以可設定的關鍵字全文搜尋（預設 AI、人工智慧、機器學習…），依職缺編號去重。
- **兩階段爬取**：列表 API 取基本欄位，詳細 API 補齊工作技能／擅長工具／完整描述；
  只對新職缺抓詳細內容，並有每日上限（首日積壓自動分日消化）。
- **工作能力統計**：六大類別——擅長工具、工作技能、內文技術關鍵字（80+ 條字典）、
  學歷門檻、經歷要求、語言要求，另產出繁體中文每日總結。
- **儀表板**：FastAPI + Chart.js，可切換日期、看 30 日趨勢、瀏覽職缺明細、手動觸發更新。

## 專案架構

```
APScheduler（每日 20:00 Asia/Taipei，與 Web 同容器）
    └─> pipeline.run_daily_crawl()
          ├─ Client104（curl_cffi 模擬 Chrome、節流 1.2~2.8s、指數退避重試）
          │    ├─ 列表：多關鍵字 × 分頁 → 以 jobNo 聯集去重
          │    └─ 詳細：只抓尚未補齊的職缺，每日上限 600
          ├─ db.repository：jobs upsert、每日快照、爬取紀錄
          └─ analyzer：技術關鍵字比對 + 六類統計 → 統計表、每日總結
FastAPI（uvicorn 單 worker）─ Jinja2 儀表板 + JSON API + Chart.js
PostgreSQL 16（docker compose 附帶；單元測試用 SQLite in-memory）
```

### 目錄結構

```
CareerStatic/
├── run.sh                  # 指令入口（serve / crawl / pytest / logs / stop / build / psql）
├── docker/
│   ├── build.sh            # 建置 Docker image
│   ├── Dockerfile          # python:3.12-slim
│   └── docker-compose.yaml # app + postgres:16
├── logs/                   # 執行 log（掛載進容器）
├── careerstatic/
│   ├── config.py           # 環境變數設定與台北時區「今天」定義
│   ├── logging_setup.py    # RotatingFileHandler + 終端輸出
│   ├── main.py             # CLI：serve / crawl / analyze
│   ├── scheduler.py        # APScheduler 每日排程、啟動補跑、爬取互斥鎖
│   ├── db/
│   │   ├── base.py         # engine / session 工廠
│   │   ├── models.py       # 5 張表（jobs、每日快照、爬取紀錄、每日統計、每日總結）
│   │   └── repository.py   # upsert 與查詢（SQLite/PostgreSQL 可攜寫法）
│   ├── crawler/
│   │   ├── client.py       # 104 API 客戶端（curl_cffi、節流、重試）
│   │   ├── parser.py       # 回應解析（防禦性取值）
│   │   └── pipeline.py     # 每日爬取主流程
│   ├── analyzer/
│   │   ├── tech_keywords.py# 技術關鍵字字典（80+ 條 regex）
│   │   ├── code_maps.py    # 學歷／經歷／薪資／語言代碼對照
│   │   ├── stats.py        # 每日六類統計
│   │   └── summary.py      # 繁中總結文字與統計快照
│   └── web/
│       ├── app.py          # FastAPI 應用工廠（lifespan 啟動排程器）
│       ├── routes.py       # 頁面與 JSON API
│       ├── templates/      # Jinja2 模板
│       └── static/         # CSS / JS / Chart.js（vendor 入版控，免外部 CDN）
└── tests/                  # pytest 單元測試（真實 API 回應 fixtures）
```

### 資料表

| 資料表 | 用途 |
| --- | --- |
| `jobs` | 職缺主檔（最新狀態；`detail_fetched_at` 為 NULL 表示詳細內容待抓） |
| `job_daily_snapshots` | 每日快照：哪些職缺在哪一天出現（每日統計的母體） |
| `crawl_runs` | 每次爬取紀錄（狀態、筆數、截斷資訊、錯誤訊息） |
| `daily_skill_stats` | 每日六類統計（項目、職缺數、佔比、排名） |
| `daily_summaries` | 每日總結（繁中文字 + 前端用統計快照） |

## 快速開始

需求：Docker（含 docker compose）。

```bash
# 1. 建置並啟動服務（含 PostgreSQL）
./run.sh serve
# 啟動後若當日尚未爬取，約 10 秒後自動開始補跑（首輪約 30~60 分鐘）

# 2.（可選）先小量試爬，快速看到儀表板效果
./run.sh crawl --max-pages 2 --detail-limit 10

# 3. 開啟儀表板
open http://localhost:8000
```

常用指令：

```bash
./run.sh pytest                              # 於容器內執行單元測試
./run.sh crawl                               # 立即執行一次完整爬取
./run.sh crawl --details-only --detail-limit 2000   # 加速補抓詳細內容
./run.sh logs                                # 追蹤服務 log（logs/careerstatic.log）
./run.sh psql                                # 進入 PostgreSQL
./run.sh stop                                # 停止服務
```

## 設定（環境變數）

於 `docker/docker-compose.yaml` 的 `app.environment` 調整：

| 變數 | 預設 | 說明 |
| --- | --- | --- |
| `CRAWL_KEYWORDS` | AI,人工智慧,機器學習,… | 搜尋關鍵字（逗號分隔） |
| `MAX_PAGES_PER_KEYWORD` | 50 | 每關鍵字最大頁數（API 上限 150） |
| `DETAIL_LIMIT_PER_DAY` | 600 | 每日詳細內容抓取上限 |
| `CRAWL_HOUR` | 20 | 每日排程整點（Asia/Taipei） |
| `MIN_DELAY_SECONDS` / `MAX_DELAY_SECONDS` | 1.2 / 2.8 | 每次請求前的隨機延遲 |
| `RUN_ON_STARTUP` | true | 啟動時當日未爬取則補跑 |
| `STATS_TOP_N` | 100 | 每類別每日入庫項目數上限 |
| `DATABASE_URL` | （compose 內建） | SQLAlchemy 連線字串 |
| `LOG_LEVEL` | INFO | log 等級 |

## 排程與資料說明

- **排程觸發條件**：Mac 需開機且 Docker 正在執行。容器設 `restart: unless-stopped`，
  Docker 啟動後服務自動復活；錯過 20:00 時（4 小時內）會補跑，超過則由
  `RUN_ON_STARTUP` 在下次服務啟動時補當日資料。建議把 Docker Desktop 設為登入自動啟動。
- **樣本非母體**：104 列表 API 最多翻 150 頁（約 3,300 筆／關鍵字）。熱門關鍵字
  （如「AI」約 2.5 萬筆）超出可翻頁範圍時，統計母體為「當日可見樣本」；
  截斷資訊會記錄於 `crawl_runs.truncated_keywords` 並揭露於每日總結附註。
- **詳細內容涵蓋率**：「工作技能」等欄位僅詳細 API 提供。首日新職缺量大時會分日補抓，
  儀表板顯示的「詳細資料涵蓋率」代表當日統計的可信度，可用
  `./run.sh crawl --details-only` 加速補齊。

## 測試

單元測試一律於 Docker 容器內執行，使用 SQLite in-memory、不連 PostgreSQL、
不啟動排程器，並以真實 API 回應裁剪成的 fixtures 驗證解析邏輯：

```bash
./run.sh pytest            # 全部測試
./run.sh pytest tests/test_analyzer.py -v
```

## 注意事項

- 本專案使用 104 非官方 API，僅蒐集公開職缺資訊供個人研究；請維持預設的
  低頻禮貌性爬取（每日一輪、請求間隔 1.2~2.8 秒），勿移除節流。
- 104 改版可能導致欄位變動：解析層採防禦性取值，欄位缺失不會中斷，
  但建議留意 log 中的 WARNING。
- 服務必須維持 uvicorn 單 worker（Dockerfile 預設），排程器才不會重複觸發；
  若要多 worker，需先將排程器拆成獨立程序。
- 學歷／語言等代碼對照以實測樣本驗證（詳 `analyzer/code_maps.py`）；
  遇到未知代碼會顯示「代碼N」並記 log，可據此補充對照表。
