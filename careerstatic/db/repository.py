"""資料庫存取層：upsert 與查詢函式。

只使用 SQLite / PostgreSQL 皆可運作的可攜寫法（不用方言限定的
upsert、ARRAY 等），JSON 欄位一律整個重新指派以確保變更被追蹤。
"""

import datetime
import logging
from collections.abc import Collection, Iterable

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from careerstatic.config import utc_now
from careerstatic.crawler.parser import JobDetail, JobListItem
from careerstatic.db.models import (
    CrawlRun,
    DailySkillStat,
    DailySummary,
    Job,
    JobDailySnapshot,
)

logger = logging.getLogger(__name__)

_IN_BATCH_SIZE = 500


def get_existing_job_nos(session: Session, job_nos: Collection[str]) -> set[str]:
    """查詢已存在於 jobs 表的 job_no 集合（IN 分批以避免參數過多）。"""
    result: set[str] = set()
    nos = list(job_nos)
    for i in range(0, len(nos), _IN_BATCH_SIZE):
        batch = nos[i : i + _IN_BATCH_SIZE]
        rows = session.execute(select(Job.job_no).where(Job.job_no.in_(batch)))
        result.update(rows.scalars())
    return result


def upsert_jobs_from_list(
    session: Session,
    items: Iterable[JobListItem],
    matched: dict[str, set[str]],
    crawl_date: datetime.date,
    tech_keywords: dict[str, list[str]],
) -> tuple[set[str], int]:
    """以列表資料新增或更新職缺主檔。

    既有職缺只更新列表來源欄位（last_seen、薪資、應徵數、命中關鍵字
    聯集等），絕不覆寫詳細內容來源欄位（skills / specialties /
    description / detail_fetched_at 等）。

    Args:
        session: DB session。
        items: 解析後的列表職缺。
        matched: job_no → 命中之搜尋關鍵字集合。
        crawl_date: 本次爬取日期。
        tech_keywords: job_no → 以列表描述預先比對出的技術關鍵字。

    Returns:
        (新增職缺的 job_no 集合, 更新筆數)。
    """
    items = list(items)
    existing = get_existing_job_nos(session, [it.job_no for it in items])
    new_nos: set[str] = set()
    updated = 0

    for it in items:
        kw = sorted(matched.get(it.job_no, set()))
        if it.job_no in existing:
            job = session.get(Job, it.job_no)
            if job is None:  # pragma: no cover - 理論上不會發生
                continue
            job.last_seen_date = crawl_date
            job.apply_cnt = it.apply_cnt
            job.salary_low = it.salary_low
            job.salary_high = it.salary_high
            job.salary_type = it.salary_type
            job.job_name = it.job_name or job.job_name
            job.area_desc = it.area_desc or job.area_desc
            job.matched_keywords = sorted(set(job.matched_keywords or []) | set(kw))
            updated += 1
        else:
            session.add(
                Job(
                    job_no=it.job_no,
                    job_code=it.job_code,
                    job_url=it.job_url,
                    job_name=it.job_name,
                    cust_name=it.cust_name,
                    cust_no=it.cust_no,
                    area_desc=it.area_desc,
                    industry_desc=it.industry_desc,
                    salary_low=it.salary_low,
                    salary_high=it.salary_high,
                    salary_type=it.salary_type,
                    option_edu=list(it.option_edu),
                    period=it.period,
                    remote_work_type=it.remote_work_type,
                    job_cats=list(it.job_cats),
                    pc_skills=list(it.pc_skills),
                    description=it.description,
                    language_codes=list(it.language_codes),
                    apply_cnt=it.apply_cnt,
                    appear_date=it.appear_date,
                    matched_keywords=kw,
                    tech_keywords=list(tech_keywords.get(it.job_no, [])),
                    first_seen_date=crawl_date,
                    last_seen_date=crawl_date,
                )
            )
            new_nos.add(it.job_no)

    return new_nos, updated


def record_snapshots(
    session: Session,
    all_job_nos: Collection[str],
    new_job_nos: Collection[str],
    matched: dict[str, set[str]],
    snapshot_date: datetime.date,
) -> int:
    """記錄當日職缺快照（重跑安全：已存在的 (job_no, date) 不重複插入）。

    Returns:
        實際新插入的快照筆數。
    """
    existing = set(
        session.execute(
            select(JobDailySnapshot.job_no).where(
                JobDailySnapshot.snapshot_date == snapshot_date
            )
        ).scalars()
    )
    new_set = set(new_job_nos)
    inserted = 0
    for job_no in all_job_nos:
        if job_no in existing:
            continue
        session.add(
            JobDailySnapshot(
                job_no=job_no,
                snapshot_date=snapshot_date,
                is_new=job_no in new_set,
                matched_keywords=sorted(matched.get(job_no, set())),
            )
        )
        inserted += 1
    return inserted


def jobs_needing_detail(session: Session, limit: int) -> list[Job]:
    """取得尚未抓取詳細內容的職缺（新職缺優先）。"""
    if limit <= 0:
        return []
    return list(
        session.execute(
            select(Job)
            .where(Job.detail_fetched_at.is_(None))
            .order_by(Job.first_seen_date.desc(), Job.job_no)
            .limit(limit)
        ).scalars()
    )


