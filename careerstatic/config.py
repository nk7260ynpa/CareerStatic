"""全域設定管理。

所有可調參數集中於此，一律可用環境變數覆蓋；並提供全專案
唯一的「今天」時區定義（Asia/Taipei）。
"""

import dataclasses
import datetime
import functools
import os
from zoneinfo import ZoneInfo

TAIPEI_TZ = ZoneInfo("Asia/Taipei")

# 預設搜尋關鍵字（可由環境變數 CRAWL_KEYWORDS 以逗號分隔覆蓋）
DEFAULT_KEYWORDS = (
    "AI",
    "人工智慧",
    "機器學習",
    "深度學習",
    "LLM",
    "生成式AI",
    "資料科學",
    "資料工程",
    "NLP",
    "電腦視覺",
)

# 104 列表 API 的分頁硬上限
MAX_LAST_PAGE = 150


def _env_bool(name: str, default: bool) -> bool:
    """讀取布林型環境變數。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclasses.dataclass(frozen=True)
class Settings:
    """應用程式設定。

    Attributes:
        database_url: SQLAlchemy 連線字串。
        keywords: 搜尋關鍵字集合（聯集去重）。
        max_pages_per_keyword: 每個關鍵字最多翻頁數（上限 150）。
        detail_limit_per_day: 每日最多抓取的詳細內容筆數。
        min_delay: 每次請求前的最小延遲秒數。
        max_delay: 每次請求前的最大延遲秒數。
        enable_scheduler: 是否啟動每日排程器（測試時關閉）。
        run_on_startup: 服務啟動時若當日尚未爬取，是否補跑。
        crawl_hour: 每日排程觸發的整點（Asia/Taipei）。
        stats_top_n: 每類別每日入庫的統計項目上限。
        log_level: log 等級名稱。
        web_port: 網頁服務埠號。
    """

    database_url: str
    keywords: tuple[str, ...]
    max_pages_per_keyword: int
    detail_limit_per_day: int
    min_delay: float
    max_delay: float
    enable_scheduler: bool
    run_on_startup: bool
    crawl_hour: int
    stats_top_n: int
    log_level: str
    web_port: int


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """自環境變數組出 Settings（快取單例）。"""
    keywords_raw = os.getenv("CRAWL_KEYWORDS", "")
    keywords = tuple(k.strip() for k in keywords_raw.split(",") if k.strip())
    return Settings(
        database_url=os.getenv(
            "DATABASE_URL", "sqlite+pysqlite:///data/careerstatic.db"
        ),
        keywords=keywords or DEFAULT_KEYWORDS,
        max_pages_per_keyword=min(
            int(os.getenv("MAX_PAGES_PER_KEYWORD", "50")), MAX_LAST_PAGE
        ),
        detail_limit_per_day=int(os.getenv("DETAIL_LIMIT_PER_DAY", "600")),
        min_delay=float(os.getenv("MIN_DELAY_SECONDS", "1.2")),
        max_delay=float(os.getenv("MAX_DELAY_SECONDS", "2.8")),
        enable_scheduler=_env_bool("ENABLE_SCHEDULER", True),
        run_on_startup=_env_bool("RUN_ON_STARTUP", True),
        crawl_hour=int(os.getenv("CRAWL_HOUR", "8")),
        stats_top_n=int(os.getenv("STATS_TOP_N", "100")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        web_port=int(os.getenv("WEB_PORT", "8000")),
    )


def taipei_now() -> datetime.datetime:
    """取得台北當下時間（aware datetime）。"""
    return datetime.datetime.now(tz=TAIPEI_TZ)


def taipei_today() -> datetime.date:
    """取得台北「今天」日期；全專案對「日」的唯一定義。"""
    return taipei_now().date()


def utc_now() -> datetime.datetime:
    """取得 UTC 當下時間（aware datetime），供 DB 時間戳使用。"""
    return datetime.datetime.now(tz=datetime.timezone.utc)
