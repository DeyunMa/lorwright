"""结构化事件：每回合一行 JSON，写入 logs/<date>/events.jsonl。

用途：事后用 LLM 分析「哪条规则误判了」「哪一层在拖慢」。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger


def emit(**fields: Any) -> None:
    """写一行结构化事件（不影响终端日志）。"""
    logger.bind(event=True).info(json.dumps(fields, ensure_ascii=False, default=str))
