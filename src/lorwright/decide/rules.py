"""L1 规则层：伊莉絲蜘蛛快攻。

设计见 `docs/decision-l1-rules.md`，牌表见 `docs/decks/spider-aggro.md`。

结构按**决策点**分派，不是扁平优先级列表：

    P0 守卫  → P4 出牌 → P2 攻击声明 → 收尾

顺序不能反：LoR 里新出的单位**当回合就能攻击**（没有召唤失调），
所以先出牌再攻击永远比反过来强。
"""

from __future__ import annotations

from lorwright.decide.base import Policy
from lorwright.decide.combat import best_attack
from lorwright.decide.deck import rank_playable, to_combatant
from lorwright.models import Action, ActionType, GameState, UIState


class SpiderAggroPolicy(Policy):
    name = "spider_aggro"
    version = "0.2.0"

    #: 快攻 + 恐惧穿透：脸伤比换血值钱。默认 3.0，这套牌调高。
    nexus_weight: float = 4.0

    def decide(self, state: GameState) -> Action | None:
        # P0 守卫：没有优先权时，唯一合法的动作就是不动。
        # 返回 NO_OP 而不是 None —— 弃权会把请求送去 JEV，
        # 对手回合每一帧都白烧一次网络调用。
        if state.ui_state is not UIState.MY_TURN_IDLE:
            return Action(type=ActionType.NO_OP)

        # P4 出牌：先 buff 后普通，再按评分。每 tick 只出一张，下一 tick 重新感知。
        ranked = rank_playable(state)
        if ranked:
            card, _definition, _score = ranked[0]
            return Action(type=ActionType.PLAY_CARD, card_index=card.index)

        # P2 攻击声明：求解器说值得打才打
        attack = self._attack(state)
        if attack is not None:
            return attack

        # P4-d 收尾
        return Action(type=ActionType.END_TURN)

    def _attack(self, state: GameState) -> Action | None:
        if not state.has_attack_token:
            return None

        challenger = state.my_units_have_challenger
        attackers = [
            to_combatant(u, challenger=challenger) for u in state.my_units if u.can_attack
        ]
        if not attackers:
            return None

        blockers = [to_combatant(u) for u in state.enemy_units]
        plan = best_attack(
            attackers,
            blockers,
            nexus_weight=self.nexus_weight,
            challenger=challenger,
        )

        # 求解器算出所有声明都不划算（比如拿 1/1 白喂 5/5）→ 不打
        if not plan.attackers or plan.score <= 0:
            return None

        return Action(
            type=ActionType.ATTACK,
            target="nexus",
            raw={
                "attackers": list(plan.attackers),
                "nexus_damage": plan.nexus_damage,
                "score": plan.score,
            },
        )
