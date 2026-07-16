"""104 結構化欄位的代碼對照。

學歷（optionEdu）對照已以真實職缺 detail 文字交叉驗證：
    [4,5,6]      ↔ 「大學以上」
    [3,4,5]      ↔ 「專科、大學、碩士」
    [1,2,3,4,5]  ↔ 「高中以下、高中、專科、大學、碩士」

經歷（period）為「代碼」而非年數（實測 period=2 ↔ 「1年以上」），
因此經歷統計優先採用詳細內容的 workExp 文字；未知代碼一律顯示
「代碼N」並記 log，不讓統計中斷。
"""

import logging

logger = logging.getLogger(__name__)

EDU_CODE_MAP = {
    1: "高中以下",
    2: "高中",
    3: "專科",
    4: "大學",
    5: "碩士",
    6: "博士",
}

# period 代碼 → 經歷文字（僅收錄已實測驗證的值）
PERIOD_CODE_MAP = {
    0: "不拘",
    2: "1年以上",
}

SALARY_TYPE_MAP = {
    10: "面議",
    30: "時薪",
    40: "日薪",
    50: "月薪",
    60: "年薪",
}

LANGUAGE_CODE_MAP = {
    1: "英文",
    2: "日文",
    18: "中文",
}

# 104 以 salaryHigh=9999999 表示「以上」（無上限）
SALARY_NO_UPPER_BOUND = 9999999


def edu_level(option_edu: list[int] | None) -> str:
    """以最低可接受學歷作為「學歷門檻」分組。

    Args:
        option_edu: 列表 API 的學歷代碼集合。

    Returns:
        門檻名稱；空集合視為「不拘」。
    """
    if not option_edu:
        return "不拘"
    lowest = min(option_edu)
    name = EDU_CODE_MAP.get(lowest)
    if name is None:
        logger.warning("未知學歷代碼：%s", lowest)
        return f"代碼{lowest}"
    return name


def experience_level(period: int, work_exp_desc: str | None) -> str:
    """經歷要求分組：優先採用詳細內容文字，否則以代碼對照。"""
    if work_exp_desc and work_exp_desc.strip():
        return work_exp_desc.strip()
    name = PERIOD_CODE_MAP.get(period)
    if name is None:
        logger.debug("未知經歷代碼：%s", period)
        return f"代碼{period}"
    return name


def language_names(language_codes: list[int] | None) -> list[str]:
    """語言代碼 → 名稱列表；未知代碼顯示「語言代碼N」。"""
    names: list[str] = []
    for code in language_codes or []:
        name = LANGUAGE_CODE_MAP.get(code)
        if name is None:
            logger.debug("未知語言代碼：%s", code)
            name = f"語言代碼{code}"
        names.append(name)
    return names


def format_salary(
    salary_desc: str | None,
    salary_low: int,
    salary_high: int,
    salary_type: int,
) -> str:
    """組出薪資顯示文字。

    優先使用詳細內容的文字；否則以列表數值與型態代碼組合。
    """
    if salary_desc:
        return salary_desc
    if salary_type == 10 or (not salary_low and not salary_high):
        return "待遇面議"
    unit = SALARY_TYPE_MAP.get(salary_type, "")
    if salary_high and salary_high != SALARY_NO_UPPER_BOUND:
        if salary_low:
            return f"{unit} {salary_low:,}～{salary_high:,} 元"
        return f"{unit} {salary_high:,} 元以下"
    if salary_low:
        return f"{unit} {salary_low:,} 元以上"
    return "待遇面議"
