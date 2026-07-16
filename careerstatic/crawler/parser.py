"""104 API 回應解析：原始 JSON → dataclass。

104 為非官方 API，回應結構可能變動，因此所有欄位一律以
防禦性方式（.get + 型別轉換）取值，缺欄位時 fail-soft 不中斷。
"""

import dataclasses
import datetime
import logging

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class JobListItem:
    """列表 API 的單筆職缺。"""

    job_no: str = ""
    job_code: str = ""
    job_url: str = ""
    job_name: str = ""
    cust_name: str = ""
    cust_no: str = ""
    area_desc: str = ""
    industry_desc: str = ""
    description: str = ""
    pc_skills: list[str] = dataclasses.field(default_factory=list)
    option_edu: list[int] = dataclasses.field(default_factory=list)
    period: int = 0
    salary_low: int = 0
    salary_high: int = 0
    salary_type: int = 0
    job_cats: list[int] = dataclasses.field(default_factory=list)
    remote_work_type: int = 0
    appear_date: datetime.date | None = None
    apply_cnt: int = 0
    language_codes: list[int] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class JobDetail:
    """詳細 API 的職缺內容。"""

    job_description: str = ""
    other_condition: str = ""
    skills: list[str] = dataclasses.field(default_factory=list)
    specialties: list[str] = dataclasses.field(default_factory=list)
    work_exp_desc: str = ""
    edu_desc: str = ""
    salary_desc: str = ""
    salary_min: int = 0
    salary_max: int = 0
    salary_type: int = 0
    job_cat_descs: list[str] = dataclasses.field(default_factory=list)
    address_region: str = ""
    majors: list[str] = dataclasses.field(default_factory=list)
    certificates: list[str] = dataclasses.field(default_factory=list)
    language_codes: list[int] = dataclasses.field(default_factory=list)


def _to_int(value, default: int = 0) -> int:
    """安全轉整數。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_str(value) -> str:
    """安全轉字串（None → 空字串）。"""
    return str(value) if value is not None else ""


def _descriptions(seq) -> list[str]:
    """從 [{"code":…, "description":…}] 或字串列表擷取名稱清單。"""
    out: list[str] = []
    for item in seq or []:
        if isinstance(item, dict):
            text = _to_str(item.get("description") or item.get("name")).strip()
        else:
            text = _to_str(item).strip()
        if text:
            out.append(text)
    return out


def extract_job_code(link_job: str) -> str:
    """自 link.job URL 取出職缺代碼。

    例：https://www.104.com.tw/job/60yka?jobsource=… → "60yka"。
    """
    if not link_job:
        return ""
    path = link_job.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return path.rsplit("/", 1)[-1]


def _parse_appear_date(raw) -> datetime.date | None:
    """解析日期字串（支援 20260714 與 2026/07/14 兩種格式）。"""
    text = _to_str(raw).strip()
    for fmt in ("%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _language_codes(seq) -> list[int]:
    """擷取語言代碼列表（list 用 language 欄位、detail 用 code 欄位）。"""
    codes: list[int] = []
    for item in seq or []:
        if not isinstance(item, dict):
            continue
        raw = item.get("code", item.get("language"))
        code = _to_int(raw, default=-1)
        if code >= 0:
            codes.append(code)
    return codes


def parse_list_item(raw: dict) -> JobListItem:
    """解析列表 API 的單筆職缺。"""
    link = raw.get("link") or {}
    job_url = _to_str(link.get("job"))
    if job_url.startswith("//"):
        job_url = "https:" + job_url

    return JobListItem(
        job_no=_to_str(raw.get("jobNo")),
        job_code=extract_job_code(job_url),
        job_url=job_url,
        job_name=_to_str(raw.get("jobName")),
        cust_name=_to_str(raw.get("custName")),
        cust_no=_to_str(raw.get("custNo")),
        area_desc=_to_str(raw.get("jobAddrNoDesc")),
        industry_desc=_to_str(raw.get("coIndustryDesc")),
        description=_to_str(raw.get("description") or raw.get("descSnippet")),
        pc_skills=_descriptions(raw.get("pcSkills")),
        option_edu=[_to_int(x) for x in raw.get("optionEdu") or []],
        period=_to_int(raw.get("period")),
        salary_low=_to_int(raw.get("salaryLow")),
        salary_high=_to_int(raw.get("salaryHigh")),
        salary_type=_to_int(raw.get("s10")),
        job_cats=[_to_int(x) for x in raw.get("jobCat") or []],
        remote_work_type=_to_int(raw.get("remoteWorkType")),
        appear_date=_parse_appear_date(raw.get("appearDate")),
        apply_cnt=_to_int(raw.get("applyCnt")),
        language_codes=_language_codes(raw.get("languageRequirements")),
    )


def parse_job_detail(raw: dict) -> JobDetail:
    """解析詳細 API 的回應（傳入完整回應，內部取 data.*）。"""
    data = raw.get("data") or {}
    condition = data.get("condition") or {}
    job_detail = data.get("jobDetail") or {}

    return JobDetail(
        job_description=_to_str(job_detail.get("jobDescription")),
        other_condition=_to_str(condition.get("other")),
        skills=_descriptions(condition.get("skill")),
        specialties=_descriptions(condition.get("specialty")),
        work_exp_desc=_to_str(condition.get("workExp")).strip(),
        edu_desc=_to_str(condition.get("edu")).strip(),
        salary_desc=_to_str(job_detail.get("salary")).strip(),
        salary_min=_to_int(job_detail.get("salaryMin")),
        salary_max=_to_int(job_detail.get("salaryMax")),
        salary_type=_to_int(job_detail.get("salaryType")),
        job_cat_descs=_descriptions(job_detail.get("jobCategory")),
        address_region=_to_str(job_detail.get("addressRegion")),
        majors=[m for m in (_to_str(x).strip() for x in condition.get("major") or []) if m],
        certificates=_descriptions(condition.get("certificate")),
        language_codes=_language_codes(condition.get("language")),
    )
