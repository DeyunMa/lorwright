"""伊莉絲蜘蛛快攻的 L1 规则层。

核心层只提供机制（`GameState`、`Action`、战斗求解器）；
**这套牌怎么打分、什么先出、什么时候不打** 全在这里。

结构按决策点分派，不是扁平优先级列表：

    P0 守卫  → P4 出牌 → P2 攻击声明 → 收尾

顺序不能反：LoR 里新出的单位**当回合就能攻击**（没有召唤失调），
所以先出牌再攻击永远比反过来强。
"""

from __future__ import annotations

from lorwright.core.champions.elise.deck import Effect, EliseCard, lookup
from lorwright.core.decide.base import Policy
from lorwright.core.decide.card import CardKind
from lorwright.core.models import Action, ActionType, CardInHand, GameState, UIState


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
        # 伊莉絲：牌组核心引擎，不是「一次性召唤 1 只」。
        # 「攻擊：召喚 1 隻攻擊中的小蜘蛛」是**每次攻击**都触发，
        # 2|3 恐惧的身材本身也合格，升级后还能让全体蜘蛛带恐惧。
        # 蜘蛛快攻要的就是「每回合多一个能打的单位」，所以她在任何
        # 同费用牌里都该排第一。
        #
        # 旧代码按 `summons * 2` 只给 2.0，2 费算下来 5+2-3 = 4.0，
        # 挤不进前三 —— 结果整局都不打英雄卡。用户多次指出这是错的：
        # 这套牌的核心就是伊莉絲，先出她，其余蜘蛛围绕她的收益展开。
        # 10.0 的取法：保守按「之后还能攻击 3 回合、每回合多 1 只
        # 小蜘蛛」折 6 分，再加上英雄本身的威胁力，取整到能稳居第一。
        bonus = 10.0
    elif card.effect is Effect.GENERATE_CHOICE:
        # 泰爾石：三选一虽然灵活，但要占掉一次出牌节奏，还要多两次点击。
        # 蜘蛛快攻要的是「这回合就把蜘蛛铺上去」，所以给负分排到最后，
        # 只有实在没别的牌可出时才会轮到它（用户明确要求不要默认打它）。
        bonus = -5.0

    return base + bonus - card.cost * 1.5


def rank_playable(state: GameState) -> list[tuple[CardInHand, EliseCard, float]]:
    """当前能打出的牌，按「先铺场后召唤时 buff，再按评分」排好序。

    buff 牌先出是这套牌的确定性规则：所有 buff 都是给「其他蜘蛛」的，
    先出只会让后面的牌更值，不会更亏。
    牌名未知时仅使用独立的可出单位证据；其余未知牌跳过，不阻塞攻击或收尾。
    """
    # 这套牌场上单位全是蜘蛛（含小蜘蛛 token），所以直接取单位数。
    # 换其他英雄时这段逻辑会跟着英雄包一起换掉。
    spiders_on_board = len(state.my_units)
    board_full = spiders_on_board >= 6
    enemy_max_attack = max((u.attack for u in state.enemy_units), default=0)

    playable: list[tuple[CardInHand, EliseCard, float]] = []
    for card in state.hand:
        if card.cost < 0:
            continue
        if state.hand_expanded and not card.drag_point_valid:
            continue
        definition = lookup(card.name)
        if definition is not None and definition.kind not in (
            CardKind.UNIT, CardKind.CHAMPION, CardKind.SPELL,
        ):
            continue  # 地标暂不打出，装备需要已核验的友方目标流程。
        available_mana = max(0, state.mana)
        if (definition is not None and definition.kind is CardKind.SPELL
                and state.spell_mana is not None and state.has_fresh_readings("spell_mana")):
            available_mana += max(0, state.spell_mana)
        if card.cost > available_mana:
            continue
        if definition is None:
            if board_full or not card.visible_playable_unit:
                continue
            definition = EliseCard(card.name, cost=card.cost)
        elif board_full and definition.is_unit:
            continue
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

    # 「召喚時」型 buff 排在后面：先铺受益的蜘蛛，再召唤它们
    playable.sort(key=lambda item: (item[1].settles_last, -item[2]))
    return playable


#: 单位被拖到攻击行（或格挡位）后 y 中心约 710；平躺在己方半场时约 930。
#: 用它区分「还没声明」和「已声明、等确认」—— 后者按钮是「確認」，状态机认不出来。
ATTACK_ROW_MAX_Y = 800


def _units_in_attack_row(state: GameState) -> bool:
    return any(u.rect.center[1] < ATTACK_ROW_MAX_Y for u in state.my_units)


