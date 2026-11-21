"""通用决策规则：不依赖任何英雄包的机制层。

分层顺序（在 Router 里排在英雄包之后）：

    英雄包特殊规则 → 英雄优先出英雄 → 攻击/格挡序列 → fallback

英雄包弃权（返回 None）时这些规则才接手，所以伊莉丝这种
自带完整打法的包不受影响。
"""

from __future__ import annotations

from lorwright.core.decide.base import Policy
from lorwright.core.models import Action, ActionType, GameState, Rect, UIState, Unit


class HeroFirstPolicy(Policy):
    """手牌里有英雄就优先出英雄（用户确认的通用原则）。

    例外由英雄包自己维护：英雄包排在这一层前面，
    想推迟下英雄就在自己的 decide 里先出动作。
    """

    name = "hero_first"
    version = "1.0.0"

    def __init__(self, champion_names: frozenset[str]) -> None:
        self.champion_names = champion_names

    def decide(self, state: GameState) -> Action | None:
        if (state.ui_state is not UIState.MY_TURN_IDLE or not state.hand_expanded
                or board_count(state) >= 6):
            return None
        for card in state.hand:
            if (card.name in self.champion_names and card.drag_point_valid
                    and 0 <= card.cost <= max(0, state.mana)):
                return Action(type=ActionType.PLAY_CARD, card_index=card.index,
                              raw={"unit_card": True})
        return None


class OptionalChoicePolicy(Policy):
    """候选策略未知时，使用界面明确提供的跳过。"""

    name = "optional_choice"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is UIState.OPTIONAL_CHOICE:
            return Action(type=ActionType.SKIP_CHOICE)
        return None


class RequiredChoicePolicy(Policy):
    """强制三选一没有跳过：候选收益未知时选最左一张。"""

    name = "required_choice"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is UIState.REQUIRED_CHOICE:
            return Action(type=ActionType.PICK_CHOICE, card_index=0)
        return None


class CombatConfirmPolicy(Policy):
    """战斗结算/提交声明：按钮是「結算」，答案唯一，点确认。"""

    name = "combat_confirm"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is UIState.COMBAT_RESOLVING:
            return Action(type=ActionType.CONFIRM)
        return None


class ExpandHandPolicy(Policy):
    """我方回合手牌收起时，先展开手牌；展开动作不会打出牌。"""

    name = "expand_hand"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is UIState.MY_TURN_IDLE and not state.hand_expanded and state.hand:
            return Action(type=ActionType.EXPAND_HAND)
        return None


class PlayUnitPolicy(Policy):
    """场面未满 6 时，按费用从低到高打已知或有可出单位视觉依据的牌。"""

    name = "play_unit"
    version = "1.0.0"

    def __init__(self, lookup, board_limit: int = 6) -> None:
        self.lookup = lookup
        self.board_limit = board_limit

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is not UIState.MY_TURN_IDLE or not state.hand_expanded:
            return None
        if board_count(state) >= self.board_limit:
            return None
        playable = []
        for card in state.hand:
            if not card.drag_point_valid or card.cost < 0 or card.cost > max(0, state.mana):
                continue
            definition = self.lookup(card.name)
            if definition is None:
                if not card.visible_playable_unit:
                    continue
                strength = 0
            elif getattr(definition, "is_unit", False):
                strength = definition.attack + definition.health
            else:
                continue
            playable.append((card.cost, -strength, card))
        if not playable:
            return None
        playable.sort(key=lambda item: (item[0], item[1]))
        return Action(type=ActionType.PLAY_CARD, card_index=playable[0][2].index,
                      raw={"unit_card": True})


class UnknownCardPolicy(Policy):
    """未知牌不猜测出牌，也不阻塞其他策略；保留类供现有装配方使用。

    有 visible_playable_unit 依据的牌由 PlayUnitPolicy 处理，其余局部未知牌
    只跳过；None 是弃权，NO_OP 则会终止路由，不能用来表示跳过一张牌。
    """

    name = "unknown_card"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        return None


def board_count(state: GameState) -> int:
    """满场判断的单位数：帧抖只会少读，取两帧较大值兜底。"""
    return state.my_units_floor if state.my_units_floor is not None else len(state.my_units)


