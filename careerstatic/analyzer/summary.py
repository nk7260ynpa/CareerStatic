"""每日繁體中文總結文字產生（純模板組裝，不使用 LLM）。"""

import datetime
import logging

from sqlalchemy.orm import Session

from careerstatic.db import repository

logger = logging.getLogger(__name__)

_CATEGORY_LABELS = {
    "specialty": "熱門擅長工具",
    "skill": "熱門工作技能",
    "tech_keyword": "內文技術關鍵字",
}

_TOP_N_TEXT = 5
_TOP_N_JSON = 20
_MAX_RANK_CHANGES = 3


def _top_line(label: str, ranked: list[tuple[str, int]], total: int) -> str | None:
    """組出單一類別的 Top N 句子。"""
    if not ranked or not total:
        return None
    parts = [
        f"{name}（{count:,} 筆，{count / total * 100:.1f}%）"
        for name, count in ranked[:_TOP_N_TEXT]
    ]
    return f"{label} Top {len(parts)}：" + "、".join(parts) + "。"


def _distribution_line(label: str, ranked: list[tuple[str, int]], total: int) -> str | None:
    """組出分布句（學歷／經歷）。"""
    if not ranked or not total:
        return None
    parts = [
        f"{name} {count / total * 100:.1f}%"
        for name, count in ranked[:6]
    ]
    return f"{label}分布：" + "、".join(parts) + "。"


def _rank_changes(
    current: list[tuple[str, int]], previous_items: list[dict]
) -> list[str]:
    """比較技術關鍵字排名，找出顯著上升的項目（最多 3 條）。"""
    prev_rank = {item["name"]: item["rank"] for item in previous_items}
    changes: list[tuple[int, str]] = []
    for rank, (name, _) in enumerate(current, start=1):
        if rank > 20:
            break
        old = prev_rank.get(name)
        if old is not None and old - rank >= 2:
            changes.append(
                (old - rank, f"{name} 上升 {old - rank} 名（第 {old} → 第 {rank}）")
            )
    changes.sort(reverse=True)
    return [text for _, text in changes[:_MAX_RANK_CHANGES]]


def build_stats_json(stats: dict, previous: "repository.DailySummary | None") -> dict:
    """組出前端一次取用的統計快照（各類 Top 20 + 與前日排名差）。"""
    prev_by_category: dict[str, dict[str, int]] = {}
    if previous and isinstance(previous.stats_json, dict):
        for category, items in (previous.stats_json.get("by_category") or {}).items():
            prev_by_category[category] = {
                item["name"]: item["rank"] for item in items if isinstance(item, dict)
            }

    by_category: dict[str, list[dict]] = {}
    total = stats["total_jobs"]
    for category, ranked in stats["by_category"].items():
        prev_ranks = prev_by_category.get(category, {})
        items = []
        for rank, (name, count) in enumerate(ranked[:_TOP_N_JSON], start=1):
            old = prev_ranks.get(name)
            items.append(
                {
                    "name": name,
                    "count": count,
                    "ratio": (count / total) if total else 0.0,
                    "rank": rank,
                    "rank_delta": (old - rank) if old is not None else None,
                }
            )
        by_category[category] = items
    return {"by_category": by_category}


def build_summary_text(
    session: Session,
    stat_date: datetime.date,
    stats: dict,
    truncated_keywords: dict | None = None,
) -> str:
    """組出當日繁中總結文字。

    Args:
        session: DB session（查詢前一日總結供比較）。
        stat_date: 統計日期。
        stats: compute_daily_stats 的回傳值。
        truncated_keywords: 因分頁上限而截斷的關鍵字資訊。

    Returns:
        多行總結文字。
    """
    total = stats["total_jobs"]
    new_jobs = stats["new_jobs"]
    previous = repository.get_previous_summary(session, stat_date)

    lines = [f"【{stat_date.isoformat()} AI 職缺技能日報】"]

    delta_text = ""
    if previous is not None:
        delta = total - previous.total_jobs
        if delta:
            direction = "增加" if delta > 0 else "減少"
            delta_text = f"，較前日（{previous.stat_date.isoformat()}）{direction} {abs(delta):,} 筆"
        else:
            delta_text = "，與前日持平"
    lines.append(
        f"今日共收錄 {total:,} 筆 AI 相關職缺，其中新增 {new_jobs:,} 筆{delta_text}。"
    )

    by_category = stats["by_category"]
    for category in ("specialty", "skill", "tech_keyword"):
        line = _top_line(_CATEGORY_LABELS[category], by_category.get(category, []), total)
        if line:
            lines.append(line)

    for category, label in (("education", "學歷門檻"), ("experience", "經歷要求")):
        line = _distribution_line(label, by_category.get(category, []), total)
        if line:
            lines.append(line)

    if previous is not None and isinstance(previous.stats_json, dict):
        prev_keywords = (previous.stats_json.get("by_category") or {}).get(
            "tech_keyword", []
        )
        changes = _rank_changes(by_category.get("tech_keyword", []), prev_keywords)
        if changes:
            lines.append("與前一日相比：" + "；".join(changes) + "。")

    notes = [f"詳細資料涵蓋率 {stats['detail_coverage'] * 100:.1f}%"]
    for keyword, info in (truncated_keywords or {}).items():
        sampled = info.get("sampled")
        total_count = info.get("total")
        if sampled and total_count:
            notes.append(
                f"關鍵字「{keyword}」因 104 分頁上限僅取樣 {sampled:,}／{total_count:,} 筆"
            )
    lines.append("（附註：" + "；".join(notes) + "）")

    return "\n".join(lines)


def summarize_day(
    session: Session,
    stat_date: datetime.date,
    stats: dict,
    truncated_keywords: dict | None = None,
) -> str:
    """產生總結文字與統計快照並 upsert 至 daily_summaries。

    Returns:
        總結文字。
    """
    previous = repository.get_previous_summary(session, stat_date)
    text = build_summary_text(session, stat_date, stats, truncated_keywords)
    stats_json = build_stats_json(stats, previous)
    repository.upsert_daily_summary(
        session,
        stat_date,
        total_jobs=stats["total_jobs"],
        new_jobs=stats["new_jobs"],
        detail_coverage=stats["detail_coverage"],
        summary_text=text,
        stats_json=stats_json,
    )
    return text
