"""analyzer（關鍵字比對、代碼對照、每日統計）的單元測試。"""

import datetime

from careerstatic.analyzer.code_maps import (
    edu_level,
    experience_level,
    format_salary,
    language_names,
)
from careerstatic.analyzer.stats import compute_daily_stats
from careerstatic.analyzer.tech_keywords import match_keywords
from careerstatic.db.models import DailySkillStat, Job, JobDailySnapshot

TEST_DATE = datetime.date(2026, 7, 16)


class TestMatchKeywords:
    def test_basic_match(self):
        result = match_keywords("熟悉 Python 與 PyTorch，具備深度學習經驗")
        assert {"Python", "PyTorch", "深度學習"} <= result

    def test_java_not_javascript(self):
        assert "Java" not in match_keywords("JavaScript 前端開發")
        assert "JavaScript" in match_keywords("JavaScript 前端開發")
        assert "Java" in match_keywords("Java 後端開發")

    def test_symbol_languages(self):
        result = match_keywords("需要 C++ 與 C# 開發經驗")
        assert "C++" in result
        assert "C#" in result

    def test_go_requires_golang(self):
        assert "Go" in match_keywords("熟悉 Golang 開發")
        assert "Go" in match_keywords("熟悉 Go 語言")
        assert "Go" not in match_keywords("Go to our website for details")

    def test_case_insensitive_and_variants(self):
        assert "機器學習" in match_keywords("MACHINE LEARNING engineer")
        assert "機器學習" in match_keywords("machine-learning pipeline")
        assert "scikit-learn" in match_keywords("使用 sklearn 建模")

    def test_llm_ecosystem(self):
        result = match_keywords("使用 LangChain 開發 LLM 應用，熟悉 RAG 與提示工程")
        assert {"LangChain", "LLM", "RAG", "Prompt Engineering"} <= result

    def test_sql_not_matched_in_mysql(self):
        result = match_keywords("熟悉 MySQL 資料庫")
        assert "MySQL" in result
        assert "SQL" not in result  # \b 邊界：mysql 不應命中獨立的 SQL

    def test_git_not_github(self):
        assert "Git" not in match_keywords("GitHub Actions 部署")
        assert "Git" in match_keywords("熟悉 Git 版本控制")

    def test_empty_text(self):
        assert match_keywords("") == set()

    def test_returns_deduplicated_set(self):
        result = match_keywords("Python python PYTHON")
        assert result == {"Python"}


class TestCodeMaps:
    def test_edu_level_verified_mapping(self):
        # 已以真實 detail 文字交叉驗證：[4,5,6] ↔ 大學以上
        assert edu_level([4, 5, 6]) == "大學"
        assert edu_level([3, 4, 5]) == "專科"
        assert edu_level([1, 2, 3, 4, 5]) == "高中以下"
        assert edu_level([]) == "不拘"
        assert edu_level(None) == "不拘"

    def test_edu_level_unknown_code(self):
        assert edu_level([99]) == "代碼99"

    def test_experience_level_prefers_detail_text(self):
        assert experience_level(2, "3年以上") == "3年以上"
        assert experience_level(0, None) == "不拘"
        assert experience_level(2, None) == "1年以上"  # 已實測 period=2 ↔ 1年以上
        assert experience_level(7, None) == "代碼7"

    def test_language_names(self):
        assert language_names([1, 18]) == ["英文", "中文"]
        assert language_names([99]) == ["語言代碼99"]
        assert language_names(None) == []

    def test_format_salary(self):
        assert format_salary("月薪 50,000 元", 0, 0, 50) == "月薪 50,000 元"
        assert format_salary(None, 0, 0, 10) == "待遇面議"
        assert format_salary(None, 40000, 60000, 50) == "月薪 40,000～60,000 元"
        assert format_salary(None, 40000, 9999999, 50) == "月薪 40,000 元以上"


def add_job(session, job_no, *, is_new=False, **fields):
    """建立職缺與當日快照的測試小工具。"""
    defaults = {
        "job_no": job_no,
        "first_seen_date": TEST_DATE,
        "last_seen_date": TEST_DATE,
        "pc_skills": [],
        "tech_keywords": [],
        "option_edu": [4, 5],
        "period": 0,
        "language_codes": [],
    }
    defaults.update(fields)
    session.add(Job(**defaults))
    session.add(
        JobDailySnapshot(job_no=job_no, snapshot_date=TEST_DATE, is_new=is_new)
    )


class TestComputeDailyStats:
    def test_counts_ratio_rank(self, session):
        add_job(session, "1", is_new=True, pc_skills=["Python", "Git"],
                tech_keywords=["Python", "LLM"])
        add_job(session, "2", pc_skills=["Python"], tech_keywords=["Python"],
                specialties=["PyTorch"], skills=["軟體程式設計"],
                detail_fetched_at=datetime.datetime.now(datetime.timezone.utc),
                work_exp_desc="2年以上", language_codes=[1])
        add_job(session, "3", option_edu=[3, 4], period=2)
        session.commit()

        stats = compute_daily_stats(session, TEST_DATE, top_n=50)
        session.commit()

        assert stats["total_jobs"] == 3
        assert stats["new_jobs"] == 1
        assert abs(stats["detail_coverage"] - 1 / 3) < 1e-9

        by_cat = stats["by_category"]
        assert by_cat["specialty"][0] == ("Python", 2)
        assert ("PyTorch", 1) in by_cat["specialty"]
        assert by_cat["tech_keyword"][0] == ("Python", 2)
        assert dict(by_cat["education"]) == {"大學": 2, "專科": 1}
        assert dict(by_cat["experience"]) == {"不拘": 1, "2年以上": 1, "1年以上": 1}
        assert dict(by_cat["language"]) == {"英文": 1}

        # 已入庫且 rank / ratio 正確
        row = (
            session.query(DailySkillStat)
            .filter_by(stat_date=TEST_DATE, category="specialty", item_name="Python")
            .one()
        )
        assert row.job_count == 2
        assert row.rank == 1
        assert abs(row.ratio - 2 / 3) < 1e-9

    def test_rerun_replaces_stats(self, session):
        add_job(session, "1", pc_skills=["Python"])
        session.commit()
        compute_daily_stats(session, TEST_DATE)
        compute_daily_stats(session, TEST_DATE)
        session.commit()

        rows = (
            session.query(DailySkillStat)
            .filter_by(stat_date=TEST_DATE, category="specialty")
            .all()
        )
        assert len(rows) == 1

    def test_empty_day(self, session):
        stats = compute_daily_stats(session, TEST_DATE)
        assert stats["total_jobs"] == 0
        assert stats["detail_coverage"] == 0.0
