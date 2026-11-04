"""伊莉絲蜘蛛快攻的 L1 规则层。

核心层只提供机制（`GameState`、`Action`、战斗求解器）；
**这套牌怎么打分、什么先出、什么时候不打** 全在这里。

结构按决策点分派，不是扁平优先级列表：

    P0 守卫  → P4 出牌 → P2 攻击声明 → 收尾

顺序不能反：LoR 里新出的单位**当回合就能攻击**（没有召唤失调），
所以先出牌再攻击永远比反过来强。
"""

from __future__ import annotations

from lorwright.champions.elise.deck import Effect, EliseCard, lookup
from lorwright.decide.base import Policy
from lorwright.decide.combat import best_attack, to_combatant
from lorwright.models import Action, ActionType, CardInHand, GameState, UIState


def score(card: EliseCard, *, spiders_on_board: int, enemy_max_attack: int) -> float:
    """这张牌现在打出去值多少。

    这套牌的收益结构是 **buff 叠乘**，不是单卡质量：群蛛之主 +2|+0、
    尖嘯蜘蛛 +2|+0、發狂疾行蛛 +1|+0 都是「喂给其他蜘蛛」的，
    所以场上蜘蛛越多，buff 牌越值钱。
    """
    base = float(card.attack + card.health)
    bonus = 0.0

    if card.effect is Effect.BUFF_PERMANENT:
        # 群蛛之主：每多喂一只就多赚 buff_attack 点永久攻击力
        bonus = card.buff_attack * max(0, spiders_on_board - 1)
    elif card.effect is Effect.BUFF_ON_ATTACK:
        # 尖嘯蜘蛛：本回合攻击前出，等于全体 +2
        bonus = card.buff_attack * spiders_on_board
    elif card.effect is Effect.BUFF_ON_SUMMON:
        # 發狂疾行蛛：+1|+0 给自己以外的蜘蛛，外加敌军 -1|-0 折 1 分
        bonus = card.buff_attack * spiders_on_board + 1
    elif card.effect is Effect.SUMMON_SPIDERLINGS:
        # 傾巢而出：3 只 1/1（每只折 2 分）+ 全体 +1
        bonus = card.summons * 2 + card.buff_attack * spiders_on_board
    elif card.effect is Effect.STUN:
        # 击晕只有在对面有大单位时才值钱
        bonus = 2 * max(0, enemy_max_attack - 3)
    elif card.effect is Effect.ATTACK_SUMMON:
        # 伊莉絲：攻击时白赚一只小蜘蛛
        bonus = card.summons * 2
    elif card.effect is Effect.GENERATE_CHOICE:
        # 泰爾石：1 费换一张 +2|+2，灵活度折 3 分
        bonus = 3.0

    return base + bonus - card.cost * 1.5


def rank_playable(state: GameState) -> list[tuple[CardInHand, EliseCard, float]]:
    """当前能打出的牌，按「先 buff 后普通，再按评分」排好序。

    buff 牌先出是这套牌的确定性规则：所有 buff 都是给「其他蜘蛛」的，
    先出只会让后面的牌更值，不会更亏。
    查不到的牌（识别错字/新卡）按 0 费、0 分处理，排在最后但不会被丢掉。
    """
    # 这套牌场上单位全是蜘蛛（含小蜘蛛 token），所以直接取单位数。
    # 换其他英雄时这段逻辑会跟着英雄包一起换掉。
    spiders_on_board = len(state.my_units)
    enemy_max_attack = max((u.attack for u in state.enemy_units), default=0)

    playable: list[tuple[CardInHand, EliseCard, float]] = []
    for card in state.hand:
        if not (0 <= card.cost <= state.mana):
            continue
        definition = lookup(card.name) or EliseCard(card.name, cost=card.cost)
        playable.append(
            (
                card,
                definition,
                score(
                    definition,
                    spiders_on_board=spiders_on_board,
                    enemy_max_attack=enemy_max_attack,
                ),
            )
        )

    playable.sort(key=lambda item: (not item[1].is_buffer, -item[2]))
    return playable


#: 单位被拖到攻击行（或格挡位）后 y 中心约 710；平躺在己方半场时约 930。
#: 用它区分「还没声明」和「已声明、等确认」—— 后者按钮是「確認」，状态机认不出来。
ATTACK_ROW_MAX_Y = 800


def _units_in_attack_row(state: GameState) -> bool:
    return any(u.rect.center[1] < ATTACK_ROW_MAX_Y for u in state.my_units)


