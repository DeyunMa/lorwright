"""通用决策规则：不依赖任何英雄包的机制层。

分层顺序（在 Router 里排在英雄包之后）：

    英雄包特殊规则 → 英雄优先出英雄 → 攻击/格挡序列 → fallback

英雄包弃权（返回 None）时这些规则才接手，所以伊莉丝这种
自带完整打法的包不受影响。
"""

from __future__ import annotations

from lorwright.decide.base import Policy
from lorwright.models import Action, ActionType, GameState, UIState


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
        if state.ui_state is not UIState.MY_TURN_IDLE or not state.hand_expanded:
            return None
        for card in state.hand:
            if card.name in self.champion_names and card.cost <= state.mana:
                return Action(type=ActionType.PLAY_CARD, card_index=card.index)
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
            return Action(type=ActionType.PLAY_CARD, card_index=state.hand[0].index)
        return None


class PlayUnitPolicy(Policy):
    """通用下单位：场面未满 6 时，按费用从低到高打已知单位。"""

    name = "play_unit"
    version = "1.0.0"

    def __init__(self, lookup, board_limit: int = 6) -> None:
        self.lookup = lookup
        self.board_limit = board_limit

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is not UIState.MY_TURN_IDLE or not state.hand_expanded:
            return None
        if len(state.my_units) >= self.board_limit:
            return None
        playable = []
        for card in state.hand:
            if card.cost < 0 or card.cost > state.mana:
                continue
            definition = self.lookup(card.name)
            if definition is None or not getattr(definition, "is_unit", False):
                continue
            playable.append((card.cost, -(definition.attack + definition.health), card))
        if not playable:
            return None
        playable.sort(key=lambda item: (item[0], item[1]))
        return Action(type=ActionType.PLAY_CARD, card_index=playable[0][2].index)


class TargetingPolicy(Policy):
    """通用选目标：手牌展开时先选手牌（弃牌提示），再敌方单位、我方单位、敌方水晶。"""

    name = "targeting"
    version = "1.0.0"

    def decide(self, state: GameState) -> Action | None:
        if state.ui_state is not UIState.TARGETING:
            return None
        # 「棄置1張牌」这类提示会展开手牌让玩家点手牌；单位/法术目标时手牌通常是收起的。
        if state.hand_expanded and state.hand:
            return Action(type=ActionType.SELECT_TARGET, raw={"hand": True, "index": 0})
        if state.enemy_units:
            return Action(type=ActionType.SELECT_TARGET, raw={"enemy": True, "index": 0})
        if state.my_units:
            return Action(type=ActionType.SELECT_TARGET, raw={"enemy": False, "index": 0})
        if state.enemy_nexus_hp > 0:
            return Action(type=ActionType.SELECT_TARGET, raw={"nexus": True})
        return Action(type=ActionType.CANCEL)


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
        pairs = plan_blocks(state.my_units, attackers)
        self._declared = True
        if not pairs:
            return Action(type=ActionType.CONFIRM)
        return Action(type=ActionType.BLOCK, raw={"pairs": pairs})


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
        u.health < 0 for u in my_units
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
    """有攻击令牌就全体进攻，声明后下一 tick 确认。

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
        attackers = tuple(range(len(state.my_units)))
        return Action(type=ActionType.ATTACK, raw={"attackers": attackers})