def _rect_close(a: Rect, b: Rect) -> bool:
    return (abs(a.x - b.x) <= 12 and abs(a.y - b.y) <= 12
            and abs(a.w - b.w) <= 12 and abs(a.h - b.h) <= 12)


def same_unit_identity(a: Unit, b: Unit) -> bool:
    """同一单位的身份证据（不含位置）：名字/攻击/生命一致。"""
    return a.name == b.name and a.attack == b.attack and a.health == b.health


def same_unit(a: Unit, b: Unit) -> bool:
    """同一单位跨帧：位置容差内且身份一致，矩形必须有效。

    不含 can_attack/keyword/stun 图标证据——紫色可选中辉光下这些
    会随脉冲抖动，而动作只需要确认还是同一个单位。
    """
    return (same_unit_identity(a, b)
            and a.rect.w > 0 and a.rect.h > 0 and b.rect.w > 0 and b.rect.h > 0
            and _rect_close(a.rect, b.rect))


def weakest_replace_index(units: list[Unit], pool: list[int]) -> int:
    """替换目标：攻击+生命最低者（含并列取最左）。

    不读单位身份；名字能被识别的是英雄（如升级后的吉茵珂丝），
    不参与替换。数值未读出的单位按最大处理，避免误换未知大件。
    """
    eligible = [i for i in pool if not units[i].name] or list(pool)

    def value(index: int) -> int:
        unit = units[index]
        if unit.attack < 0 or unit.health < 0:
            return 1 << 20
        return unit.attack + unit.health

    return min(eligible, key=lambda i: (value(i), i))


class ReplacePromptPolicy(Policy):
    """满场打出单位要求替换友军：选攻击+生命最低者（含并列取最左）。

    紫色可选中辉光下 my_units 会随脉冲逐帧增减；只在引擎注入的
    跨帧稳定单位集合（my_units_stable）里选目标，没有稳定单位时
    回退全表最弱——实际点击仍由就绪门禁要求目标跨帧稳定后才放行。
    """

    name = "replace_prompt"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if (state.ui_state is not UIState.TARGETING or not state.replace_prompt
                or not state.my_units):
            return None
        stable = state.my_units_stable
        pool = sorted(stable) if stable else list(range(len(state.my_units)))
        index = weakest_replace_index(state.my_units, pool)
        return Action(type=ActionType.SELECT_TARGET, raw={"enemy": False, "index": index})


class TargetingPolicy(Policy):
    """目标类型未识别时等待，由有依据的专属策略处理。"""

    name = "targeting"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is not UIState.TARGETING:
            return None
        # 法术变体选项（实机 20261121T140928「希格斯 彈跳炸彈」二选一）：
        # 不读变体语义，固定选左侧——单体版本在任何敌数下都可结算。
        if state.spell_options:
            return Action(type=ActionType.SELECT_TARGET, raw={"option": 0})
        # 「跳過」= 可选目标提示：能认出敌方目标就选，否则按跳过放弃该效果。
        if state.action_prompt == "action_skip":
            if state.enemy_units:
                return Action(type=ActionType.SELECT_TARGET,
                              raw={"enemy": True, "index": 0})
            return Action(type=ActionType.END_TURN)
        # 必选「選擇目標」提示（实机 20261121T142531 彈跳炸彈变体后的单体
        # 目标阶段）：默认选首个跨帧稳定的敌方单位；友方目标提示由
        # replace_prompt 证据分流到 ReplacePromptPolicy，不走到这里。
        if state.action_prompt == "action_target" and state.enemy_units:
            stable = state.enemy_units_stable
            index = sorted(stable)[0] if stable else 0
            return Action(type=ActionType.SELECT_TARGET,
                          raw={"enemy": True, "index": index})
        return Action(type=ActionType.NO_OP)


