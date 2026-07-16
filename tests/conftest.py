"""pytest 共用 fixtures。

重要：必須在 import careerstatic 之前設定環境變數，
確保測試不啟動排程器、不連線 PostgreSQL。
"""

import os

os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["RUN_ON_STARTUP"] = "false"
os.environ["DATABASE_URL"] = "sqlite+pysqlite://"

import dataclasses
import datetime
import json
import pathlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from careerstatic.config import get_settings
from careerstatic.db.base import Base

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"

TEST_DATE = datetime.date(2026, 7, 16)


@pytest.fixture
def engine():
    """SQLite in-memory engine（StaticPool 確保共用同一連線）。"""
    eng = create_engine(
        "sqlite+pysqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    from careerstatic.db import models  # noqa: F401  確保模型已註冊

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """繫結測試 engine 的 session 工廠。"""
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session(session_factory):
    """單一測試用 session。"""
    s = session_factory()
    yield s
    s.close()


@pytest.fixture
def test_settings():
    """測試用 Settings（少量關鍵字、無延遲）。"""
    return dataclasses.replace(
        get_settings(),
        keywords=("AI", "機器學習"),
        max_pages_per_keyword=5,
        detail_limit_per_day=10,
        min_delay=0.0,
        max_delay=0.0,
        enable_scheduler=False,
        run_on_startup=False,
        stats_top_n=50,
    )


@pytest.fixture
def list_fixture():
    """真實列表 API 回應（裁剪為 3 筆）。"""
    return json.loads((FIXTURE_DIR / "list_page.json").read_text(encoding="utf-8"))


@pytest.fixture
def detail_fixture():
    """真實詳細 API 回應（裁剪 header/condition/jobDetail）。"""
    return json.loads((FIXTURE_DIR / "detail.json").read_text(encoding="utf-8"))


@pytest.fixture
def app(session_factory):
    """FastAPI 測試應用（DB 依賴覆寫為測試 session）。"""
    from careerstatic.web import routes
    from careerstatic.web.app import create_app

    application = create_app()

    def override_get_db():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    application.dependency_overrides[routes.get_db] = override_get_db
    return application


@pytest.fixture
def client(app):
    """FastAPI TestClient（with 區塊觸發 lifespan）。"""
    from fastapi.testclient import TestClient

    with TestClient(app) as test_client:
        yield test_client
