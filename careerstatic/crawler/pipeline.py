"""每日爬取主流程：列表蒐集 → 入庫 → 詳細補抓 → 統計總結。"""

import dataclasses
import datetime
import logging
from collections import defaultdict

from sqlalchemy.orm import Session, sessionmaker

from careerstatic.analyzer.stats import compute_daily_stats
from careerstatic.analyzer.summary import summarize_day
from careerstatic.analyzer.tech_keywords import match_keywords
from careerstatic.config import MAX_LAST_PAGE, Settings, taipei_today, utc_now
from careerstatic.crawler.client import Client104, CrawlBlockedError, CrawlError
from careerstatic.crawler.parser import JobListItem, parse_job_detail, parse_list_item
from careerstatic.db import repository
from careerstatic.db.models import CrawlRun

logger = logging.getLogger(__name__)

# 詳細階段連續失敗達此數即中止（疑似被封鎖），可由測試覆寫
MAX_CONSECUTIVE_DETAIL_FAILURES = 10

# 詳細階段每抓 N 筆 commit 一次，避免中途失敗遺失進度
_DETAIL_COMMIT_INTERVAL = 20


@dataclasses.dataclass
class CrawlResult:
    """單次爬取的執行結果摘要。"""

    run_date: datetime.date
    status: str = "success"
    jobs_seen: int = 0
    jobs_new: int = 0
    pages_fetched: int = 0
    details_fetched: int = 0
    details_pending: int = 0
    truncated_keywords: dict = dataclasses.field(default_factory=dict)
    error_message: str | None = None


def _collect_list_items(
    client: Client104, keywords: tuple[str, ...], max_pages: int
) -> tuple[dict[str, JobListItem], dict[str, set[str]], dict, int]:
    """走訪所有關鍵字的列表頁並以 job_no 聯集去重。

    Returns:
        (job_no → 職缺, job_no → 命中關鍵字集合, 截斷資訊, 總頁數)。
    """
    items_by_no: dict[str, JobListItem] = {}
    matched: dict[str, set[str]] = defaultdict(set)
    truncated: dict[str, dict] = {}
    total_pages = 0
    failed_keywords: list[str] = []

    for keyword in keywords:
        keyword_pages = 0
        keyword_items = 0
        last_pagination: dict = {}
        try:
            for raw_items, pagination in client.iter_search(keyword, max_pages):
                keyword_pages += 1
                total_pages += 1
                last_pagination = pagination
                for raw in raw_items:
                    item = parse_list_item(raw)
                    if not item.job_no:
                        continue
                    keyword_items += 1
                    items_by_no.setdefault(item.job_no, item)
                    matched[item.job_no].add(keyword)
        except CrawlError as exc:
            failed_keywords.append(keyword)
            logger.error("關鍵字「%s」搜尋失敗：%s", keyword, exc)
            continue

        last_page = int(last_pagination.get("lastPage") or 0)
        total_count = int(last_pagination.get("total") or 0)
        if last_page > keyword_pages or (
            last_page >= MAX_LAST_PAGE and total_count > keyword_items
        ):
            truncated[keyword] = {
                "total": total_count,
                "pages_fetched": keyword_pages,
                "last_page": last_page,
                "sampled": keyword_items,
            }
            logger.warning(
                "關鍵字「%s」超出可翻頁範圍：total=%d、實際取樣 %d 筆（%d 頁）",
                keyword,
                total_count,
                keyword_items,
                keyword_pages,
            )
        logger.info(
            "關鍵字「%s」完成：%d 頁、%d 筆（去重前）", keyword, keyword_pages, keyword_items
        )

    if failed_keywords and not items_by_no:
        raise CrawlError(f"所有關鍵字搜尋皆失敗：{failed_keywords}")

    return items_by_no, matched, truncated, total_pages


def _fetch_details(
    session: Session, client: Client104, limit: int
) -> tuple[int, int]:
    """抓取待補職缺的詳細內容。

    Returns:
        (本次成功筆數, 剩餘待抓筆數)。

    Raises:
        CrawlBlockedError: 連續失敗達門檻（已 commit 既有進度）。
    """
    jobs = repository.jobs_needing_detail(session, limit)
    fetched = 0
    consecutive_failures = 0

    for job in jobs:
        if not job.job_code:
            # 無法取得詳細內容代碼：標記已處理避免佇列卡死
            logger.warning("職缺 %s 缺少 job_code，跳過詳細抓取", job.job_no)
            job.detail_fetched_at = utc_now()
            continue
        try:
            raw = client.fetch_job_detail(job.job_code)
        except CrawlError as exc:
            consecutive_failures += 1
            logger.error("職缺 %s 詳細內容抓取失敗：%s", job.job_no, exc)
            if consecutive_failures >= MAX_CONSECUTIVE_DETAIL_FAILURES:
                session.commit()
                raise CrawlBlockedError(
                    f"連續 {consecutive_failures} 筆詳細內容抓取失敗，中止本輪詳細階段"
                ) from exc
            continue

        consecutive_failures = 0
        detail = parse_job_detail(raw)
        text = "\n".join(
            part
            for part in (job.job_name, detail.job_description, detail.other_condition)
            if part
        )
        repository.apply_detail(session, job, detail, match_keywords(text))
        fetched += 1
        if fetched % _DETAIL_COMMIT_INTERVAL == 0:
            session.commit()

    session.commit()
    pending = repository.count_jobs_needing_detail(session)
    return fetched, pending