def count_jobs_needing_detail(session: Session) -> int:
    """計算尚未抓取詳細內容的職缺數。"""
    return int(
        session.scalar(
            select(func.count()).select_from(Job).where(Job.detail_fetched_at.is_(None))
        )
        or 0
    )


def apply_detail(
    session: Session, job: Job, detail: JobDetail, tech_keywords: set[str]
) -> None:
    """將詳細內容套用至職缺主檔，並標記 detail_fetched_at。"""
    del session  # 介面保留 session 以利未來擴充；目前僅就地修改 ORM 物件
    if detail.job_description:
        job.description = detail.job_description
    job.other_condition = detail.other_condition
    job.skills = list(detail.skills)
    job.specialties = list(detail.specialties)
    job.edu_desc = detail.edu_desc or None
    job.work_exp_desc = detail.work_exp_desc or None
    job.salary_desc = detail.salary_desc or None
    if detail.salary_min:
        job.salary_low = detail.salary_min
    if detail.salary_max:
        job.salary_high = detail.salary_max
    job.job_cat_descs = list(detail.job_cat_descs)
    job.majors = list(detail.majors)
    job.certificates = list(detail.certificates)
    if detail.language_codes:
        job.language_codes = list(detail.language_codes)
    job.tech_keywords = sorted(tech_keywords)
    job.detail_fetched_at = utc_now()


def replace_daily_stats(
    session: Session, stat_date: datetime.date, rows: list[dict]
) -> None:
    """先刪後插某日統計（重跑安全）。"""
    session.execute(
        delete(DailySkillStat).where(DailySkillStat.stat_date == stat_date)
    )
    session.add_all(DailySkillStat(**row) for row in rows)


def upsert_daily_summary(
    session: Session,
    stat_date: datetime.date,
    total_jobs: int,
    new_jobs: int,
    detail_coverage: float,
    summary_text: str,
    stats_json: dict,
) -> DailySummary:
    """新增或更新某日總結。"""
    summary = session.get(DailySummary, stat_date)
    if summary is None:
        summary = DailySummary(stat_date=stat_date)
        session.add(summary)
    summary.total_jobs = total_jobs
    summary.new_jobs = new_jobs
    summary.detail_coverage = detail_coverage
    summary.summary_text = summary_text
    summary.stats_json = stats_json
    return summary


def get_summary(session: Session, stat_date: datetime.date) -> DailySummary | None:
    """取得某日總結。"""
    return session.get(DailySummary, stat_date)


def get_previous_summary(
    session: Session, stat_date: datetime.date
) -> DailySummary | None:
    """取得某日之前最近一筆總結（供跨日比較）。"""
    return session.execute(
        select(DailySummary)
        .where(DailySummary.stat_date < stat_date)
        .order_by(DailySummary.stat_date.desc())
        .limit(1)
    ).scalar_one_or_none()


def list_stat_dates(session: Session) -> list[datetime.date]:
    """列出所有有總結的日期（新到舊）。"""
    return list(
        session.execute(
            select(DailySummary.stat_date).order_by(DailySummary.stat_date.desc())
        ).scalars()
    )


def get_trend(session: Session, days: int) -> list[DailySummary]:
    """取得近 N 日總結（舊到新，供趨勢圖）。"""
    rows = list(
        session.execute(
            select(DailySummary).order_by(DailySummary.stat_date.desc()).limit(days)
        ).scalars()
    )
    return list(reversed(rows))


def query_jobs_by_date(
    session: Session,
    stat_date: datetime.date,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
) -> tuple[list[Job], int]:
    """分頁查詢某日快照中的職缺，可依職稱/公司名關鍵字過濾。

    Returns:
        (職缺列表, 總筆數)。
    """
    base = (
        select(Job)
        .join(JobDailySnapshot, JobDailySnapshot.job_no == Job.job_no)
        .where(JobDailySnapshot.snapshot_date == stat_date)
    )
    if q:
        pattern = f"%{q}%"
        base = base.where(
            or_(Job.job_name.ilike(pattern), Job.cust_name.ilike(pattern))
        )
    total = int(
        session.scalar(select(func.count()).select_from(base.subquery())) or 0
    )
    rows = list(
        session.execute(
            base.order_by(Job.apply_cnt.desc(), Job.job_no)
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        ).scalars()
    )
    return rows, total


def get_run_for_date(
    session: Session,
    run_date: datetime.date,
    statuses: tuple[str, ...] = ("success", "partial"),
) -> CrawlRun | None:
    """取得某日符合狀態的爬取紀錄（最新一筆）。"""
    return session.execute(
        select(CrawlRun)
        .where(CrawlRun.run_date == run_date, CrawlRun.status.in_(statuses))
        .order_by(CrawlRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_latest_run_for_date(
    session: Session, run_date: datetime.date
) -> CrawlRun | None:
    """取得某日最新一筆爬取紀錄（不限狀態）。"""
    return session.execute(
        select(CrawlRun)
        .where(CrawlRun.run_date == run_date)
        .order_by(CrawlRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
