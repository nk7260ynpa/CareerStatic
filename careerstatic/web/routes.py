"""網頁與 JSON API 路由。"""

import datetime
import logging
import threading
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from careerstatic.analyzer.code_maps import format_salary
from careerstatic.db import repository

logger = logging.getLogger(__name__)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def get_db() -> Iterator[Session]:
    """FastAPI 依賴：提供 DB session（用畢關閉）。"""
    from careerstatic.db.base import get_session_factory

    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


class CrawlRequest(BaseModel):
    """手動觸發爬取的參數。"""

    max_pages: int | None = None
    detail_limit: int | None = None
    details_only: bool = False


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    """儀表板頁面。"""
    dates = repository.list_stat_dates(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "dates": [d.isoformat() for d in dates],
            "latest": dates[0].isoformat() if dates else None,
        },
    )


@router.get("/healthz")
def healthz() -> dict:
    """健康檢查（docker healthcheck 用）。"""
    return {"status": "ok"}


@router.get("/api/dates")
def api_dates(db: Session = Depends(get_db)) -> dict:
    """列出所有有統計資料的日期（新到舊）。"""
    return {"dates": [d.isoformat() for d in repository.list_stat_dates(db)]}


@router.get("/api/summary")
def api_summary(
    date: datetime.date = Query(...), db: Session = Depends(get_db)
) -> dict:
    """取得某日總結與各類統計。"""
    summary = repository.get_summary(db, date)
    if summary is None:
        raise HTTPException(status_code=404, detail="該日期尚無統計資料")
    stats_json = summary.stats_json if isinstance(summary.stats_json, dict) else {}
    return {
        "date": summary.stat_date.isoformat(),
        "total_jobs": summary.total_jobs,
        "new_jobs": summary.new_jobs,
        "detail_coverage": summary.detail_coverage,
        "summary_text": summary.summary_text,
        "categories": stats_json.get("by_category", {}),
    }


@router.get("/api/trend")
def api_trend(
    days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)
) -> dict:
    """近 N 日職缺總數與新增數趨勢。"""
    rows = repository.get_trend(db, days)
    return {
        "dates": [row.stat_date.isoformat() for row in rows],
        "total_jobs": [row.total_jobs for row in rows],
        "new_jobs": [row.new_jobs for row in rows],
    }


@router.get("/api/jobs")
def api_jobs(
    date: datetime.date = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: str | None = Query(None, max_length=50),
    db: Session = Depends(get_db),
) -> dict:
    """分頁查詢某日快照中的職缺。"""
    jobs, total = repository.query_jobs_by_date(db, date, page, page_size, q)
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "job_no": job.job_no,
                "job_name": job.job_name,
                "cust_name": job.cust_name,
                "area_desc": job.area_desc,
                "salary_text": format_salary(
                    job.salary_desc, job.salary_low, job.salary_high, job.salary_type
                ),
                "job_url": job.job_url,
                "tech_keywords": list(job.tech_keywords or [])[:8],
            }
            for job in jobs
        ],
    }


@router.post("/api/crawl", status_code=202)
def api_crawl(payload: CrawlRequest | None = None) -> dict:
    """手動觸發一次爬取（背景執行）。

    已有爬取進行中時回 409。
    """
    from careerstatic import scheduler

    if scheduler.CRAWL_LOCK.locked():
        raise HTTPException(status_code=409, detail="已有爬取進行中，請稍後再試")

    payload = payload or CrawlRequest()
    thread = threading.Thread(
        target=scheduler.run_crawl_locked,
        kwargs={
            "trigger": "manual",
            "max_pages": payload.max_pages,
            "detail_limit": payload.detail_limit,
            "details_only": payload.details_only,
        },
        daemon=True,
    )
    thread.start()
    logger.info("已受理手動爬取請求：%s", payload.model_dump())
    return {"status": "started"}
