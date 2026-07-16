"""web 層（FastAPI 路由）的單元測試。"""

import datetime

from careerstatic import scheduler
from careerstatic.db import repository
from careerstatic.db.models import Job, JobDailySnapshot

TEST_DATE = datetime.date(2026, 7, 16)


def seed_summary(session_factory, stat_date=TEST_DATE):
    """塞入一筆總結供 API 測試。"""
    session = session_factory()
    try:
        repository.upsert_daily_summary(
            session,
            stat_date,
            total_jobs=42,
            new_jobs=7,
            detail_coverage=0.9,
            summary_text="測試總結",
            stats_json={"by_category": {"specialty": [
                {"name": "Python", "count": 30, "ratio": 0.71, "rank": 1, "rank_delta": None}
            ]}},
        )
        session.commit()
    finally:
        session.close()


class TestPages:
    def test_dashboard_page(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'lang="zh-Hant"' in resp.text
        assert "CareerStatic" in resp.text
        assert "104 AI 職缺技能儀表板" in resp.text

    def test_healthz(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestApiDates:
    def test_empty(self, client):
        assert client.get("/api/dates").json() == {"dates": []}

    def test_with_data(self, client, session_factory):
        seed_summary(session_factory)
        assert client.get("/api/dates").json() == {"dates": ["2026-07-16"]}


class TestApiSummary:
    def test_not_found(self, client):
        resp = client.get("/api/summary", params={"date": "2026-01-01"})
        assert resp.status_code == 404

    def test_ok(self, client, session_factory):
        seed_summary(session_factory)
        resp = client.get("/api/summary", params={"date": "2026-07-16"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_jobs"] == 42
        assert data["new_jobs"] == 7
        assert data["summary_text"] == "測試總結"
        assert data["categories"]["specialty"][0]["name"] == "Python"

    def test_invalid_date(self, client):
        resp = client.get("/api/summary", params={"date": "不是日期"})
        assert resp.status_code == 422


class TestApiTrend:
    def test_trend(self, client, session_factory):
        seed_summary(session_factory, datetime.date(2026, 7, 15))
        seed_summary(session_factory, TEST_DATE)
        data = client.get("/api/trend", params={"days": 30}).json()
        assert data["dates"] == ["2026-07-15", "2026-07-16"]
        assert len(data["total_jobs"]) == 2


class TestApiJobs:
    def test_jobs_list(self, client, session_factory):
        session = session_factory()
        try:
            session.add(
                Job(
                    job_no="1",
                    job_name="AI 工程師",
                    cust_name="測試公司",
                    area_desc="台北市",
                    job_url="https://www.104.com.tw/job/abc",
                    salary_low=50000,
                    salary_high=70000,
                    salary_type=50,
                    tech_keywords=["Python", "LLM"],
                    first_seen_date=TEST_DATE,
                    last_seen_date=TEST_DATE,
                )
            )
            session.add(JobDailySnapshot(job_no="1", snapshot_date=TEST_DATE))
            session.commit()
        finally:
            session.close()

        data = client.get(
            "/api/jobs", params={"date": "2026-07-16", "page": 1}
        ).json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["job_name"] == "AI 工程師"
        assert item["salary_text"] == "月薪 50,000～70,000 元"
        assert item["tech_keywords"] == ["Python", "LLM"]


class TestApiCrawl:
    def test_accepted(self, client, monkeypatch):
        calls = {}

        def fake_run(**kwargs):
            calls.update(kwargs)
            return True

        monkeypatch.setattr(scheduler, "run_crawl_locked", fake_run)
        resp = client.post("/api/crawl", json={"max_pages": 2})
        assert resp.status_code == 202
        assert resp.json() == {"status": "started"}

    def test_conflict_when_locked(self, client):
        assert scheduler.CRAWL_LOCK.acquire(blocking=False)
        try:
            resp = client.post("/api/crawl", json={})
            assert resp.status_code == 409
        finally:
            scheduler.CRAWL_LOCK.release()
