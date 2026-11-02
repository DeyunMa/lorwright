"""战斗求解器：精确枚举格挡分配与攻击声明。

LoR 的战斗是「攻方声明攻击者 → 守方分配格挡者」，攻方**不能**指定打谁
（除非带挑战者）。所以「攻击某个单位」不是合法动作。

动作空间很小（场上限 6 单位，格挡分配 ≤ 13327 种），可以穷举出最优解——
这类决策不该进 L2，穷举比启发式既准又便宜。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

MAX_BOARD = 6


class Keyword(StrEnum):
    ELUSIVE = "elusive"            # 灵巧：只能被灵巧单位格挡
    FEARSOME = "fearsome"          # 恐惧：只能被攻击力 >= 3 的单位格挡
    CHALLENGER = "challenger"      # 挑战者：攻方指定格挡者（暂不建模）
    OVERWHELM = "overwhelm"        # 碾压：对格挡者的溢出伤害穿透到水晶
    QUICK_ATTACK = "quick_attack"  # 快速攻击：先手伤害足以击杀则不受伤
    TOUGH = "tough"                # 坚韧：受到的伤害 -1


@dataclass(frozen=True)
class Combatant:
    """参与战斗的单位。"""

    attack: int
    health: int
    keywords: frozenset[Keyword] = frozenset()
    name: str = ""

    @property
    def value(self) -> int:
        """单位价值代理指标：攻 + 血。用来比较交换的亏赚。"""
        return self.attack + self.health


@dataclass(frozen=True)
class BlockPlan:
    """守方的最优格挡方案。

    pairs 里的下标指向**本次传入的** attackers / blockers 列表，
    不是原始场面列表。
    """

    pairs: tuple[tuple[int, int], ...] = ()  # (攻击者下标, 格挡者下标)
    nexus_damage: int = 0                    # 打到守方水晶的伤害
    attacker_loss: int = 0                   # 攻方阵亡单位的总价值
    blocker_loss: int = 0                    # 守方阵亡单位的总价值

    def describe(self, attackers: list[Combatant], blockers: list[Combatant]) -> str:
        if not self.pairs:
            return f"不格挡，水晶受 {self.nexus_damage} 点伤害"
        parts = [
            f"{blockers[b].name or f'格挡者{b}'} 挡 {attackers[a].name or f'攻击者{a}'}"
            for a, b in self.pairs
        ]
        return (
            f"{'、'.join(parts)}；水晶受 {self.nexus_damage} 点伤害，"
            f"我方阵亡价值 {self.blocker_loss}、对方 {self.attacker_loss}"
        )


@dataclass(frozen=True)
class AttackPlan:
    """攻方的最优攻击声明。"""

    attackers: tuple[int, ...] = ()  # 下标，指向传入的 attackers 列表
    block: BlockPlan = BlockPlan()   # 对手的最优应对（pairs 指向 attackers 子集）
    score: float = 0.0

    @property
    def nexus_damage(self) -> int:
        return self.block.nexus_damage


def can_block(blocker: Combatant, attacker: Combatant) -> bool:
    """格挡者能否挡住这个攻击者。"""
    if Keyword.ELUSIVE in attacker.keywords and Keyword.ELUSIVE not in blocker.keywords:
        return False
    if Keyword.FEARSOME in attacker.keywords and blocker.attack < 3:
        return False
    return True


def _incoming(damage: int, target: Combatant) -> int:
    if Keyword.TOUGH in target.keywords:
        return max(0, damage - 1)
    return damage


def strike(attacker: Combatant, blocker: Combatant) -> tuple[int, bool, bool]:
    """单次交锋结算。

    返回 (穿透到守方水晶的伤害, 攻方是否阵亡, 守方是否阵亡)。
    """
    to_blocker = _incoming(attacker.attack, blocker)
    blocker_dies = to_blocker >= blocker.health

    # 快速攻击：先手打死对方，自己就不吃反伤
    if Keyword.QUICK_ATTACK in attacker.keywords and blocker_dies:
        to_attacker = 0
    else:
        to_attacker = _incoming(blocker.attack, attacker)

    trample = 0
    if Keyword.OVERWHELM in attacker.keywords:
        trample = max(0, to_blocker - blocker.health)

    return trample, to_attacker >= attacker.health, blocker_dies


def best_blocking(
    attackers: list[Combatant],
    blockers: list[Combatant],
    *,
    limit: int = 200_000,
) -> BlockPlan:
    """守方的最优格挡分配。

    守方偏好（字典序）：先最小化自己水晶受到的伤害，再最小化「我方损失 − 对方损失」。
    超出搜索上限时返回已找到的最优解（任意时刻算法）。
    """
    best: tuple[tuple[int, int], BlockPlan] | None = None
    used = [False] * len(attackers)
    pairs: list[tuple[int, int]] = []
    nodes = 0

    def evaluate() -> None:
        nonlocal best
        assigned = dict(pairs)
        nexus = 0
        attacker_loss = 0
        blocker_loss = 0
        for j, atk in enumerate(attackers):
            if j not in assigned:
                nexus += atk.attack
                continue
            blk = blockers[assigned[j]]
            trample, atk_dies, blk_dies = strike(atk, blk)
            nexus += trample
            if atk_dies:
                attacker_loss += atk.value
            if blk_dies:
                blocker_loss += blk.value
        key = (nexus, blocker_loss - attacker_loss)
        if best is None or key < best[0]:
            best = (key, BlockPlan(tuple(pairs), nexus, attacker_loss, blocker_loss))

    def dfs(i: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > limit:
            return
        if i == len(blockers):
            evaluate()
            return
        dfs(i + 1)  # 这个格挡者不挡
        blk = blockers[i]
        for j, atk in enumerate(attackers):
            if used[j] or not can_block(blk, atk):
                continue
            used[j] = True
            pairs.append((j, i))
            dfs(i + 1)
            pairs.pop()
            used[j] = False

    dfs(0)
    return best[1] if best else BlockPlan()


def _attacker_subsets(
    attackers: list[Combatant], exact_limit: int
) -> list[tuple[int, ...]]:
    """要枚举的攻击者子集。

    n 小的时候全枚举（2^n − 1）；大的时候退化成「按攻击力从高到低的前 k 个」，
    因为实战中不会出现「打小留大」这种声明。
    """
    n = len(attackers)
    if n <= exact_limit:
        out: list[tuple[int, ...]] = []
        for k in range(1, n + 1):
            out.extend(combinations(range(n), k))
        return out
    order = sorted(range(n), key=lambda i: attackers[i].attack, reverse=True)
    return [tuple(sorted(order[:k])) for k in range(1, n + 1)]


def best_attack(
    attackers: list[Combatant],
    blockers: list[Combatant],
    *,
    nexus_weight: float = 3.0,
    exact_limit: int = 4,
    limit: int = 200_000,
) -> AttackPlan:
    """攻方的最优攻击声明。

    评分：`脸伤 * nexus_weight − 我方阵亡价值 + 对方阵亡价值`。
    nexus_weight 越大越激进（快攻调高）。
    """
    if not attackers:
        return AttackPlan()

    best: tuple[float, AttackPlan] | None = None
    for idx in _attacker_subsets(attackers, exact_limit):
        chosen = [attackers[i] for i in idx]
        block = best_blocking(chosen, blockers, limit=limit)
        score = block.nexus_damage * nexus_weight - block.attacker_loss + block.blocker_loss
        if best is None or score > best[0]:
            best = (score, AttackPlan(attackers=idx, block=block, score=score))
    return best[1] if best else AttackPlan()


def max_nexus_damage(
    attackers: list[Combatant],
    blockers: list[Combatant],
    *,
    exact_limit: int = 4,
    limit: int = 200_000,
) -> int:
    """对手最优格挡下，我方最多能打出多少脸伤。用于斩杀判定。"""
    if not attackers:
        return 0

    best = 0
    for idx in _attacker_subsets(attackers, exact_limit):
        chosen = [attackers[i] for i in idx]
        best = max(best, best_blocking(chosen, blockers, limit=limit).nexus_damage)
    return best


def is_lethal(
    attackers: list[Combatant],
    blockers: list[Combatant],
    enemy_nexus_hp: int,
    **kwargs,
) -> bool:
    """这一波能不能直接打死对手水晶。"""
    return max_nexus_damage(attackers, blockers, **kwargs) >= enemy_nexus_hp
