"""L2：JEV 快速决策客户端。

JEV 是「类型安全的决策引擎」，输出 Choice / Score / Noul，
适合做「从候选里挑一个」这类有界决策（100–500ms）。

接口按 OpenAI 风格设计，实际 endpoint 在配置里指定；
未配置时自动降级为 None（路由会跳到下一层）。
"""

from __future__ import annotations

import httpx

from lorwright.util.logger import logger


class JevClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        timeout: float = 2.0,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def choose(self, context: str, options: list[str]) -> str | None:
        """从 options 里选一个；失败或未配置返回 None。"""
        if not self.enabled or not options:
            return None
        if len(options) == 1:
            return options[0]

        payload = {
            "kind": "choice",
            "context": context,
            "options": options,
        }
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(
                    f"{self.base_url}/decide",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                )
                r.raise_for_status()
                data = r.json()
            choice = data.get("choice")
            if choice in options:
                return choice
            logger.warning("JEV 返回了非法选项: {!r}", choice)
            return None
        except Exception as e:  # noqa: BLE001
            logger.warning("JEV 调用失败，降级: {}", e)
            return None

    def yes_no(self, context: str) -> bool | None:
        """布尔决策；失败返回 None。"""
        if not self.enabled:
            return None
        try:
            with httpx.Client(timeout=self.timeout) as c:
                r = c.post(
                    f"{self.base_url}/decide",
                    json={"kind": "noul", "context": context},
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                )
                r.raise_for_status()
                data = r.json()
            v = data.get("value")
            return bool(v) if v is not None else None
        except Exception as e:  # noqa: BLE001
            logger.warning("JEV 调用失败: {}", e)
            return None


class MockJev:
    """测试用：按预设规则返回，不联网。"""

    def __init__(self, answer: str | None = None) -> None:
        self.answer = answer
        self.calls: list[dict] = []

    @property
    def enabled(self) -> bool:
        return True

    def choose(self, context: str, options: list[str]) -> str | None:
        self.calls.append({"context": context, "options": options})
        return self.answer if self.answer in options else None

    def yes_no(self, context: str) -> bool | None:
        self.calls.append({"context": context})
        return None