class BlockingPolicy(Policy):
    """格挡（用户确认的规则，2026-11-05）：

    1. 能格挡就格挡；
    2. 优先「无死换」：blocker 生命 > 攻击者攻击，且 blocker 攻击 >=
       攻击者生命（我活敌死）；
    3. 其次「互换」：blocker 会死但能带走攻击者，在能互换的候选里
       选价值最低的（例：对面 3/1，用 1/1 换，不用 2/2 送）；
    4. 挡了必死且杀不死对方 → 不挡这个攻击者，宁可挨脸。
    5. 格挡资格（REA 已验证规则组件，2026-11-06）：击晕/不可移动/
       鲁莽的单位不能格挡；恐惧攻击者，攻击力 <3 的单位挡不住
       （research/lor-client-07.10.013-v1/data/native-rule-components.json，
       GetFearsomeBlockingValue 原生返回 3）；隐秘攻击者只能被隐秘或
       锐目（BlockElusive）单位格挡；硬派攻击者只能被生命 >=3 的单位格挡
       （官方关键词文本，globals-en_us.json "Brash"）。
    6. 蛮力攻击者被格挡时，超过格挡者生命值的伤害计入主堡伤害。
    声明后下一 tick 确认。
    """

    name = "blocking"
    version = "1.0.0"

    def __init__(self) -> None:
        self._declared = False

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is not UIState.BLOCKING:
            self._declared = False
            return None
        if self._declared:
            return Action(type=ActionType.CONFIRM)
        attackers = state.enemy_attackers or state.enemy_units
        committed = _committed_blocks(state.my_units, attackers)
        committed_attackers = {a for a, _ in committed}
        committed_blockers = {b for _, b in committed}
        # 行内已锁定指派按本帧全表判定（它是对局状态，不是读数）。
        my_stable = state.my_units_stable
        enemy_stable = state.enemy_units_stable
        free_all = [i for i in range(len(attackers)) if i not in committed_attackers]
        bench_all = [i for i in range(len(state.my_units))
                     if i not in committed_blockers]
        # 新指派只在跨帧稳定单位里规划，紫色屏障辉光下计数抖动时
        # 计划不再随帧翻转；一个稳定单位都没有时退回全表，实际点击
        # 仍由就绪门禁按单位身份放行。
        free_attackers = ([i for i in free_all if enemy_stable is None or i in enemy_stable]
                          or free_all)
        bench = ([i for i in bench_all if my_stable is None or i in my_stable]
                 or bench_all)
        sub = plan_blocks([state.my_units[i] for i in bench],
                          [attackers[i] for i in free_attackers])
        pairs = [(bench[b], free_attackers[a]) for b, a in sub]
        covered = {a for _, a in pairs}
        # 稳定格挡者覆盖了稳定攻击者后仍有未验证的攻击者未被覆盖：
        # 不确认——等下一帧身份稳定再规划。
        if (enemy_stable is not None and any(
                i not in enemy_stable and i not in committed_attackers
                and i not in covered for i in free_all)):
            return Action(type=ActionType.NO_OP)
        if not pairs:
            return Action(type=ActionType.CONFIRM)
        return Action(type=ActionType.BLOCK, raw={"pairs": pairs})

    def on_action_outcome(self, action: Action, before: GameState, after: GameState) -> None:
        """成功声明后才确认；成功结果已离开格挡时清除本轮声明。"""
        if after.ui_state is not UIState.BLOCKING:
            self._declared = False
        elif action.type is ActionType.BLOCK and before.ui_state is UIState.BLOCKING:
            self._declared = True


# 1 点水晶伤害折算的单位价值权重（水晶血不可再生，单位可以）
FACE_DAMAGE_WEIGHT = 2
# 指派穷举的规模上限；6v6 全部主子映射约 3700 种，毫秒级。
MAX_ASSIGNMENT_COMBINATIONS = 20000


def _pair_loss(blocker, attacker):
    # 一次 (blocker, attacker) 格挡的损失：阵亡单位价值 + 残留威胁
    lost = blocker.attack + blocker.health if blocker.health <= attacker.attack else 0
    remaining = max(0, attacker.health - blocker.attack)
    return lost, remaining


# 恐惧格挡门槛：blocker 攻击力必须 >= 3 才能挡恐惧攻击者。
# 来源：Shared.Cards.CardState.GetFearsomeBlockingValue 原生函数恒返 3
# （research/lor-client-07.10.013-v1/data/native-rule-components.json，
#  evidence ev_a5d7d7b2…，2026-11-06 接入）。
FEARSOME_THRESHOLD = 3

