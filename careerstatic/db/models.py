"""ORM 模型定義（SQLAlchemy 2.x）。

JSON 欄位一律使用 JSONVariant：PostgreSQL 用 JSONB、SQLite 落回一般
JSON（TEXT），確保測試（SQLite）與正式環境（PostgreSQL）行為一致。
"""

import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from careerstatic.db.base import Base

JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Job(Base):
    """職缺主檔：每個 104 職缺一筆，存最新狀態。

    列表 API 提供基本欄位；詳細 API 補齊 skills / specialties /
    完整描述等欄位（detail_fetched_at 為 NULL 表示尚未抓取詳細內容）。
    """

    __tablename__ = "jobs"

    job_no: Mapped[str] = mapped_column(String(20), primary_key=True)
    job_code: Mapped[str] = mapped_column(String(20), index=True, default="")
    job_url: Mapped[str] = mapped_column(String(255), default="")
    job_name: Mapped[str] = mapped_column(String(255), default="")
    cust_name: Mapped[str] = mapped_column(String(255), default="")
    cust_no: Mapped[str] = mapped_column(String(20), default="")
    area_desc: Mapped[str] = mapped_column(String(50), default="")
    industry_desc: Mapped[str] = mapped_column(String(100), default="")

    salary_low: Mapped[int] = mapped_column(Integer, default=0)
    salary_high: Mapped[int] = mapped_column(Integer, default=0)
    salary_type: Mapped[int] = mapped_column(Integer, default=0)
    salary_desc: Mapped[str | None] = mapped_column(String(100), nullable=True)

    option_edu: Mapped[list] = mapped_column(JSONVariant, default=list)
    edu_desc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    period: Mapped[int] = mapped_column(Integer, default=0)
    work_exp_desc: Mapped[str | None] = mapped_column(String(50), nullable=True)
    remote_work_type: Mapped[int] = mapped_column(Integer, default=0)

    job_cats: Mapped[list] = mapped_column(JSONVariant, default=list)
    job_cat_descs: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    pc_skills: Mapped[list] = mapped_column(JSONVariant, default=list)
    specialties: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    skills: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)

    description: Mapped[str] = mapped_column(Text, default="")
    other_condition: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_codes: Mapped[list] = mapped_column(JSONVariant, default=list)
    majors: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)
    certificates: Mapped[list | None] = mapped_column(JSONVariant, nullable=True)

    apply_cnt: Mapped[int] = mapped_column(Integer, default=0)
    appear_date: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)

    matched_keywords: Mapped[list] = mapped_column(JSONVariant, default=list)
    tech_keywords: Mapped[list] = mapped_column(JSONVariant, default=list)

    first_seen_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    last_seen_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    detail_fetched_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class JobDailySnapshot(Base):
    """每日職缺快照：記錄「哪些職缺在哪一天出現」。

    每日統計的母體即為當日快照集合；同一職缺跨多日出現時，
    每天各有一筆快照。
    """

    __tablename__ = "job_daily_snapshots"
    __table_args__ = (
        UniqueConstraint("job_no", "snapshot_date", name="uq_snapshot_job_date"),
        Index("ix_snapshot_date", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_no: Mapped[str] = mapped_column(String(20), ForeignKey("jobs.job_no"))
    snapshot_date: Mapped[datetime.date] = mapped_column(Date)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)
    matched_keywords: Mapped[list] = mapped_column(JSONVariant, default=list)


class CrawlRun(Base):
    """每次爬取執行紀錄。"""

    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_date: Mapped[datetime.date] = mapped_column(Date, index=True)
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="running")
    keywords: Mapped[list] = mapped_column(JSONVariant, default=list)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    jobs_seen: Mapped[int] = mapped_column(Integer, default=0)
    jobs_new: Mapped[int] = mapped_column(Integer, default=0)
    details_fetched: Mapped[int] = mapped_column(Integer, default=0)
    details_pending: Mapped[int] = mapped_column(Integer, default=0)
    truncated_keywords: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DailySkillStat(Base):
    """每日技能統計：某日某類別下各項目的職缺數與排名。"""

    __tablename__ = "daily_skill_stats"
    __table_args__ = (
        UniqueConstraint(
            "stat_date", "category", "item_name", name="uq_stats_date_cat_item"
        ),
        Index("ix_stats_date_cat", "stat_date", "category"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stat_date: Mapped[datetime.date] = mapped_column(Date)
    category: Mapped[str] = mapped_column(String(20))
    item_name: Mapped[str] = mapped_column(String(200))
    job_count: Mapped[int] = mapped_column(Integer, default=0)
    ratio: Mapped[float] = mapped_column(Float, default=0.0)
    rank: Mapped[int] = mapped_column(Integer, default=0)


class DailySummary(Base):
    """每日總結：總數、新增數、繁中總結文字與前端用統計快照。"""

    __tablename__ = "daily_summaries"

    stat_date: Mapped[datetime.date] = mapped_column(Date, primary_key=True)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    detail_coverage: Mapped[float] = mapped_column(Float, default=0.0)
    summary_text: Mapped[str] = mapped_column(Text, default="")
    stats_json: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
