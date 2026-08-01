"""统一 logging 配置：默认 stdout，按需追加文件。"""
from __future__ import annotations

import logging
import sys
from typing import IO, Any


logger = logging.getLogger("mypodcast")
logger.setLevel(logging.INFO)
logger.propagate = False

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_initialized = False


class _MaxLevelFilter(logging.Filter):
    """只允许 ≤ level 的记录通过（logging 内置不支持）。"""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def configure(level: str | int = "INFO", log_file: str | None = None) -> None:
    """初始化 logging。可重复调用以更新配置。"""
    global _initialized
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    # 清掉已有 handlers，避免重复输出
    for h in list(logger.handlers):
        logger.removeHandler(h)

    fmt = logging.Formatter(_DEFAULT_FORMAT, datefmt=_DATE_FORMAT)
    stdout_h = logging.StreamHandler(sys.stdout)
    stdout_h.setFormatter(fmt)
    stdout_h.setLevel(level)
    logger.addHandler(stdout_h)
    logger.setLevel(level)

    if log_file:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8", mode="a")
            fh.setFormatter(fmt)
            fh.setLevel(level)
            logger.addHandler(fh)
        except OSError as e:
            logger.warning(f"无法打开日志文件 {log_file}: {e}")

    _initialized = True


def get_logger() -> logging.Logger:
    """惰性获取 logger；未配置时初始化默认。"""
    if not _initialized:
        configure()
    return logger