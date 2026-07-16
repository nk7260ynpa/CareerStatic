"""每日統計彙整。

母體為 job_daily_snapshots 中某日的職缺集合；六個統計類別
（每職缺每項目只計一次）：

    specialty     擅長工具（列表 pcSkills 與詳細 specialties 聯集）
    skill         工作技能（僅詳細內容提供，受 detail 涵蓋率影響）
    tech_keyword  內文技術關鍵字（字典比對）
    education     學歷門檻（每職缺恰一值）
    experience    經歷要求（每職缺恰一值）
    language      語言要求
"""

import datetime
import logging
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from careerstatic.analyzer.code_maps import edu_level, experience_level, language_names
from careerstatic.db import repository
from careerstatic.db.models import Job, JobDailySnapshot

logger = logging.getLogger(__name__)

CATEGORIES = (
    "specialty",
    "skill",
    "tech_keyword",
    "education",
    "experience",
    "language",
)


def compute_daily_stats(
    session: Session, stat_date: datetime.date, top_n: int = 100
) -> dict:
    """計算某日統計並寫入 daily_skill_stats（先刪後插，可重跑）。

    Args:
        session: DB session（呼叫端負責 commit）。
        stat_date: 統計日期。
        top_n: 每類別入庫的項目數上限。

    Returns:
        統計結果 dict：total_jobs、new_jobs、detail_coverage、
        by_category（類別 → [(名稱, 職缺數), …] 依數量降冪）。
    """
    rows = session.execute(
        select(Job, JobDailySnapshot.is_new)
        .join(JobDailySnapshot, JobDailySnapshot.job_no == Job.job_no)
        .where(JobDailySnapshot.snapshot_date == stat_date)
    ).all()

    total = len(rows)
    new_jobs = sum(1 for _, is_new in rows if is_new)
    with_detail = sum(1 for job, _ in rows if job.detail_fetched_at is not None)

    counters: dict[str, Counter] = {cat: Counter() for cat in CATEGORIES}
    for job, _ in rows:
        specialties = set(job.pc_skills or []) | set(job.specialties or [])
        for name in specialties:
            counters["specialty"][name] += 1
        for name in set(job.skills or []):
            counters["skill"][name] += 1
        for name in set(job.tech_keywords or []):
            counters["tech_keyword"][name] += 1
        counters["education"][edu_level(job.option_edu)] += 1
        counters["experience"][
            experience_level(job.period or 0, job.work_exp_desc)
        ] += 1
        for name in set(language_names(job.language_codes)):
            counters["language"][name] += 1

    stat_rows: list[dict] = []
    by_category: dict[str, list[tuple[str, int]]] = {}
    for category, counter in counters.items():
        ranked = counter.most_common(top_n)
        by_category[category] = ranked
        for rank, (name, count) in enumerate(ranked, start=1):
            stat_rows.append(
                {
                    "stat_date": stat_date,
                    "category": category,
                    "item_name": name[:200],
                    "job_count": count,
                    "ratio": (count / total) if total else 0.0,
                    "rank": rank,
                }
            )

    repository.replace_daily_stats(session, stat_date, stat_rows)
    logger.info(
        "已計算 %s 統計：%d 筆職缺、%d 筆新職缺、detail 涵蓋率 %.1f%%",
        stat_date,
        total,
        new_jobs,
        (with_detail / total * 100) if total else 0.0,
    )

    return {
        "stat_date": stat_date,
        "total_jobs": total,
        "new_jobs": new_jobs,
        "detail_coverage": (with_detail / total) if total else 0.0,
        "by_category": by_category,
    }
