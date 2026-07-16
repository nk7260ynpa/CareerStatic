"""資料庫 engine 與 session 工廠。"""

import logging
import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from careerstatic.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基底類別。"""


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(database_url: str | None = None) -> Engine:
    """初始化（或重新初始化）engine 與 session 工廠。

    Args:
        database_url: 覆蓋設定值的資料庫連線字串；None 時取自 Settings。

    Returns:
        建立好的 SQLAlchemy Engine。
    """
    global _engine, _session_factory
    url = database_url or get_settings().database_url

    connect_args = {}
    if url.startswith("sqlite"):
        # SQLite 檔案路徑需先確保目錄存在；跨執行緒使用需放寬限制
        connect_args["check_same_thread"] = False
        path = url.split("///", 1)[-1]
        if path and not url.endswith("//"):
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)

    _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    logger.info("資料庫 engine 已初始化：%s", _engine.url.render_as_string(hide_password=True))
    return _engine


def get_engine() -> Engine:
    """取得全域 engine（未初始化時自動初始化）。"""
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """取得全域 session 工廠（未初始化時自動初始化）。"""
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def create_all() -> None:
    """建立所有資料表（冪等）。"""
    from careerstatic.db import models  # noqa: F401  確保模型已註冊

    Base.metadata.create_all(get_engine())