class SpiderAggroPolicy(Policy):
    name = "elise_spider_aggro"
    version = "0.3.0"

    #: 快攻 + 恐惧穿透：脸伤比换血值钱。默认 3.0，这套牌调高。
    nexus_weight: float = 4.0

    def __init__(self) -> None:
        #: 上一 tick 打出的手牌序号。用来发现「拖了但没出成」。
        #: 有些牌带着条件，不满足时**根本拖不动**：伊莉絲变成英雄法术后
        #: 要求「本回合有友軍單位陣亡」。不记下来就会每 tick 重试同一张，
        #: 永远出不了牌（实机 2026-11-04 卡了 10 个 tick）。
        self._pending_play: int | None = None
        self._pending_hand: int = -1
        #: 当前手牌状态下确认拖不出去的序号
        self._unplayable: set[int] = set()

    def _settle_previous_play(self, state: GameState) -> None:
        """上一 tick 的 play_card 成不成：手牌没减少就是没出成。"""
        if self._pending_play is None:
            return
        if len(state.hand) >= self._pending_hand:
            self._unplayable.add(self._pending_play)
        self._pending_play = None

    def decide(self, state: GameState) -> Action | None:
        # P0 守卫：没有优先权时，唯一合法的动作就是不动。
        # 返回 NO_OP 而不是 None —— 弃权会把请求送去 JEV，
        # 对手回合每一帧都白烧一次网络调用。
        if state.ui_state is UIState.BLOCKING:
            return self._block(state)

        # 「選擇目標」说明上一 tick 拖出的牌要选目标（例如冥血戰要求击杀友军）。
        # 这个状态下拖手牌没反应，先取消；取消后手牌没减少，
        # _settle_previous_play 会把那张牌记成不可用，下次换一张。
        if state.ui_state is UIState.TARGETING:
            return Action(type=ActionType.CANCEL)

        if state.ui_state is not UIState.MY_TURN_IDLE:
            return Action(type=ActionType.NO_OP)

        self._settle_previous_play(state)
        # 手牌数量一变（出成了 / 抽到新牌）就重新给每张牌机会
        if len(state.hand) != self._pending_hand:
            self._unplayable.clear()
        self._pending_hand = len(state.hand)

        # 单位已经被拖到攻击行 → 按钮已变成「確認」，下一步只能确认。
        # 用位置判断而不是按钮文字：拖完的按钮是「確認」，状态机认不出它，
        # 但攻击行的单位 y 坐标（≈710）和平躺的（≈930）差得很开。
        if state.my_units and _units_in_attack_row(state):
            return Action(type=ActionType.CONFIRM)

        # P4 出牌：先 buff 后普通，再按评分。每 tick 只出一张，下一 tick 重新感知。
        ranked = [
            item for item in rank_playable(state) if item[0].index not in self._unplayable
        ]
        if ranked:
            card, _definition, _score = ranked[0]
            self._pending_play = card.index
            return Action(type=ActionType.PLAY_CARD, card_index=card.index)

        # P2 攻击声明：求解器说值得打才打
        attack = self._attack(state)
        if attack is not None:
            return attack

        # P4-d 收尾
        return Action(type=ActionType.END_TURN)

    def _block(self, state: GameState) -> Action:
        """对手攻击中。已经挡好了就确认，否则一挡一。"""
        if _units_in_attack_row(state):
            return Action(type=ActionType.CONFIRM)
        if not state.my_units or not state.enemy_units:
            # 没兵可挡：只能放行（点「略過格擋」= 结束回合按钮）
            return Action(type=ActionType.END_TURN)
        # 从后往前配：先用攻击力最高的挡，剩小的挡剩下的
        pairs = [
            (i, i)
            for i in range(min(len(state.my_units), len(state.enemy_units)))
        ]
        return Action(type=ActionType.BLOCK, raw={"pairs": pairs})

    def _attack(self, state: GameState) -> Action | None:
        if not state.has_attack_token:
            return None

        # 攻击力/生命值还没识别（units.py 只给了位置）—— 不做求解，
        # 全体压上。蜘蛛 aggro 本来就是铺完场换脸，这里宁可粗糙也不要
        # 把「不知道」当成 0 攻击力而白站一回合。
        if not state.my_units:
            return None
        if any(u.attack < 0 for u in state.my_units):
            return Action(
                type=ActionType.ATTACK,
                target="nexus",
                raw={"attackers": list(range(len(state.my_units)))},
            )

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

