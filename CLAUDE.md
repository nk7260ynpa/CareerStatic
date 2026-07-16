# CareerStatic 開發指南

104 人力銀行 AI 職缺每日爬取（20:00 Asia/Taipei）→ PostgreSQL →
工作能力統計 → FastAPI + Chart.js 儀表板。

## 常用指令

```bash
./run.sh serve      # 啟動服務（排程 + 儀表板，http://localhost:8000）
./run.sh pytest     # 於容器內跑單元測試（SQLite、不連 PG、不啟排程）
./run.sh crawl --max-pages 2 --detail-limit 10   # 小量手動爬取
./run.sh build      # 改碼後重建 image（serve 不掛載原始碼）
./run.sh logs       # 追蹤 log
./run.sh psql       # 進入 PostgreSQL
```

## 架構速覽

- `careerstatic/crawler/`：`client.py`（curl_cffi impersonate="chrome"，**勿自訂 UA**、
  勿移除節流）→ `parser.py`（防禦性解析）→ `pipeline.py`（每日流程：列表去重 →
  upsert → 詳細補抓 → 統計總結）。
- `careerstatic/db/`：五張表見 `models.py`；`repository.py` 只用 SQLite/PG 皆可的
  可攜寫法（JSONVariant、無方言 upsert）；JSON 欄位一律整個重新指派。
- `careerstatic/analyzer/`：`tech_keywords.py` 關鍵字字典（正則守則見模組 docstring）；
  `code_maps.py` 代碼對照（period 是代碼非年數，經歷統計優先用 detail 文字）。
- `careerstatic/scheduler.py`：APScheduler + `CRAWL_LOCK` 三方互斥；
  uvicorn 必須單 worker。
- 「日」一律用 `config.taipei_today()`；DB 時間戳用 `config.utc_now()`。

## 開發規範

- 文件、註解、docstring、commit message 一律繁體中文；遵循 Google Python /
  Shell / Markdown Style Guide。
- Conventional Commits（繁中、50/72），任務拆小步提交。
- 測試一律經 `./run.sh pytest` 於 Docker 內執行；`tests/conftest.py` 必須在
  import careerstatic 前設定環境變數（勿移動到 import 之後）。
- 修改 API 解析欄位時，優先更新 `tests/fixtures/`（自真實回應裁剪）。
