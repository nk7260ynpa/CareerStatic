"""analyzer.summary 繁中總結文字的單元測試。"""

import datetime

from careerstatic.analyzer.summary import build_stats_json, summarize_day
from careerstatic.db import repository

TEST_DATE = datetime.date(2026, 7, 16)
PREV_DATE = datetime.date(2026, 7, 15)


def make_stats(total=100, new=10, coverage=0.8, tech_keyword=None):
    return {
        "stat_date": TEST_DATE,
        "total_jobs": total,
        "new_jobs": new,
        "detail_coverage": coverage,
        "by_category": {
            "specialty": [("Python", 60), ("SQL", 40)],
            "skill": [("軟體程式設計", 30)],
            "tech_keyword": tech_keyword or [("Python", 70), ("LLM", 50), ("Docker", 30)],
            "education": [("大學", 55), ("碩士", 30), ("不拘", 15)],
            "experience": [("不拘", 40), ("2年以上", 35)],
            "language": [("英文", 45)],
        },
    }


class TestSummarizeDay:
    def test_contains_key_numbers(self, session):
        text = summarize_day(session, TEST_DATE, make_stats())
        session.commit()

        assert "2026-07-16 AI 職缺技能日報" in text
        assert "100 筆" in text
        assert "新增 10 筆" in text
        assert "Python（60 筆，60.0%）" in text
        assert "學歷門檻分布" in text
        assert "詳細資料涵蓋率 80.0%" in text
        # 前日無資料 → 不含比較句
        assert "較前日" not in text

        summary = repository.get_summary(session, TEST_DATE)
        assert summary.total_jobs == 100
        assert summary.stats_json["by_category"]["specialty"][0]["name"] == "Python"

    def test_day_over_day_comparison(self, session):
        summarize_day(
            session,
            PREV_DATE,
            {
                "stat_date": PREV_DATE,
                "total_jobs": 90,
                "new_jobs": 90,
                "detail_coverage": 0.5,
                "by_category": {
                    "tech_keyword": [
                        ("Docker", 40),
                        ("Python", 35),
                        ("RAG", 25),
                        ("LLM", 20),
                    ]
                },
            },
        )
        session.commit()

        # 今日 LLM 從第 4 名升到第 2 名（上升 ≥2 名才會出現在總結）
        text = summarize_day(session, TEST_DATE, make_stats())
        session.commit()

        assert "較前日（2026-07-15）增加 10 筆" in text
        assert "上升" in text  # 排名變化句

    def test_truncation_note(self, session):
        text = summarize_day(
            session,
            TEST_DATE,
            make_stats(),
            truncated_keywords={"AI": {"total": 25012, "sampled": 3300}},
        )
        assert "關鍵字「AI」" in text
        assert "3,300／25,012" in text

    def test_rerun_updates_summary(self, session):
        summarize_day(session, TEST_DATE, make_stats(total=100))
        session.commit()
        summarize_day(session, TEST_DATE, make_stats(total=120))
        session.commit()
        assert repository.get_summary(session, TEST_DATE).total_jobs == 120


class TestBuildStatsJson:
    def test_rank_delta(self, session):
        summarize_day(
            session,
            PREV_DATE,
            {
                "stat_date": PREV_DATE,
                "total_jobs": 50,
                "new_jobs": 50,
                "detail_coverage": 1.0,
                "by_category": {"tech_keyword": [("Docker", 30), ("LLM", 10)]},
            },
        )
        session.commit()
        previous = repository.get_summary(session, PREV_DATE)

        stats_json = build_stats_json(
            make_stats(tech_keyword=[("LLM", 40), ("Docker", 20)]), previous
        )
        items = {item["name"]: item for item in stats_json["by_category"]["tech_keyword"]}
        assert items["LLM"]["rank_delta"] == 1  # 第 2 → 第 1
        assert items["Docker"]["rank_delta"] == -1
        # 前日沒有的項目 rank_delta 為 None
        stats_json2 = build_stats_json(
            make_stats(tech_keyword=[("RAG", 40)]), previous
        )
        assert stats_json2["by_category"]["tech_keyword"][0]["rank_delta"] is None
