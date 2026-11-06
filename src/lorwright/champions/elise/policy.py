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
        #: 上一 tick 打出的手牌序号。用来发现「拖了但没出成」。
        #: 有些牌带着条件，不满足时**根本拖不动**：伊莉絲变成英雄法术后
        #: 要求「本回合有友軍單位陣亡」。不记下来就会每 tick 重试同一张，
        #: 永远出不了牌（实机 2026-11-04 卡了 10 个 tick）。
        self._pending_play: int | None = None
        self._pending_cost: int | None = None
        self._pending_hand: int = -1
        #: 拖不动的费用。**按费用记，不按序号**：手牌展开态是平铺 7 张、
        #: 收起态是扇形只露 6 张，同一个序号在两种状态下指的不是同一张牌，
        #: 按序号记会在展开/收起之间反复失忆（实机死循环过）。
        self._unplayable: set[int] = set()
        #: 需要选目标的费用（冥血戰这类「擊殺1個友軍單位」的牌）。
        #: 这是牌本身的性质，不是暂时状态，所以整场战斗都不再碰它。
        self._needs_target: set[int] = set()
        #: 「選擇目標」阶段已经试过几次（0=还没试，1=点过敌方，2=点过我方）
        self._target_attempt: int = 0

    def _settle_previous_play(self, state: GameState) -> None:
        """上一 tick 的 play_card 成不成：手牌没减少就是没出成。"""
        if self._pending_play is None:
            return
        if len(state.hand) >= self._pending_hand and self._pending_cost is not None:
            self._unplayable.add(self._pending_cost)
        self._pending_play = None
        self._pending_cost = None

    def decide(self, state: GameState) -> Action | None:
        # P0 守卫：没有优先权时，唯一合法的动作就是不动。
        # 返回 NO_OP 而不是 None —— 弃权会把请求送去 JEV，
        # 对手回合每一帧都白烧一次网络调用。
        if state.ui_state is UIState.BLOCKING:
            return self._block(state)

        # 起手换牌：「確定」按钮和动作按钮同位置同颜色，点一下保留整手牌。
        # 蜘蛛快攻的起手本来就都是低费单位，换牌收益低于「卡住不出牌」的代价。
        if state.ui_state is UIState.MULLIGAN:
            return Action(type=ActionType.CONFIRM)

        # 「結算」= 战斗结算/提交声明，答案唯一，点一下就走。
        # 不处理会一直 no_op 卡死（实机卡过 13 个 tick）。
        if state.ui_state is UIState.COMBAT_RESOLVING:
            return Action(type=ActionType.CONFIRM)

        # 「選擇目標」说明上一 tick 拖出的牌要选目标（击晕、替换、击杀友军…）。
        # 这个状态下拖手牌没反应，必须点一个单位把选择做完。
        if state.ui_state is UIState.TARGETING:
            return self._targeting(state)
        self._target_attempt = 0

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
            item
            for item in rank_playable(state)
            if item[0].cost not in self._unplayable
            and item[0].cost not in self._needs_target
        ]
        if ranked:
            card, _definition, _score = ranked[0]
            # 收起态的 PLAY_CARD 只展开手牌，尚未拖牌，不能记作一次出牌失败。
            self._pending_play = card.index if state.hand_expanded else None
            self._pending_cost = card.cost
            return Action(type=ActionType.PLAY_CARD, card_index=card.index)

        # P2 攻击声明：求解器说值得打才打
        attack = self._attack(state)
        if attack is not None:
            return attack

        # P4-d 收尾
        return Action(type=ActionType.END_TURN)

    def _targeting(self, state: GameState) -> Action:
        """「選擇目標」阶段：点一个单位把选择做完。

        实机上同一个「選擇目標」按钮底下至少有两种提示，要选的对象相反：

          「擊暈1個敵軍單位」            → 点**敌方**单位
          「選擇1個單位或地標進行替換」  → 点**我方**单位（点敌方完全没反应）

        光看按钮模板区分不出来，只能按顺序试：先点敌方（击晕最常见），
        还停在 targeting 就点我方，两边都不行才取消。

        之前这里直接 CANCEL，而 cancel 点的是战场空白处 —— 在「選擇目標」
        状态下那个位置根本不响应，于是每帧都在点同一处，看门狗超时。
        """
        self._target_attempt += 1
        if self._target_attempt == 1 and state.enemy_units:
            return Action(
                type=ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0}
            )
        if self._target_attempt == 2 and state.my_units:
            return Action(
                type=ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0}
            )
        # 两次都点不动（或者场上没单位可选）：记下这张牌需要目标，换下一张
        if self._pending_cost is not None:
            self._needs_target.add(self._pending_cost)
            self._pending_play = None
        self._target_attempt = 0
        return Action(type=ActionType.CANCEL)

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
        attackers = [i for i, u in enumerate(state.my_units) if u.can_attack]
        if not attackers:
            return None
        return Action(
            type=ActionType.ATTACK,
            target="nexus",
            raw={"attackers": attackers},
        )

