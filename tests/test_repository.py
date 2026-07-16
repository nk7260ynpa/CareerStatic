"""db.repository 的單元測試（SQLite in-memory）。"""

import datetime

from careerstatic.crawler.parser import JobDetail, JobListItem
from careerstatic.db import repository
from careerstatic.db.models import Job, JobDailySnapshot

D1 = datetime.date(2026, 7, 15)
D2 = datetime.date(2026, 7, 16)


def make_item(job_no: str, **overrides) -> JobListItem:
    """建立測試用列表職缺。"""
    fields = {
        "job_no": job_no,
        "job_code": f"c{job_no}",
        "job_url": f"https://www.104.com.tw/job/c{job_no}",
        "job_name": "AI 工程師",
        "cust_name": "測試公司",
        "area_desc": "台北市",
        "pc_skills": ["Python"],
        "option_edu": [4, 5],
        "apply_cnt": 3,
    }
    fields.update(overrides)
    return JobListItem(**fields)


def upsert(session, items, date, matched=None):
    """簡化呼叫的小工具。"""
    matched = matched or {it.job_no: {"AI"} for it in items}
    new_nos, updated = repository.upsert_jobs_from_list(
        session, items, matched, date, {it.job_no: ["Python"] for it in items}
    )
    session.commit()
    return new_nos, updated


class TestUpsertJobs:
    def test_insert_then_update(self, session):
        new_nos, updated = upsert(session, [make_item("1")], D1)
        assert new_nos == {"1"}
        assert updated == 0

        new_nos, updated = upsert(session, [make_item("1", apply_cnt=9)], D2)
        assert new_nos == set()
        assert updated == 1

        job = session.get(Job, "1")
        assert job.first_seen_date == D1
        assert job.last_seen_date == D2
        assert job.apply_cnt == 9

    def test_detail_fields_not_overwritten(self, session):
        upsert(session, [make_item("1")], D1)
        job = session.get(Job, "1")
        detail = JobDetail(
            job_description="完整描述",
            skills=["軟體程式設計"],
            specialties=["Python", "PyTorch"],
            work_exp_desc="2年以上",
            edu_desc="大學以上",
            salary_desc="月薪 60,000 元以上",
        )
        repository.apply_detail(session, job, detail, {"Python", "PyTorch"})
        session.commit()

        # 隔日再以列表資料 upsert，不得覆寫詳細來源欄位
        upsert(session, [make_item("1", description="列表簡述")], D2)
        job = session.get(Job, "1")
        assert job.description == "完整描述"
        assert job.skills == ["軟體程式設計"]
        assert job.specialties == ["Python", "PyTorch"]
        assert job.detail_fetched_at is not None

    def test_matched_keywords_union(self, session):
        upsert(session, [make_item("1")], D1, matched={"1": {"AI"}})
        upsert(session, [make_item("1")], D2, matched={"1": {"機器學習"}})
        job = session.get(Job, "1")
        assert set(job.matched_keywords) == {"AI", "機器學習"}


class TestSnapshots:
    def test_record_and_rerun_safe(self, session):
        upsert(session, [make_item("1"), make_item("2")], D1)
        inserted = repository.record_snapshots(
            session, {"1", "2"}, {"1"}, {"1": {"AI"}, "2": {"AI"}}, D1
        )
        session.commit()
        assert inserted == 2

        # 重跑同日不重複插入
        inserted = repository.record_snapshots(
            session, {"1", "2"}, set(), {}, D1
        )
        session.commit()
        assert inserted == 0

        rows = session.query(JobDailySnapshot).filter_by(snapshot_date=D1).all()
        assert len(rows) == 2
        flags = {row.job_no: row.is_new for row in rows}
        assert flags == {"1": True, "2": False}


class TestJobsNeedingDetail:
    def test_order_and_limit(self, session):
        upsert(session, [make_item("1")], D1)
        upsert(session, [make_item("2"), make_item("3")], D2)

        # 標記其中一筆已抓取
        job3 = session.get(Job, "3")
        repository.apply_detail(session, job3, JobDetail(), set())
        session.commit()

        pending = repository.jobs_needing_detail(session, limit=10)
        assert [job.job_no for job in pending] == ["2", "1"]  # 新職缺優先

        assert len(repository.jobs_needing_detail(session, limit=1)) == 1
        assert repository.count_jobs_needing_detail(session) == 2


class TestSummaries:
    def test_upsert_and_queries(self, session):
        repository.upsert_daily_summary(
            session, D1, total_jobs=10, new_jobs=10, detail_coverage=0.5,
            summary_text="前日總結", stats_json={"by_category": {}},
        )
        repository.upsert_daily_summary(
            session, D2, total_jobs=12, new_jobs=2, detail_coverage=0.6,
            summary_text="今日總結", stats_json={"by_category": {}},
        )
        session.commit()

        assert repository.get_summary(session, D2).total_jobs == 12
        assert repository.get_previous_summary(session, D2).stat_date == D1
        assert repository.get_previous_summary(session, D1) is None
        assert repository.list_stat_dates(session) == [D2, D1]

        trend = repository.get_trend(session, days=30)
        assert [row.stat_date for row in trend] == [D1, D2]

    def test_upsert_updates_existing(self, session):
        repository.upsert_daily_summary(
            session, D1, total_jobs=1, new_jobs=1, detail_coverage=0.0,
            summary_text="v1", stats_json={},
        )
        repository.upsert_daily_summary(
            session, D1, total_jobs=5, new_jobs=0, detail_coverage=1.0,
            summary_text="v2", stats_json={},
        )
        session.commit()
        summary = repository.get_summary(session, D1)
        assert summary.total_jobs == 5
        assert summary.summary_text == "v2"


class TestQueryJobsByDate:
    def test_filter_and_pagination(self, session):
        items = [make_item(str(i), apply_cnt=i) for i in range(1, 6)]
        items.append(make_item("99", job_name="資料科學家", cust_name="數據公司"))
        upsert(session, items, D1)
        repository.record_snapshots(
            session, {it.job_no for it in items}, set(), {}, D1
        )
        session.commit()

        jobs, total = repository.query_jobs_by_date(session, D1, page=1, page_size=3)
        assert total == 6
        assert len(jobs) == 3

        jobs, total = repository.query_jobs_by_date(session, D1, q="資料科學")
        assert total == 1
        assert jobs[0].job_no == "99"

        jobs, total = repository.query_jobs_by_date(session, D2)
        assert total == 0
