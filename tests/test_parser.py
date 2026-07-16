"""crawler.parser 的單元測試（以真實 API 回應 fixtures 驗證）。"""

import datetime

from careerstatic.crawler.parser import (
    extract_job_code,
    parse_job_detail,
    parse_list_item,
)


class TestExtractJobCode:
    def test_full_url_with_query(self):
        assert extract_job_code("https://www.104.com.tw/job/60yka?jobsource=x") == "60yka"

    def test_protocol_relative_url(self):
        assert extract_job_code("//www.104.com.tw/job/85wr8") == "85wr8"

    def test_trailing_slash(self):
        assert extract_job_code("https://www.104.com.tw/job/abc12/") == "abc12"

    def test_empty(self):
        assert extract_job_code("") == ""


class TestParseListItem:
    def test_basic_fields(self, list_fixture):
        item = parse_list_item(list_fixture["data"][0])
        assert item.job_no == "10122490"
        assert item.job_code == "60yka"
        assert item.job_url.startswith("https://")
        assert "教育顧問" in item.job_name
        assert item.cust_name
        assert item.area_desc == "台中市南區"
        assert item.salary_low == 70000
        assert item.salary_high == 150000
        assert item.option_edu == [4, 5, 6]

    def test_language_codes(self, list_fixture):
        item = parse_list_item(list_fixture["data"][0])
        # 實測第一筆含英文（1）與中文（18）語言要求
        assert 1 in item.language_codes
        assert 18 in item.language_codes

    def test_pc_skills(self, list_fixture):
        item = parse_list_item(list_fixture["data"][2])
        assert "Python" in item.pc_skills
        assert "Git" in item.pc_skills

    def test_period(self, list_fixture):
        item = parse_list_item(list_fixture["data"][1])
        assert item.period == 2

    def test_missing_fields_fail_soft(self):
        item = parse_list_item({})
        assert item.job_no == ""
        assert item.pc_skills == []
        assert item.salary_low == 0
        assert item.appear_date is None


class TestParseJobDetail:
    def test_condition_fields(self, detail_fixture):
        detail = parse_job_detail(detail_fixture)
        assert "AI" in detail.skills
        # 此職缺 period=2，對照 detail 文字為「1年以上」（代碼≠年數的實證）
        assert detail.work_exp_desc == "1年以上"
        # 與列表 optionEdu=[3,4,5] 交叉一致（3=專科、4=大學、5=碩士）
        assert detail.edu_desc == "專科、大學、碩士"

    def test_job_detail_fields(self, detail_fixture):
        detail = parse_job_detail(detail_fixture)
        assert detail.salary_desc == "待遇面議"
        assert len(detail.job_description) > 100
        assert "AI工程師" in detail.job_cat_descs

    def test_missing_data_fail_soft(self):
        detail = parse_job_detail({})
        assert detail.skills == []
        assert detail.job_description == ""


class TestParseAppearDate:
    def test_compact_format(self, list_fixture):
        item = parse_list_item(list_fixture["data"][0])
        assert isinstance(item.appear_date, (datetime.date, type(None)))

    def test_slash_format(self):
        item = parse_list_item({"appearDate": "2026/07/16"})
        assert item.appear_date == datetime.date(2026, 7, 16)

    def test_invalid_format(self):
        item = parse_list_item({"appearDate": "不是日期"})
        assert item.appear_date is None
