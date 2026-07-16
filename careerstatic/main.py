"""CLI 入口。

子指令：
    serve    啟動每日排程與網頁儀表板（Docker CMD 預設）
    crawl    立即執行一次爬取
    analyze  重算某日統計與總結
"""

import argparse
import dataclasses
import datetime
import sys

from careerstatic.config import get_settings, taipei_today
from careerstatic.logging_setup import configure_logging


def cmd_serve(args: argparse.Namespace) -> int:
    """啟動排程器與網頁儀表板。"""
    del args
    import uvicorn

    from careerstatic.web.app import create_app

    settings = get_settings()
    configure_logging(settings.log_level)
    # 單 worker：排程器唯一性的前提，勿加 workers 參數
    uvicorn.run(
        create_app(),
        host="0.0.0.0",
        port=settings.web_port,
        log_config=None,
    )
    return 0


def cmd_crawl(args: argparse.Namespace) -> int:
    """立即執行一次爬取。"""
    from careerstatic.crawler.client import Client104
    from careerstatic.crawler.pipeline import run_daily_crawl
    from careerstatic.db.base import create_all, get_session_factory

    settings = get_settings()
    if args.keywords:
        keywords = tuple(k.strip() for k in args.keywords.split(",") if k.strip())
        settings = dataclasses.replace(settings, keywords=keywords)
    configure_logging(settings.log_level)
    create_all()

    client = Client104(min_delay=settings.min_delay, max_delay=settings.max_delay)
    result = run_daily_crawl(
        get_session_factory(),
        client,
        settings,
        max_pages=args.max_pages,
        detail_limit=args.detail_limit,
        details_only=args.details_only,
        trigger="manual",
    )
    print(
        f"爬取完成：狀態={result.status}、收錄 {result.jobs_seen} 筆"
        f"（新增 {result.jobs_new}）、詳細內容 {result.details_fetched} 筆"
        f"（待補 {result.details_pending}）"
    )
    return 0 if result.status in ("success", "partial") else 1


def cmd_analyze(args: argparse.Namespace) -> int:
    """重算某日統計與總結。"""
    from careerstatic.analyzer.stats import compute_daily_stats
    from careerstatic.analyzer.summary import summarize_day
    from careerstatic.db import repository
    from careerstatic.db.base import create_all, get_session_factory

    settings = get_settings()
    configure_logging(settings.log_level)
    create_all()

    stat_date = (
        datetime.date.fromisoformat(args.date) if args.date else taipei_today()
    )
    session = get_session_factory()()
    try:
        latest_run = repository.get_latest_run_for_date(session, stat_date)
        truncated = dict(latest_run.truncated_keywords or {}) if latest_run else {}
        stats = compute_daily_stats(session, stat_date, settings.stats_top_n)
        text = summarize_day(session, stat_date, stats, truncated)
        session.commit()
    finally:
        session.close()
    print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """建立 CLI 參數解析器。"""
    parser = argparse.ArgumentParser(
        prog="careerstatic",
        description="104 人力銀行 AI 職缺每日爬取、統計與儀表板",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="啟動排程與網頁儀表板")
    serve.set_defaults(func=cmd_serve)

    crawl = subparsers.add_parser("crawl", help="立即執行一次爬取")
    crawl.add_argument("--max-pages", type=int, default=None, help="每關鍵字最大頁數")
    crawl.add_argument(
        "--detail-limit", type=int, default=None, help="本次詳細內容抓取上限"
    )
    crawl.add_argument(
        "--details-only",
        action="store_true",
        help="只補抓詳細內容並重算統計（跳過列表階段）",
    )
    crawl.add_argument(
        "--keywords", type=str, default=None, help="覆蓋搜尋關鍵字（逗號分隔）"
    )
    crawl.set_defaults(func=cmd_crawl)

    analyze = subparsers.add_parser("analyze", help="重算某日統計與總結")
    analyze.add_argument("--date", type=str, default=None, help="日期（YYYY-MM-DD）")
    analyze.set_defaults(func=cmd_analyze)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 主函式。"""
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
