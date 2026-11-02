"""把 JEV 包装成 Policy：规则弃权时，由 JEV 从候选里挑。"""

from __future__ import annotations

from lorwright.decide.candidates import describe, generate
from lorwright.decide.jev import JevClient
from lorwright.models import Action, GameState


class JevPolicy:
    name = "jev"
    version = "0.1.0"

    def __init__(self, client: JevClient | None) -> None:
        self.client = client

    def decide(self, state: GameState) -> Action | None:
        if self.client is None or not self.client.enabled:
            return None

        candidates = generate(state)
        if len(candidates) <= 1:
            return None

        labels = [describe(a, state) for a in candidates]
        picked = self.client.choose(context=state.summary(), options=labels)
        if picked is None:
            return None

        idx = labels.index(picked)
        action = candidates[idx]
        # JEV 不该改变动作类型之外的语义
        return Action(type=action.type, card_index=action.card_index, target=action.target)


class LlmPolicy:
    name = "llm"
    version = "0.1.0"

    def __init__(self, client) -> None:
        self.client = client

    def decide(self, state: GameState) -> Action | None:
        if self.client is None or not self.client.enabled:
            return None

        candidates = generate(state)
        if len(candidates) <= 1:
            return None

        labels = [describe(a, state) for a in candidates]
        picked = self.client.choose(context=state.summary(), options=labels)
        if picked is None:
            return None

        idx = labels.index(picked)
        action = candidates[idx]
        return Action(type=action.type, card_index=action.card_index, target=action.target)
