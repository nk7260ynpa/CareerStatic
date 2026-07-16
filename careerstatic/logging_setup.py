"""logging 初始化：檔案輪替 + 終端輸出。"""

import logging
import os
from logging.handlers import RotatingFileHandler

_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_CONFIGURED_FLAG = "_careerstatic_configured"


def configure_logging(level: str = "INFO", log_dir: str = "logs") -> None:
    """設定 root logger：RotatingFileHandler + StreamHandler（冪等）。

    Args:
        level: log 等級名稱（如 INFO、DEBUG）。
        log_dir: log 檔存放目錄，不存在時自動建立。
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        return

    os.makedirs(log_dir, exist_ok=True)
    formatter = logging.Formatter(_LOG_FORMAT)

    file_handler = RotatingFileHandler(
        os.path.join(log_dir, "careerstatic.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root.setLevel(level.upper())
    root.addHandler(file_handler)
    root.addHandler(stream_handler)
    setattr(root, _CONFIGURED_FLAG, True)
