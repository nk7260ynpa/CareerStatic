"""每日排程：APScheduler 於每日固定時刻（Asia/Taipei）觸發爬取。

設計約束：
- 服務必須以 uvicorn 單 worker 執行，排程器才會唯一；
  若未來要多 worker，必須將排程器拆成獨立程序。
- CRAWL_LOCK 讓排程觸發、手動 API 觸發與啟動補跑三方互斥。
"""

import datetime
import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from careerstatic.config import Settings, get_settings, taipei_today

logger = logging.getLogger(__name__)

CRAWL_LOCK = threading.Lock()

# 錯過排程時間 4 小時內仍補跑（例：Mac 短暫睡眠後喚醒）
_MISFIRE_GRACE_SECONDS = 4 * 3600
_STARTUP_DELAY_SECONDS = 10


def run_crawl_locked(trigger: str = "manual", **kwargs) -> bool:
    """取得鎖後執行一次爬取；已有爬取進行中則跳過。

    Args:
        trigger: 觸發來源（schedule / manual / startup）。
        **kwargs: 傳遞給 run_daily_crawl 的額外參數。

    Returns:
        是否實際執行了爬取。
    """
    if not CRAWL_LOCK.acquire(blocking=False):
        logger.warning("已有爬取進行中，跳過本次觸發（%s）", trigger)
        return False
    try:
        # 延遲載入以避免模組層循環相依
        from careerstatic.crawler.client import Client104
        from careerstatic.crawler.pipeline import run_daily_crawl
        from careerstatic.db.base import get_session_factory

        settings = get_settings()
        client = Client104(
            min_delay=settings.min_delay, max_delay=settings.max_delay
        )
        run_daily_crawl(
            get_session_factory(), client, settings, trigger=trigger, **kwargs
        )
        return True
    finally:
        CRAWL_LOCK.release()


def scheduled_crawl() -> None:
    """每日排程的進入點。"""
    run_crawl_locked(trigger="schedule")


def _startup_crawl() -> None:
    """啟動補跑的進入點。"""
    run_crawl_locked(trigger="startup")


def create_scheduler(settings: Settings) -> BackgroundScheduler:
    """建立每日排程器（尚未啟動）。"""
    scheduler = BackgroundScheduler(timezone="Asia/Taipei")
    scheduler.add_job(
        scheduled_crawl,
        CronTrigger(hour=settings.crawl_hour, minute=0, timezone="Asia/Taipei"),
        id="daily_crawl",
        name="每日職缺爬取",
        misfire_grace_time=_MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )
    return scheduler


def maybe_run_startup_crawl(
    scheduler: BackgroundScheduler, settings: Settings
) -> bool:
    """服務啟動時，若當日尚無成功爬取紀錄則排入補跑。

    Returns:
        是否已排入補跑。
    """
    if not settings.run_on_startup:
        return False

    from careerstatic.db import repository
    from careerstatic.db.base import get_session_factory

    session = get_session_factory()()
    try:
        run = repository.get_run_for_date(session, taipei_today())
    finally:
        session.close()

    if run is not None:
        logger.info("今日已完成爬取（run #%d），跳過啟動補跑", run.id)
        return False

    run_at = datetime.datetime.now().astimezone() + datetime.timedelta(
        seconds=_STARTUP_DELAY_SECONDS
    )
    scheduler.add_job(
        _startup_crawl,
        DateTrigger(run_date=run_at),
        id="startup_crawl",
        name="啟動補跑爬取",
    )
    logger.info("今日尚未爬取，已排入 %d 秒後的啟動補跑", _STARTUP_DELAY_SECONDS)
    return True
