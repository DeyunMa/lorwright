"""日志：按日期分目录，便于事后用 LLM 分析。"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from loguru import logger


def setup_logger(base_dir: str = "logs", level: str = "INFO", by_date: bool = True) -> None:
    logger.remove()

    # 终端：简洁彩色
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
    )

    # 文件：完整结构化，按日期分目录
    root = Path(base_dir)
    day = date.today().isoformat() if by_date else "all"
    log_dir = root / day if by_date else root
    log_dir.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_dir / "run_{time:HH-mm-ss}.log",
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <7} | {name}:{line} | {message}",
        rotation="50 MB",
        encoding="utf-8",
    )

    # 结构化事件流（每回合一行 JSON，供 LLM 复盘）
    logger.add(
        log_dir / "events.jsonl",
        level="INFO",
        format="{message}",
        filter=lambda r: r["extra"].get("event") is True,
        encoding="utf-8",
    )
