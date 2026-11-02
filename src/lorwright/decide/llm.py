"""L3：大模型客户端（OpenAI 兼容协议）。

用于处理复杂局面，例如：
  - 判断对手卡组类型
  - 多单位交换的取舍
  - 规则和 JEV 都弃权时的兜底

默认关闭；未配置 base_url 时直接返回 None。
"""

from __future__ import annotations

import httpx

from lorwright.util.logger import logger

SYSTEM_PROMPT = """你是《符文大地传说》的对局助手，只做一件事：在给定局面下选一个动作。

规则：
1. 只能从给定的候选动作里选，不能发明新动作。
2. 只输出 JSON：{"choice": "<候选动作原文>", "reason": "<20 字以内>"}
3. 不确定时输出 {"choice": null, "reason": "unclear"}
4. 不要输出任何其他文字。
"""


class LlmClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        model: str | None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    def choose(self, context: str, options: list[str]) -> str | None:
        if not self.enabled or not options:
            return None

        user = f"局面：\n{context}\n\n候选动作：\n" + "\n".join(f"- {o}" for o in options)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 200,
        }
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                )
                r.raise_for_status()
                content = r.json()["choices"][0]["message"]["content"]
            choice = self._parse(content)
            if choice in options:
                return choice
            logger.warning("LLM 选择不在候选中: {!r}", choice)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("LLM 调用失败，降级: {}", e)
            return None

    @staticmethod
    def _parse(content: str) -> str | None:
        import json
        import re

        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0)).get("choice")
        except json.JSONDecodeError:
            return None


class MockLlm:
    def __init__(self, answer: str | None = None) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return True

    def choose(self, context: str, options: list[str]) -> str | None:
        self.calls.append({"context": context, "options": options})
        return self.answer if self.answer in options else None
