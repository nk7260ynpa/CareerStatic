"""crawler.pipeline 的端到端測試（FakeClient + SQLite）。"""

import datetime

import pytest

from careerstatic.crawler.client import CrawlError
from careerstatic.crawler.pipeline import run_daily_crawl
from careerstatic.db.models import CrawlRun, DailySummary, Job, JobDailySnapshot

TEST_DATE = datetime.date(2026, 7, 16)


class FakeClient:
    """以 fixtures 餵資料的假客戶端。"""

    def __init__(self, list_fixture, detail_fixture, fail_details=False):
        self.page = (list_fixture["data"], list_fixture["metadata"]["pagination"])
        self.detail = detail_fixture
        self.fail_details = fail_details
        self.detail_calls = 0

    def iter_search(self, keyword, max_pages):
        del keyword, max_pages
        yield self.page

    def fetch_job_detail(self, job_code):
        self.detail_calls += 1
        if self.fail_details:
            raise CrawlError(f"模擬失敗：{job_code}")
        return self.detail


def run(session_factory, settings, client, **kwargs):
    kwargs.setdefault("crawl_date", TEST_DATE)
    kwargs.setdefault("trigger", "manual")
    return run_daily_crawl(session_factory, client, settings, **kwargs)


class TestRunDailyCrawl:
    def test_end_to_end(self, session_factory, test_settings, list_fixture, detail_fixture):
        client = FakeClient(list_fixture, detail_fixture)
        result = run(session_factory, test_settings, client)

        assert result.status == "success"
        assert result.jobs_seen == 3  # 兩個關鍵字回同一頁 → 以 jobNo 去重
        assert result.jobs_new == 3
        assert result.details_fetched == 3
        assert result.details_pending == 0

        session = session_factory()
        try:
            assert session.query(Job).count() == 3
            snapshots = session.query(JobDailySnapshot).all()
            assert len(snapshots) == 3
            assert all(s.is_new for s in snapshots)
            # 詳細內容已套用
            job = session.query(Job).filter_by(job_no="10122490").one()
            assert job.detail_fetched_at is not None
            assert job.skills  # detail fixture 的工作技能
            # 每個 job 命中兩個關鍵字
            assert set(job.matched_keywords) == {"AI", "機器學習"}
            # 統計與總結已產生
            summary = session.get(DailySummary, TEST_DATE)
            assert summary is not None
            assert summary.total_jobs == 3
            assert "AI 職缺技能日報" in summary.summary_text
            run_row = session.query(CrawlRun).order_by(CrawlRun.id.desc()).first()
            assert run_row.status == "success"
            assert run_row.jobs_seen == 3
        finally:
            session.close()

    def test_detail_limit(self, session_factory, test_settings, list_fixture, detail_fixture):
        client = FakeClient(list_fixture, detail_fixture)
        result = run(session_factory, test_settings, client, detail_limit=1)

        assert result.details_fetched == 1
        assert result.details_pending == 2

    def test_details_only_mode(self, session_factory, test_settings, list_fixture, detail_fixture):
        client = FakeClient(list_fixture, detail_fixture)
        run(session_factory, test_settings, client, detail_limit=0)

        # 第二輪只補詳細內容，不重爬列表
        client2 = FakeClient(list_fixture, detail_fixture)
        result = run(session_factory, test_settings, client2, details_only=True)

        assert result.jobs_seen == 0
        assert result.details_fetched == 3
        session = session_factory()
        try:
            assert session.query(Job).count() == 3
            # 統計已依補抓後資料重算
            summary = session.get(DailySummary, TEST_DATE)
            assert summary.detail_coverage == 1.0
        finally:
            session.close()

    def test_rerun_same_day_idempotent(self, session_factory, test_settings, list_fixture, detail_fixture):
        run(session_factory, test_settings, FakeClient(list_fixture, detail_fixture))
        result = run(session_factory, test_settings, FakeClient(list_fixture, detail_fixture))

        assert result.jobs_new == 0  # 第二輪無新職缺
        session = session_factory()
        try:
            assert session.query(Job).count() == 3
            assert session.query(JobDailySnapshot).count() == 3
        finally:
            session.close()

    def test_blocked_marks_partial(
        self, session_factory, test_settings, list_fixture, detail_fixture, monkeypatch
    ):
        monkeypatch.setattr(
            "careerstatic.crawler.pipeline.MAX_CONSECUTIVE_DETAIL_FAILURES", 2
        )
        client = FakeClient(list_fixture, detail_fixture, fail_details=True)
        result = run(session_factory, test_settings, client)

        assert result.status == "partial"
        assert "中止" in (result.error_message or "")
        session = session_factory()
        try:
            run_row = session.query(CrawlRun).order_by(CrawlRun.id.desc()).first()
            assert run_row.status == "partial"
            # 列表資料仍已入庫、統計仍已產生
            assert session.query(Job).count() == 3
            assert session.get(DailySummary, TEST_DATE) is not None
        finally:
            session.close()

    def test_list_failure_marks_failed(self, session_factory, test_settings):
        class BrokenClient:
            def iter_search(self, keyword, max_pages):
                raise CrawlError("模擬列表失敗")
                yield  # pragma: no cover

            def fetch_job_detail(self, job_code):  # pragma: no cover
                raise CrawlError("不應被呼叫")

        result = run(session_factory, test_settings, BrokenClient())
        assert result.status == "failed"
        session = session_factory()
        try:
            run_row = session.query(CrawlRun).order_by(CrawlRun.id.desc()).first()
            assert run_row.status == "failed"
            assert run_row.error_message
        finally:
            session.close()


class TestTruncationDetection:
    def test_truncated_keyword_recorded(
        self, session_factory, test_settings, list_fixture, detail_fixture
    ):
        class TruncatedClient(FakeClient):
            def iter_search(self, keyword, max_pages):
                items, _ = self.page
                # 模擬 API 上限：lastPage=150、total 遠大於實際取樣
                yield items, {"currentPage": 1, "lastPage": 150, "total": 25012}

        client = TruncatedClient(list_fixture, detail_fixture)
        result = run(session_factory, test_settings, client, detail_limit=0)

        assert "AI" in result.truncated_keywords
        info = result.truncated_keywords["AI"]
        assert info["total"] == 25012
        session = session_factory()
        try:
            summary = session.get(DailySummary, TEST_DATE)
            assert "取樣" in summary.summary_text
        finally:
            session.close()