# 硬派格挡门槛：blocker 生命必须 >= 3。
# 来源：官方关键词文本 "Can only be blocked by enemies with 3 or more Health."
# （analysis/full-resource/globals-en_us.json，name=Brash，2026-11-06 核对）。
BRASH_THRESHOLD = 3

#: 能挡隐秘攻击者的关键词（任一即可）；锐目不使攻击获得隐秘。
ELUSIVE_BLOCK_KEYWORDS = frozenset({"Elusive", "BlockElusive"})

#: 这些关键词存在时单位不能格挡（StatePreventsBlock：非 Creature、
#  Immobile(3)、Reckless(1)、Stunned(80) 阻止格挡；击晕另有专用字段）。
NO_BLOCK_KEYWORDS = frozenset({"Immobile", "Reckless"})


def _can_block(blocker, attacker) -> bool:
    """格挡资格。攻击力未识别（-1）按能挡就挡处理（用户规则 1）。"""
    if blocker.stunned or NO_BLOCK_KEYWORDS & set(blocker.keywords):
        return False
    if "Elusive" in attacker.keywords and not (
        ELUSIVE_BLOCK_KEYWORDS & set(blocker.keywords)
    ):
        return False
    if "Fearsome" in attacker.keywords:
        if blocker.attack >= 0 and blocker.attack < FEARSOME_THRESHOLD:
            return False
    if "Brash" in attacker.keywords:
        if blocker.health >= 0 and blocker.health < BRASH_THRESHOLD:
            return False
    return True


#: 格挡行判定的最小行距：单位中心比后排最低单位高这么多视为已在行内。
_BLOCK_LANE_MIN_SEPARATION = 120
#: 格挡行单位归属于正上方攻击者的横向容差。
_BLOCK_LANE_ALIGN_PX = 150


def _committed_blocks(my_units, attackers):
    """已在格挡行的单位及其正对的攻击者 (attacker_idx, blocker_idx)。

    挑战者等拉拽会把格挡者直接放进格挡行；该指派由对局锁定——既不能
    改派这个单位，也不能换别的单位去挡同一个攻击者（实机
    20261121T071021：对锁定指派重发拖拽无任何可见结果）。
    行位按相对高度判定：显著高于后排最低单位的视为已在行内；
    行内单位一律退出待指派集合，横向对正的攻击者视为已被覆盖。
    """
    if not attackers or not my_units:
        return []
    back_y = max(u.rect.center[1] for u in my_units)
    committed = []
    for mi, unit in enumerate(my_units):
        if unit.rect.center[1] > back_y - _BLOCK_LANE_MIN_SEPARATION:
            continue
        nearest = min(
            range(len(attackers)),
            key=lambda ai: abs(attackers[ai].rect.center[0]
                               - unit.rect.center[0]))
        if (abs(attackers[nearest].rect.center[0] - unit.rect.center[0])
                <= _BLOCK_LANE_ALIGN_PX):
            committed.append((nearest, mi))
    return committed