class SpiderAggroPolicy(Policy):
    name = "elise_spider_aggro"
    version = "0.3.0"

    def __init__(self) -> None:
        #: 最近已发送拖牌的手牌序号。用来发现「拖了但没出成」。
        #: 有些牌带着条件，不满足时**根本拖不动**：伊莉絲变成英雄法术后
        #: 要求「本回合有友軍單位陣亡」。不记下来就会每 tick 重试同一张，
        #: 永远出不了牌（实机 2026-11-04 卡了 10 个 tick）。
        self._pending_play: int | None = None
        self._pending_cost: int | None = None
        self._pending_name: str = ""
        self._pending_hand: int = -1
        #: 拖不动的牌身份 `(name, cost)`。已知牌名按 `(牌名, 费用)` 隔离，避免一张同费
        #: 条件牌拖不动时连带封死其他同费蜘蛛；未知牌退回 `("", cost)` 兼容收起/展开。
        self._unplayable: set[tuple[str, int]] = set()
        #: 需要选目标的牌身份 `(name, cost)`。整场对局不再碰该牌，新对局换牌时清空。
        self._needs_target: set[tuple[str, int]] = set()

    def reset_for_battle(self) -> None:
        self._pending_play = None
        self._pending_cost = None
        self._pending_name = ""
        self._pending_hand = -1
        self._unplayable.clear()
        self._needs_target.clear()

    @staticmethod
    def _card_key(card: CardInHand) -> tuple[str, int]:
        return (card.name, card.cost)

    def on_action_sent(self, action: Action, before: GameState) -> None:
        """仅记录已发送的拖牌；视图动作不进入出牌状态。"""
        if (action.type is not ActionType.PLAY_CARD or not before.hand_expanded
                or before.ui_state is not UIState.MY_TURN_IDLE):
            return
        card = next((card for card in before.hand if card.index == action.card_index), None)
        if card is None:
            return
        self._pending_play = card.index
        self._pending_cost = card.cost
        self._pending_name = card.name
        self._pending_hand = len(before.hand)

    def on_action_outcome(self, action: Action, before: GameState, after: GameState) -> None:
        """引擎已核实出牌成功时，不能再凭手牌数量把它当成失败。"""
        if action.type is ActionType.PLAY_CARD and action.card_index == self._pending_play:
            self._pending_play = None
            self._pending_cost = None
            self._pending_name = ""

    def _settle_previous_play(self, state: GameState) -> None:
        """上一 tick 的 play_card 成不成：手牌没减少就是没出成。"""
        if self._pending_play is None:
            return
        if len(state.hand) >= self._pending_hand and self._pending_cost is not None:
            self._unplayable.add((self._pending_name, self._pending_cost))
        self._pending_play = None
        self._pending_cost = None
        self._pending_name = ""

    def decide(self, state: GameState) -> Action | None:
        # 格挡、可选选牌、弃牌交由通用层或引擎专用流程处理，必须弃权返回 None。
        if state.ui_state in (UIState.BLOCKING, UIState.OPTIONAL_CHOICE, UIState.DISCARD):
            return None

        # 起手换牌是新对局边界：清空上一场战斗残留的失败/选目标记忆，直接确定保留低费起手。
        if state.ui_state is UIState.MULLIGAN:
            self.reset_for_battle()
            return Action(type=ActionType.CONFIRM)

        # 「結算」= 战斗结算/提交声明，答案唯一，点一下就走。
        if state.ui_state is UIState.COMBAT_RESOLVING:
            return Action(type=ActionType.CONFIRM)

        # 「選擇目標」说明上一 tick 拖出的牌要选目标（击晕、替换、击杀友军…）。
        if state.ui_state is UIState.TARGETING:
            if self._pending_cost is not None:
                self._needs_target.add((self._pending_name, self._pending_cost))
                self._pending_play = None
                self._pending_cost = None
                self._pending_name = ""
            return Action(type=ActionType.NO_OP)

        if state.ui_state is not UIState.MY_TURN_IDLE:
            return Action(type=ActionType.NO_OP)

        self._settle_previous_play(state)
        # 手牌数量一变（出成了 / 抽到新牌）就重新给每张牌机会
        if len(state.hand) != self._pending_hand:
            self._unplayable.clear()
        self._pending_hand = len(state.hand)

        # 单位已经被拖到攻击行 → 按钮已变成「確認」，下一步只能确认。
        if state.my_units and _units_in_attack_row(state):
            return Action(type=ActionType.CONFIRM)

        if not state.hand_expanded and state.hand:
            return Action(type=ActionType.EXPAND_HAND)

        # P4 出牌：先铺场后召唤时 buff，再按评分。每 tick 只出一张，下一 tick 重新感知。
        ranked = [
            item
            for item in rank_playable(state)
            if self._card_key(item[0]) not in self._unplayable
            and self._card_key(item[0]) not in self._needs_target
        ]
        if ranked:
            card, definition, _score = ranked[0]
            raw = {"unit_card": True} if (definition.is_unit or card.visible_playable_unit) else {}
            return Action(type=ActionType.PLAY_CARD, card_index=card.index, raw=raw)

        # P2 攻击声明：求解器说值得打才打
        attack = self._attack(state)
        if attack is not None:
            return attack

        # P4-d 收尾
        return Action(type=ActionType.END_TURN)

    def _attack(self, state: GameState) -> Action | None:
        if not state.has_attack_token:
            return None

        # 蜘蛛快攻：**全员压上**，不做「最优子集」求解。
        #
        # 求解器 `decide.combat.best_attack` 只看攻/血两个数，算不出这套牌
        # 真正吃的东西：
        #   - 伊莉絲「攻擊：召喚 1 隻攻擊中的小蜘蛛」—— 她参战就白赚一个单位，
        #     站着不动等于每回合扔掉一只蜘蛛；
        #   - 尖嘯蜘蛛「攻擊：本回合全體蜘蛛 +2|+0」；
        #   - 恐惧让对面攻击力 <3 的单位根本挡不了。
        # 它按「脸伤×权重 − 阵亡价值」评分，天然倾向只派一两个去换，实战表现
        # 就是每回合只有一个单位冲上去，英雄卡一直站着。用户多次指出这一点。
        #
        # 快攻要的是持续施压和触发次数，不是每回合算一次最优交换。所以这里
        # 跳过求解：能攻击的全部参战。攻击力还没识别（-1）时也一样。
        attackers = [i for i, u in enumerate(state.my_units) if u.can_attack and not u.stunned]
        if not attackers:
            return None
        return Action(
            type=ActionType.ATTACK,
            target="nexus",
            raw={"attackers": attackers},
        )

