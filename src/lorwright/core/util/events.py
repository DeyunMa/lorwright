"""结构化事件：每回合一行 JSON，写入 logs/<date>/events.jsonl。

用途：事后用 LLM 分析「哪条规则误判了」「哪一层在拖慢」。
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from lorwright.core.runtime.session import current_session, record_event


def emit(**fields: Any) -> None:
    """运行中写入会话事件；独立调用仍保留日期日志供已有复盘工具使用。"""
    if current_session() is not None:
        record_event(str(fields.get("event", "tick")), **fields)
    else:
        logger.bind(event=True).info(json.dumps(fields, ensure_ascii=False, default=str))