def plan_blocks(my_units, attackers):
    # 穷举全部指派，按用户格挡原则取总损失最小：
    # 脸伤（未挡攻击者的攻击力以及蛮力的溢出伤害 x FACE_DAMAGE_WEIGHT）
    # + 阵亡单位价值 + 被打残但存活的攻击者残留威胁。
    # 组合超上限退回贪心；攻击力未识别（-1）按能挡就挡处理。
    attackers = list(attackers)
    my_units = list(my_units)
    if not my_units or not attackers:
        return []
    # 攻/血任一未识别就退回贪心：穷举评分里的“阵亡价值/残留威胁”
    # 会把 -1 当成真实数值，算出负损失或零威胁。
    if any(u.attack < 0 or u.health < 0 for u in attackers) or any(
        u.attack < 0 or u.health < 0 for u in my_units
    ):
        return _greedy_blocks(my_units, attackers)

    import itertools

    # 每个攻击者的合法候选先过滤（恐惧/击晕等资格规则），
    # 穷举空间随之缩小。
    options_per_attacker = [
        [None] + [i for i, u in enumerate(my_units) if _can_block(u, attacker)]
        for attacker in attackers
    ]

    total = 1
    for opts in options_per_attacker:
        total *= max(1, len(opts))
        if total > MAX_ASSIGNMENT_COMBINATIONS:
            return _greedy_blocks(my_units, attackers)

    best = None
    for assignment in itertools.product(*options_per_attacker):
        used = [b for b in assignment if b is not None]
        if len(set(used)) != len(used):
            continue
        face = 0
        lost = 0
        threat = 0
        for a_idx, b_idx in enumerate(assignment):
            attacker = attackers[a_idx]
            if b_idx is None:
                face += attacker.attack
                continue
            blocker = my_units[b_idx]
            # 用户规则：白死（blocker 死但杀不死对面）直接禁止这个配对
            if blocker.health <= attacker.attack and blocker.attack < attacker.health:
                break
            if "Overwhelm" in attacker.keywords:
                face += max(0, attacker.attack - blocker.health)
            lost_part, remaining = _pair_loss(blocker, attacker)
            lost += lost_part
            threat += remaining
        else:
            score = face * FACE_DAMAGE_WEIGHT + lost + threat
            key = (score, -len(used))
            if best is None or key < best[0]:
                best = (key, assignment)
    if best is None:
        return []
    return [
        (b_idx, a_idx)
        for a_idx, b_idx in enumerate(best[1])
        if b_idx is not None
    ]


def _greedy_blocks(my_units, attackers):
    # 穷举超限时的退路：威胁降序，能带走攻击者的最低价值 blocker。
    # 攻击力/生命值未识别（-1）时仍要能挡：感知层目前只给位置，
    # 不能因为读数缺失就把整轮格挡放掉。
    pairs = []
    used = set()
    ranked = sorted(
        enumerate(attackers),
        key=lambda item: -(item[1].attack + item[1].health),
    )
    for a_idx, attacker in ranked:
        if attacker.attack == 0:
            continue
        best = None
        for b_idx, blocker in enumerate(my_units):
            if b_idx in used or not _can_block(blocker, attacker):
                continue
            if (
                attacker.attack >= 0
                and blocker.attack >= 0
                and blocker.attack < attacker.health
            ):
                continue
            overflow = (
                max(0, attacker.attack - blocker.health)
                if "Overwhelm" in attacker.keywords
                and attacker.attack >= 0 and blocker.health >= 0 else 0
            )
            if attacker.attack < 0:
                # 不知道对方攻击力：优先选能活下来的低价值单位。
                rank = (0 if blocker.health > 0 else 1,
                        blocker.attack + blocker.health)
            else:
                rank = (0 if blocker.health > attacker.attack else 1,
                        blocker.attack + blocker.health + overflow * FACE_DAMAGE_WEIGHT)
            if best is None or rank < best[0]:
                best = (rank, b_idx)
        if best is not None:
            used.add(best[1])
            pairs.append((best[1], a_idx))
    return pairs


# 单位在攻击行（y 中心在此上方）视为已声明进攻。
# 与伊莉丝包同源：已声明后按钮变「確認」，状态机认不出来。
ATTACK_ROW_MAX_Y = 800


class AttackWhenTokenPolicy(Policy):
    """有攻击令牌时让可攻击单位进攻，声明后下一 tick 确认。

    攻击令牌按回合轮换，没令牌时弃权交给 fallback 结束回合。
    """

    name = "attack_when_token"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is not UIState.MY_TURN_IDLE or not state.my_units:
            return None
        in_row = any(u.rect.center[1] < ATTACK_ROW_MAX_Y for u in state.my_units)
        if in_row:
            return Action(type=ActionType.CONFIRM)
        if not state.has_attack_token:
            return None
        stable = state.my_units_stable
        can = [i for i, unit in enumerate(state.my_units)
               if unit.can_attack and not unit.stunned]
        if not can:
            return None
        # 优先跨帧稳定单位；没有稳定单位时退回全部可攻击单位，
        # 就绪门禁仍会要求每个攻击者跨帧同一单位才放行。
        attackers = tuple(i for i in can if stable is None or i in stable) or tuple(can)
        return Action(type=ActionType.ATTACK, raw={"attackers": attackers})

