"""ローテーションログ設定 (実装計画書 7節)。"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from hermes_updater.config import get_logs_dir

_LOG_FORMAT = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(
    base_dir: Path | None = None, level: int = logging.INFO, console: bool = True
) -> logging.Logger:
    """ルートロガーに5MB×5世代のRotatingFileHandlerを設定する。二重設定は防止する。

    `console=False`の場合はコンソールへの出力を行わない。トレイ常駐モードは本来
    コンソールを持たない(`pythonw.exe`起動)ため出力先が無く、誤って`python.exe`で
    起動された場合にログがコンソールウィンドウに流れ続けて表示され続けるのを防ぐ。
    """
    global _configured
    root = logging.getLogger("hermes_updater")
    root.setLevel(level)

    if _configured:
        return root

    logs_dir = get_logs_dir(base_dir)
    log_path = logs_dir / "updater.log"

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

    _configured = True
    return root


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"hermes_updater.{name}")