def _run_analysis(
    session: Session, crawl_date: datetime.date, top_n: int, truncated: dict
) -> None:
    """執行統計與總結並 commit。"""
    stats = compute_daily_stats(session, crawl_date, top_n)
    summarize_day(session, crawl_date, stats, truncated)
    session.commit()


def run_daily_crawl(
    session_factory: sessionmaker,
    client: Client104,
    settings: Settings,
    *,
    crawl_date: datetime.date | None = None,
    max_pages: int | None = None,
    detail_limit: int | None = None,
    details_only: bool = False,
    trigger: str = "schedule",
) -> CrawlResult:
    """執行一次完整的每日爬取。

    Args:
        session_factory: DB session 工廠。
        client: 104 API 客戶端。
        settings: 應用程式設定。
        crawl_date: 爬取歸屬日期（預設台北今天）。
        max_pages: 覆蓋每關鍵字最大頁數。
        detail_limit: 覆蓋本次詳細抓取上限。
        details_only: 只補抓詳細內容並重算統計（跳過列表階段）。
        trigger: 觸發來源（schedule / manual / startup）。

    Returns:
        CrawlResult 執行結果摘要。
    """
    crawl_date = crawl_date or taipei_today()
    effective_max_pages = min(max_pages or settings.max_pages_per_keyword, MAX_LAST_PAGE)
    effective_detail_limit = (
        detail_limit if detail_limit is not None else settings.detail_limit_per_day
    )
    result = CrawlResult(run_date=crawl_date)

    session: Session = session_factory()
    run = CrawlRun(
        run_date=crawl_date,
        trigger="details_only" if details_only else trigger,
        status="running",
        started_at=utc_now(),
        keywords=list(settings.keywords),
    )
    session.add(run)
    session.commit()
    run_id = run.id
    logger.info(
        "開始爬取（run #%d，trigger=%s，日期=%s，max_pages=%d，detail_limit=%d）",
        run_id,
        run.trigger,
        crawl_date,
        effective_max_pages,
        effective_detail_limit,
    )

    try:
        if not details_only:
            items_by_no, matched, truncated, pages = _collect_list_items(
                client, settings.keywords, effective_max_pages
            )
            result.pages_fetched = pages
            result.truncated_keywords = truncated
            result.jobs_seen = len(items_by_no)

            tech_kw = {
                job_no: sorted(
                    match_keywords(f"{item.job_name}\n{item.description}")
                )
                for job_no, item in items_by_no.items()
            }
            new_nos, updated = repository.upsert_jobs_from_list(
                session, items_by_no.values(), matched, crawl_date, tech_kw
            )
            repository.record_snapshots(
                session, set(items_by_no), new_nos, matched, crawl_date
            )
            session.commit()
            result.jobs_new = len(new_nos)
            logger.info(
                "列表入庫完成：共 %d 筆（新增 %d、更新 %d）",
                result.jobs_seen,
                len(new_nos),
                updated,
            )
        else:
            latest_run = repository.get_latest_run_for_date(session, crawl_date)
            if latest_run is not None:
                result.truncated_keywords = dict(latest_run.truncated_keywords or {})

        try:
            result.details_fetched, result.details_pending = _fetch_details(
                session, client, effective_detail_limit
            )
        except CrawlBlockedError as exc:
            result.status = "partial"
            result.error_message = str(exc)
            result.details_pending = repository.count_jobs_needing_detail(session)
            logger.error("詳細階段中止：%s", exc)

        _run_analysis(session, crawl_date, settings.stats_top_n, result.truncated_keywords)
    except Exception as exc:  # noqa: BLE001 - 任何未預期錯誤都要記錄並標記失敗
        session.rollback()
        result.status = "failed"
        result.error_message = str(exc)[:2000]
        logger.exception("爬取失敗（run #%d）", run_id)
    finally:
        run = session.get(CrawlRun, run_id)
        if run is not None:
            run.status = result.status
            run.finished_at = utc_now()
            run.pages_fetched = result.pages_fetched
            run.jobs_seen = result.jobs_seen
            run.jobs_new = result.jobs_new
            run.details_fetched = result.details_fetched
            run.details_pending = result.details_pending
            run.truncated_keywords = result.truncated_keywords
            run.error_message = result.error_message
            session.commit()
        session.close()

    logger.info(
        "爬取結束（run #%d）：status=%s、jobs_seen=%d、jobs_new=%d、"
        "details_fetched=%d、details_pending=%d",
        run_id,
        result.status,
        result.jobs_seen,
        result.jobs_new,
        result.details_fetched,
        result.details_pending,
    )
    return result
