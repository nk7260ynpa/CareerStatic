"""FastAPI 應用工廠。"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from careerstatic.config import Settings, get_settings
from careerstatic.logging_setup import configure_logging

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    """建立 FastAPI 應用。

    lifespan 啟動時初始化資料表；enable_scheduler 為真時一併啟動
    每日排程器與啟動補跑（pytest 透過環境變數關閉）。
    """
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        del app
        configure_logging(settings.log_level)
        from careerstatic.db.base import create_all

        create_all()

        scheduler = None
        if settings.enable_scheduler:
            from careerstatic.scheduler import create_scheduler, maybe_run_startup_crawl

            scheduler = create_scheduler(settings)
            scheduler.start()
            maybe_run_startup_crawl(scheduler, settings)
            job = scheduler.get_job("daily_crawl")
            logger.info(
                "排程器已啟動，下次執行時間：%s",
                job.next_run_time if job else "未知",
            )
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)

    app = FastAPI(
        title="CareerStatic",
        description="104 人力銀行 AI 職缺技能儀表板",
        lifespan=lifespan,
    )
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    from careerstatic.web.routes import router

    app.include_router(router)
    return app
