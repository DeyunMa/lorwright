"""对局外地图自动循环：点节点 → 处理事件 → 进战斗 → 回地图。

用户规则（2026-11-05 确认）：
- 沿发光线找带蓝色指向标的下一节点（已完成节点带绿色对勾，自动跳过）；
- 商店节点：旅行 → 离开（购买后续细化）；
- 战斗节点：战斗按钮 → Engine 接管；
- 休息节点（加号）：点第一个选项加血，满血点不动就离开；
- 节点内操作完成后英雄不自动离开，必须点击下一节点移动；
- 分叉按随机事件 > 商店 > 道具或法术 > 金币赠送选择，同级随机。

坐标空间：1920×1080 设计尺寸。mapnav 直接吃设计帧，点击不再 x2。
节点面板的金色按钮（旅行／战斗）由 perceive.panels.action_button 动态检测，
不再依赖固定坐标；2026-11-07 实机校准。
"""

from __future__ import annotations

import random
import time

import cv2
import numpy as np

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.decide.adventure import pick_affordable_power, pick_lowest_weekly, pick_map_node
from lorwright.core.decide.rewards import pick_card_reward, pick_hero_item_reward, pick_reward
from lorwright.core.decide.support import pick_support_group
from lorwright.core.device.base import Device
from lorwright.core.loop.engine import Engine
from lorwright.core.loop.outcome import LoopResult
from lorwright.core.models import Action, ActionType, GameState, UIState
from lorwright.core.perceive.adventure_scene import (
    button_is,
    find_home_adventure_entry,
    find_resume_adventure_button,
    find_weekly_entry,
    find_weekly_start,
    is_battle_detail,
    is_completed_panel,
    is_map,
    recognize_weekly_adventures,
    reward_timeout_continue,
    shop_leave_button,
    weekly_detail_stars,
)
from lorwright.core.perceive.astrologer import (
    SLOTS as ASTROLOGER_SLOTS,
)
from lorwright.core.perceive.astrologer import (
    astrologer_buy_button,
    astrologer_gold,
    astrologer_leave_button,
    astrologer_map_gold,
    astrologer_offers,
    astrologer_selection,
    is_power_vendor,
    same_astrologer_offers,
)
from lorwright.core.perceive.buttons import find_continue_button
from lorwright.core.perceive.healer import healer_heal_button, is_healer_screen
from lorwright.core.perceive.mapnav import (
    _current_completed_node_visible,
    empty_point,
    node_kind,
    panel_open,
    reachable_nodes,
)
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.perceive.panels import action_button
from lorwright.core.perceive.result_screen import is_adventure_victory, result_screen
from lorwright.core.perceive.revive_screen import find_revive_button
from lorwright.core.perceive.reward_screen import (
    card_reward_confirm_button,
    card_reward_diagnostics,
    card_reward_selection,
    card_reward_target,
    hero_item_choose_disabled,
    hero_item_choose_enabled,
    hero_item_hero_selection,
    hero_item_item_selection,
    is_card_reward_screen,
    is_hero_item_reward_screen,
    is_power_screen,
    power_choose_enabled,
    power_selection,
    power_unselected,
    recognize_card_rewards,
    recognize_hero_item_cards,
    recognize_hero_items,
    recognize_powers,
    same_card_reward_choices,
)
from lorwright.core.perceive.support_screen import (
    is_support_screen,
    recognize_support_choices,
    same_support_choices,
    support_confirm_button,
    support_selection,
)
from lorwright.core.runtime.session import StopRequested, checkpoint, record_event, report
from lorwright.core.util import snapshot
from lorwright.core.util.logger import logger


def _continue_view(image):
    """记录按钮上方的内容，用于区分同位置的连续结果页。"""
    height, width = image.shape[:2]
    content = image[int(height * 0.15):int(height * 0.8),
                    int(width * 0.2):int(width * 0.8)]
    return cv2.resize(content, (100, 60), interpolation=cv2.INTER_AREA)


class AdventureLoop:
    BATTLE_STATES = {
        UIState.MULLIGAN,
        UIState.MY_TURN_IDLE,
        UIState.BLOCKING,
        UIState.TARGETING,
        UIState.OPTIONAL_CHOICE,
        UIState.COMBAT_RESOLVING,
        UIState.ENEMY_TURN,
    }

    def __init__(self, settings, engine, device: Device, *, pack,
                 sample_hero_item_jinx: bool = False) -> None:
        self.settings = settings
        self.engine = engine
        self.device = device
        self.pack = pack
        self.sample_hero_item_jinx = sample_hero_item_jinx
        self.coords = settings.adventure.to_coords()
        self.translator = ActionTranslator(settings.layout.to_layout())
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self.rng = random.Random()
        self.result = LoopResult("stopped", "iteration_limit")
        self._last_scene = None
        self._details: dict = {}
        self._awaiting_battle_reward = False

    def run(self, max_nodes: int = 30) -> LoopResult:
        """max_nodes 是冒险循环迭代预算，不是已完成节点数。"""
        self.result = LoopResult("stopped", "iteration_limit")
        self._details = dict(iteration=0, iteration_limit=max_nodes)
        try:
            battle_result = self._run(max_nodes)
        except StopRequested:
            report("stopping", "stop_requested", **self._details)
            raise
        except Exception as exc:
            report("error", type(exc).__name__, error=str(exc), **self._details)
            raise
        if battle_result is not None:
            return battle_result
        report(self.result.status, self.result.reason, **self._details)
        return self.result

    def _run(self, max_nodes: int) -> LoopResult | None:
        self.engine.parser.load()
        last_continue = None
        last_continue_view = None
        pending_image = None
        selected_weekly_stars = None
        for iteration in range(1, max_nodes + 1):
            self._details.update(iteration=iteration)
            report("adventure", **self._details)
            image = pending_image if pending_image is not None else self._frame()
            pending_image = None
            normalized = self._reward_design(image)
            if normalized is not None and is_adventure_victory(normalized[0]):
                self._complete_adventure(image)
                return
            if self.sample_hero_item_jinx:
                if normalized is not None:
                    design, scale = normalized
                    heroes = recognize_hero_item_cards(design)
                    if (heroes is not None and "jinx" in heroes
                            and hero_item_choose_disabled(design)):
                        x = (780, 1125)[heroes.index("jinx")]
                        self._tap(*scale.to_device(x, 430))
                        self._wait(2, reason="hero_item_sample", wait_s=2)
                        self._snapshot(self._frame(), tag="hero_item_jinx_sample")
                        return
                self._snapshot(image, tag="hero_item_sample_precondition_failed")
                return
            timeout_button = reward_timeout_continue(normalized[0]) if normalized else None
            if timeout_button is not None:
                self._scene("reward_timeout")
                self._tap(*normalized[1].to_device(*timeout_button.center))
                for _ in range(6):
                    self._wait(2, reason="reward_timeout_transition", wait_s=12)
                    after = self._frame()
                    after_design = self._reward_design(after)
                    if after_design is None or reward_timeout_continue(after_design[0]) is not None:
                        continue
                    after_ui = self.engine.parser.ui.detect(after_design[0])
                    if (find_home_adventure_entry(after_design[0]) is not None
                            or self._recognized_after_home(after)
                            or after_ui in self.BATTLE_STATES | {UIState.BATTLE_END}):
                        pending_image = after
                        report("verified", "reward_timeout_transition", progress=True, **self._details)
                        break
                else:
                    self._snapshot(after, tag="reward_timeout_transition_unverified")
                    return
                continue
            revive = find_revive_button(normalized[0]) if normalized is not None else None
            if revive is not None:
                self._scene("revive")
                self._tap(*normalized[1].to_device(*revive.center))
                for _ in range(6):
                    self._wait(2, reason="revive_transition", wait_s=12)
                    after = self._frame()
                    after_design = self._reward_design(after)
                    if (after_design is not None
                            and find_revive_button(after_design[0]) is None
                            and find_resume_adventure_button(after_design[0]) is None
                            and self._recognized_after_home(after)):
                        pending_image = after
                        report("verified", "revive_transition", progress=True, **self._details)
                        break
                else:
                    self._snapshot(after, tag="revive_transition_unverified")
                    return
                continue
            if self._is_card_reward(image):
                self._scene("card_reward")
                if not self._handle_card_reward(image):
                    return
                self._awaiting_battle_reward = False
                continue
            post_battle_ui = None
            if self._awaiting_battle_reward:
                # 战斗结束后的地图背景不授权找节点，先核实奖励或结算页面。
                for attempt in range(7):
                    design = self._reward_design(image)
                    if design is not None and is_adventure_victory(design[0]):
                        self._complete_adventure(image)
                        return
                    post_battle_ui = self.engine.parser.ui.detect(
                        design[0] if design is not None else image
                    )
                    if post_battle_ui is UIState.BATTLE_END:
                        break
                    if self._is_hero_item_reward(image):
                        break
                    if self._is_card_reward(image):
                        pending_image = image
                        break
                    if attempt == 6:
                        self._snapshot(image, tag="battle_reward_missing")
                        return
                    self._wait(2, reason="battle_reward_pending", wait_s=12)
                    image = self._frame()
                if pending_image is not None:
                    continue
            if is_power_vendor(image):
                self._scene("astrologer")
                if not self._handle_astrologer(image):
                    return
                continue
            if shop_leave_button(image) is not None:
                self._scene("shop")
                if not self._handle_shop(image):
                    return
                continue
            if self._is_healer(image):
                self._scene("healer")
                if not self._handle_healer(image):
                    return
                continue
            if self._is_support(image):
                self._scene("support")
                if not self._handle_support(image):
                    return
                continue
            if self._is_hero_item_reward(image):
                self._scene("hero_item_reward")
                pending_image = self._handle_hero_item_reward(image)
                if pending_image is None:
                    return
                self._awaiting_battle_reward = False
                continue
            normalized = self._reward_design(image)
            design = normalized[0] if normalized is not None else image
            ui = post_battle_ui if post_battle_ui is not None else self.engine.parser.ui.detect(design)
            if ui in self.BATTLE_STATES:
                last_continue = None
                logger.info("adventure: 进入战斗，引擎接管")
                self._scene("battle")
                result = self.engine.run(max_ticks=self.coords.battle_max_ticks, close_device=False)
                if result.reason == "reward_timeout_transition":
                    continue
                if result.reason != "battle_end":
                    self.result = result
                    return result
                self._awaiting_battle_reward = True
                continue
            self._details.update(ui=ui.value)
            report("recognized", **self._details)
            if ui is UIState.BATTLE_END:
                self._awaiting_battle_reward = True
                self._scene("battle_end")
                if normalized is not None and result_screen(design) == "missions":
                    # 用户确认该任务结算页通过右下角继续；只点击一次。
                    self._tap(*normalized[1].to_device(1850, 1020))
                    for _ in range(6):
                        self._wait(2, reason="missions_transition", wait_s=12)
                        after = self._frame()
                        after_design = self._reward_design(after)
                        if after_design is not None and result_screen(after_design[0]) == "missions":
                            continue
                        if ((after_design is not None
                             and result_screen(after_design[0]) == "vault")
                                or self._recognized_after_home(after)):
                            pending_image = after
                            report("verified", "missions_transition", progress=True, **self._details)
                            break
                    else:
                        self._snapshot(after, tag="missions_transition_unverified")
                        return
                    continue
                button = find_continue_button(image)
                if button is None:
                    self._snapshot(
                        image, tag="continue_missing"
                    )
                    return
                x, y = button.center
                if last_continue is not None and (
                    abs(x - last_continue[0]) <= 40 and abs(y - last_continue[1]) <= 40
                ) and last_continue_view is not None and (
                    np.mean(cv2.absdiff(_continue_view(image), last_continue_view)) < 15
                ):
                    self._snapshot(
                        image, tag="continue_unchanged"
                    )
                    return
                plan = self.translator.translate(
                    Action(ActionType.CONTINUE), GameState(continue_button=button)
                )
                if plan is None:
                    self._snapshot(image, tag="continue_plan_missing")
                    return
                self._tap(*plan.points[0])
                last_continue = (x, y)
                last_continue_view = _continue_view(image)
                for _ in range(6):
                    self._wait(2, reason="continue_transition", wait_s=12)
                    after = self._frame()
                    after_design = self._reward_design(after)
                    after_ui = self.engine.parser.ui.detect(
                        after_design[0] if after_design is not None else after
                    )
                    changed_result = (
                        after_ui is UIState.BATTLE_END
                        and np.mean(cv2.absdiff(_continue_view(after), last_continue_view)) >= 15
                        and (find_continue_button(after) is not None
                             or (after_design is not None
                                 and result_screen(after_design[0]) == "missions"))
                    )
                    if changed_result or self._recognized_after_home(after):
                        pending_image = after
                        report("verified", "continue_transition", progress=True, **self._details)
                        break
                else:
                    self._snapshot(after, tag="continue_transition_unverified")
                    return
                continue
            last_continue = None
            if is_power_screen(image):
                pending_image = self._handle_power(image)
                if pending_image is None:
                    return
                continue
            if is_battle_detail(image):
                if not self._handle_node_panel(image):
                    return
                continue
            # 主页属于独立识别场景，不把战斗 UNKNOWN 当作点击授权。
            height, width = image.shape[:2]
            if width and height and abs(width / height - 16 / 9) <= 0.02:
                design_image, scale = self.normalizer.fit(image)
                resume = find_resume_adventure_button(design_image)
                if resume is not None:
                    selected = getattr(self.pack, "recognize_selected_hero", None)
                    if selected is None or not selected(design_image):
                        logger.warning("adventure: 无法确认所选英雄，停止")
                        self._snapshot(
                            image, tag="resume_hero_unknown"
                        )
                        return
                    self._tap(*scale.to_device(*resume.center))
                    for _ in range(6):
                        self._wait(2, reason="resume_transition", wait_s=12)
                        after = self._frame()
                        after_design = self._reward_design(after)
                        if is_map(after) or (after_design is not None
                                             and find_revive_button(after_design[0]) is not None):
                            pending_image = after
                            logger.info("adventure: 已继续冒险，进入可处理场景")
                            break
                    else:
                        self._snapshot(
                            after, tag="resume_transition_unverified",
                        )
                        return
                    continue
                weekly_entry = find_weekly_entry(design_image)
                if weekly_entry is not None:
                    self._scene("world_map")
                    self._tap(*scale.to_device(*weekly_entry.center))
                    for _ in range(6):
                        self._wait(2, reason="weekly_entry_transition", wait_s=12)
                        after = self._frame()
                        after_design = self._reward_design(after)
                        if (after_design is not None
                                and recognize_weekly_adventures(after_design[0]) is not None):
                            pending_image = after
                            report("verified", "weekly_entry_transition", progress=True,
                                   **self._details)
                            break
                    else:
                        self._snapshot(after, tag="weekly_entry_unverified")
                        return
                    continue
                weekly = recognize_weekly_adventures(design_image)
                if weekly is not None:
                    self._scene("weekly_list")
                    index = pick_lowest_weekly([candidate.stars for candidate in weekly])
                    if index is None:
                        self._snapshot(image, tag="weekly_stars_unknown")
                        return
                    selected_weekly_stars = weekly[index].stars
                    report("decided", "lowest_weekly_stars", stars=selected_weekly_stars,
                           candidates=[candidate.stars for candidate in weekly], **self._details)
                    self._tap(*scale.to_device(*weekly[index].target.center))
                    for _ in range(6):
                        self._wait(2, reason="weekly_selection_transition", wait_s=12)
                        after = self._frame()
                        after_design = self._reward_design(after)
                        if (after_design is not None
                                and weekly_detail_stars(after_design[0]) == selected_weekly_stars
                                and find_weekly_start(after_design[0]) is not None):
                            pending_image = after
                            report("verified", "weekly_selected", progress=True,
                                   stars=selected_weekly_stars, **self._details)
                            break
                    else:
                        self._snapshot(after, tag="weekly_selection_unverified")
                        return
                    continue
                detail_stars = weekly_detail_stars(design_image)
                if detail_stars is not None:
                    self._scene("weekly_detail")
                    if selected_weekly_stars is None:
                        self._snapshot(image, tag="weekly_detail_without_selection")
                        return
                    start = find_weekly_start(design_image)
                    if detail_stars != selected_weekly_stars or start is None:
                        self._snapshot(image, tag="weekly_selection_unverified")
                        return
                    self._tap(*scale.to_device(*start.center))
                    for _ in range(6):
                        self._wait(2, reason="weekly_start_transition", wait_s=12)
                        after = self._frame()
                        if is_map(after):
                            pending_image = after
                            selected_weekly_stars = None
                            report("verified", "weekly_started", progress=True, **self._details)
                            break
                    else:
                        self._snapshot(after, tag="weekly_start_unverified")
                        return
                    continue
                entry = find_home_adventure_entry(design_image)
                if entry is not None:
                    self._tap(*scale.to_device(*entry.center))
                    for _ in range(6):
                        self._wait(2, reason="home_entry_transition", wait_s=12)
                        after = self._frame()
                        if self._recognized_after_home(after):
                            pending_image = after
                            report("verified", "home_entry_transition", progress=True, **self._details)
                            break
                    else:
                        self._snapshot(after, tag="home_entry_after")
                        return
                    continue
            if not is_map(image):
                logger.warning("adventure: 未识别地图画面，停止（保存快照）")
                self._snapshot(image, tag="unknown_scene")
                return
            self._scene("map")
            nxt = self._find_next(image)
            if nxt is None:
                if is_completed_panel(image):
                    if self._close_panel(image):
                        continue
                    logger.warning("adventure: 面板打开但找不到空白点，停止")
                    self._snapshot(
                        image, tag="panel_no_empty_point"
                    )
                    return
                # 地图可能仍在转场动画中；只在重新识别到地图且没有面板时找节点。
                for _ in range(6):
                    self._wait(2, reason="map_next_node", wait_s=12)
                    image = self._frame()
                    if (self._is_card_reward(image) or self._is_hero_item_reward(image)
                            or self._is_support(image) or is_power_screen(image)):
                        pending_image = image
                        break
                    if is_map(image) and not is_completed_panel(image):
                        nxt = self._find_next(image)
                        if nxt is not None:
                            break
                if pending_image is not None:
                    continue
                if nxt is None:
                    logger.warning("adventure: 地图上找不到下一节点，停止（保存快照）")
                    self._snapshot(image, tag="map_no_next")
                    return
            if nxt.needs_reveal or nxt.y + max(nxt.radius, 80) >= image.shape[0] - 40:
                revealed = self._reveal_bottom_map_node(image, nxt)
                if revealed is None:
                    return
                image, nxt = revealed
            # mapnav 返回的是输入帧像素坐标；_find_next 已统一换算到设计尺寸。
            self._tap(nxt.x, nxt.y)
            self._wait(3)
            if not self._handle_node_panel():
                return

    def _complete_adventure(self, image) -> None:
        self._scene("adventure_victory")
        path = snapshot.save_snapshot(
            image, self.settings.perception.snapshot_dir, tag="adventure_victory",
        )
        self._details.update(snapshot=str(path), outcome="victory")
        self.result = LoopResult("completed", "adventure_victory")

    def _recognized_after_home(self, image) -> bool:
        """只在现有冒险处理器可识别场景时结束主页转场等待。"""
        normalized = self._reward_design(image)
        if normalized is not None and is_adventure_victory(normalized[0]):
            return True
        if (is_power_vendor(image) or shop_leave_button(image) is not None or self._is_healer(image)
                or self._is_support(image) or self._is_card_reward(image)
                or self._is_hero_item_reward(image)
                or is_power_screen(image) or is_battle_detail(image) or is_map(image)):
            return True
        height, width = image.shape[:2]
        if width and height and abs(width / height - 16 / 9) <= 0.02:
            design, _ = self.normalizer.fit(image)
            if (find_resume_adventure_button(design) is not None
                    or find_weekly_entry(design) is not None
                    or recognize_weekly_adventures(design) is not None
                    or weekly_detail_stars(design) is not None):
                return True
        # 主页转场中的动画可能触发战斗按钮探针；单独的战斗 UI 状态
        # 不能证明已进入冒险，应等待可识别的冒险页面。
        return False

    def _reveal_bottom_map_node(self, image, node):
        """底边目标先平移一次；新帧重新核实位置和路线后才允许点击。"""
        recognize_hero = getattr(self.pack, "recognize_map_hero", None)
        hero = recognize_hero(image) if recognize_hero is not None else None
        point = empty_point(image) if is_map(image) and not panel_open(image) else None
        if hero is None or point is None:
            self._snapshot(image, tag="map_pan_precondition_failed")
            return None
        distance = min(240, node.y - (image.shape[0] - 240), point[1] - 150)
        if distance < 80:
            self._snapshot(image, tag="map_pan_precondition_failed")
            return None
        checkpoint()
        report("execute", "map_pan", start=list(point),
               end=[point[0], point[1] - distance], **self._details)
        self.device.drag(*point, point[0], point[1] - distance, 150, 600)
        after = image
        for _ in range(6):
            self._wait(2, reason="map_pan_transition", wait_s=12)
            after = self._frame()
            if not is_map(after) or panel_open(after):
                continue
            moved = recognize_hero(after)
            if (moved is None or abs(moved[0] - hero[0]) > 75
                    or abs(moved[1] - (hero[1] - distance)) > 75):
                continue
            fresh = self._find_next(after)
            if (fresh is not None and not fresh.needs_reveal
                    and fresh.y + fresh.radius + 20 < after.shape[0]):
                report("verified", "map_pan_transition", progress=True, **self._details)
                return after, fresh
        self._snapshot(after, tag="map_pan_unverified")
        return None

    def _find_next(self, image):
        recognize_hero = getattr(self.pack, "recognize_map_hero", None)
        hero = recognize_hero(image) if recognize_hero is not None else None
        if recognize_hero is not None and hero is None:
            return None
        nodes = reachable_nodes(image, hero=hero, rng=self.rng)
        kinds = [node_kind(image, node) for node in nodes]
        index = pick_map_node(kinds, rng=self.rng)
        if index is None:
            return None
        record_event("map_node_selected", candidates=[
            {"x": node.x, "y": node.y, "kind": kind.value if kind else None}
            for node, kind in zip(nodes, kinds, strict=True)
        ], selection=index, kind=kinds[index].value if kinds[index] else None)
        return nodes[index]

    def _handle_power(self, image):
        normalized = self._reward_design(image)
        if normalized is None:
            self._snapshot(image, tag="power_choice")
            return None
        design, scale = normalized
        candidates = recognize_powers(design)
        selected = power_selection(design)
        if candidates is None or selected is None:
            self._snapshot(image, tag="power_choice")
            return None
        picked = pick_reward(candidates, self.pack.power_preferences)
        if picked is None:
            self._snapshot(image, tag="power_choice")
            return None
        index = candidates.index(picked.candidate)
        self._details.update(recommendation=picked.candidate.name or "未知能力",
                             recommendation_quality=picked.candidate.quality,
                             recommendation_reason=picked.reason, selection=index)
        report("decided", "power_choice", **self._details)
        if selected == -1:
            if not power_unselected(design):
                self._snapshot(image, tag="power_choice")
                return None
            self._tap(*scale.to_device((617, 960, 1303)[index], 430))
            self._wait(2, reason="power_selection", wait_s=2)
            image = self._frame()
            normalized = self._reward_design(image)
            if normalized is None:
                self._snapshot(image, tag="power_selected_unverified")
                return None
            design, scale = normalized
        if (recognize_powers(design) != candidates or power_selection(design) != index
                or not power_choose_enabled(design)):
            self._snapshot(image, tag="power_selected_unverified")
            return None
        self._tap(*scale.to_device(960, 1003))
        for _ in range(6):
            self._wait(2, reason="power_transition", wait_s=12)
            after = self._frame()
            if not is_power_screen(after) and self._recognized_after_home(after):
                report("verified", "power_transition", progress=True, **self._details)
                return after
        self._snapshot(after, tag="power_transition_unverified")
        return None

    def _reward_design(self, image):
        height, width = image.shape[:2]
        if not width or not height or abs(width / height - 16 / 9) > 0.02:
            return None
        if (self.settings.screen.width, self.settings.screen.height) != (1920, 1080):
            return None
        return self.normalizer.fit(image)

    def _handle_hero_item_reward(self, image):
        normalized = self._reward_design(image)
        if normalized is None:
            self._snapshot(image, tag="hero_item_selection_unverified")
            return
        design, scale = normalized
        heroes = recognize_hero_item_cards(design)
        selected = hero_item_hero_selection(design)
        items = recognize_hero_items(design)
        item_index = hero_item_item_selection(design)
        main = self.pack.name
        if (heroes is None or main not in heroes or selected is None or items is None
                or item_index is None
                or (selected == -1 and not hero_item_choose_disabled(design))
                or (item_index == -1 and not hero_item_choose_disabled(design))):
            self._snapshot(image, tag="hero_item_selection_unverified")
            return
        hero_index = heroes.index(main)
        if selected == -1:
            self._tap(*scale.to_device((780, 1125)[hero_index], 430))
            self._wait(2, reason="hero_item_hero_selection", wait_s=2)
            image = self._frame()
            normalized = self._reward_design(image)
            if normalized is None:
                self._snapshot(image, tag="hero_item_hero_unverified")
                return
            design, scale = normalized
            if (recognize_hero_item_cards(design) != heroes
                    or hero_item_hero_selection(design) != hero_index
                    or recognize_hero_items(design) != items
                    or hero_item_item_selection(design) != item_index
                    or (item_index == -1 and not hero_item_choose_disabled(design))
                    or (item_index != -1 and not hero_item_choose_enabled(design))):
                self._snapshot(image, tag="hero_item_hero_unverified")
                return
        elif selected != hero_index:
            self._snapshot(image, tag="hero_item_wrong_hero")
            return
        if item_index == -1:
            pick = pick_hero_item_reward(items, getattr(self.pack, "item_preferences", ()), self.rng)
            if pick is None:
                self._snapshot(image, tag="hero_item_choice_unverified")
                return None
            item_index = items.index(pick.candidate)
            report("decided", "hero_item_choice", selection=item_index, item=pick.candidate.name,
                   selection_reason=pick.reason)
            self._tap(*scale.to_device((615, 960, 1300)[item_index], 750))
            self._wait(2, reason="hero_item_selection", wait_s=2)
            image = self._frame()
            normalized = self._reward_design(image)
            if normalized is None:
                self._snapshot(image, tag="hero_item_selected_unverified")
                return None
            design, scale = normalized
        if (recognize_hero_item_cards(design) != heroes
                or hero_item_hero_selection(design) != hero_index
                or recognize_hero_items(design) != items
                or hero_item_item_selection(design) != item_index
                or not hero_item_choose_enabled(design)):
            self._snapshot(image, tag="hero_item_selected_unverified")
            return None
        self._tap(*scale.to_device(960, 1003))
        for _ in range(6):
            self._wait(2, reason="hero_item_transition", wait_s=12)
            after = self._frame()
            if not self._is_hero_item_reward(after) and self._recognized_after_home(after):
                report("verified", "hero_item_transition", progress=True, **self._details)
                return after
        self._snapshot(after, tag="hero_item_transition_unverified")
        return None

    def _is_hero_item_reward(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_hero_item_reward_screen(normalized[0])

    def _is_card_reward(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_card_reward_screen(normalized[0])

    def _is_support(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_support_screen(normalized[0])

    def _is_healer(self, image) -> bool:
        normalized = self._reward_design(image)
        return normalized is not None and is_healer_screen(normalized[0])

    def _leave_astrologer(self, image) -> bool:
        button = astrologer_leave_button(image)
        if button is None:
            self._snapshot(image, tag="astrologer_leave_missing")
            return False
        self._tap(*button.center)
        for _ in range(6):
            self._wait(2, reason="astrologer_leave", wait_s=12)
            after = self._frame()
            if is_map(after) and not panel_open(after):
                report("verified", "astrologer_map_transition", progress=True)
                return True
        self._snapshot(after, tag="astrologer_leave_unverified")
        return False

    def _handle_astrologer(self, image) -> bool:
        offers = astrologer_offers(image)
        gold = astrologer_gold(image)
        selection = astrologer_selection(image)
        if offers is None or gold is None or selection is None:
            self._snapshot(image, tag="astrologer_unknown")
            return False
        index = pick_affordable_power(offers, gold)
        if index is None:
            return self._leave_astrologer(image)
        if selection == -1:
            self._tap(ASTROLOGER_SLOTS[index] + 135, 350)
            self._wait(2, reason="astrologer_select", wait_s=12)
            selected = self._frame()
        else:
            selected = image
        if (astrologer_selection(selected) != index or astrologer_gold(selected) != gold
                or not same_astrologer_offers(image, selected)):
            self._snapshot(selected, tag="astrologer_selection_unverified")
            return False
        button = astrologer_buy_button(selected)
        if button is None:
            self._snapshot(selected, tag="astrologer_buy_missing")
            return False
        report("verified", "astrologer_selected", progress=True, selection=index,
               recommendation_quality=offers[index].quality, price=offers[index].cost, gold=gold)
        self._tap(*button.center)
        # 购买只发送一次；以本帧金币的精确扣减核验，不根据按钮点击猜到账。
        expected_gold = gold - offers[index].cost
        for _ in range(6):
            self._wait(2, reason="astrologer_purchase", wait_s=12)
            after = self._frame()
            map_gold = astrologer_map_gold(after)
            if astrologer_gold(after) == expected_gold or map_gold == expected_gold:
                report("verified", "astrologer_currency_paid", progress=True,
                       selection=index, price=offers[index].cost, gold=expected_gold,
                       reward_credited_verified=False)
                if map_gold == expected_gold:
                    report("verified", "astrologer_map_transition", progress=True)
                    return True
                return self._leave_astrologer(after)
        self._snapshot(after, tag="astrologer_purchase_unverified")
        return False

    def _handle_shop(self, image) -> bool:
        """按当前通用规则离开商店，核实返回地图后继续。"""
        button = shop_leave_button(image)
        if button is None:
            self._snapshot(image, tag="shop_leave_missing")
            return False
        self._tap(*button.center)
        for _ in range(6):
            self._wait(2, reason="shop_leave_transition", wait_s=12)
            after = self._frame()
            if is_map(after) and not panel_open(after):
                report("verified", "shop_map_transition", progress=True)
                logger.info("adventure: 已离开商店，继续寻找下一节点")
                return True
        self._snapshot(after, tag="shop_leave_unverified")
        return False

    def _handle_healer(self, image) -> bool:
        """点一次免费治疗，确认回到地图且节点完成后继续冒险。"""
        normalized = self._reward_design(image)
        button = healer_heal_button(normalized[0]) if normalized is not None else None
        if normalized is None or button is None:
            logger.warning("adventure: 治疗师选项或按钮无法确认，停止")
            self._snapshot(
                image, tag="healer_unknown"
            )
            return False
        _, scale = normalized
        self._tap(*scale.to_device(*button.center))
        logger.info("adventure: 已点击治疗，等待核对结果")
        self._wait(3)
        after = self._frame()
        if self._is_healer(after):
            logger.warning("adventure: 治疗后仍在治疗师页面，停止")
            tag = "healer_unchanged"
        elif is_map(after) and not panel_open(after):
            recognize_hero = getattr(self.pack, "recognize_map_hero", None)
            hero = recognize_hero(after) if recognize_hero is not None else None
            if hero is not None and _current_completed_node_visible(after, hero):
                logger.info("adventure: 治疗节点已完成，继续冒险")
                self._snapshot(
                    after, tag="healer_completed"
                )
                return True
            logger.warning("adventure: 治疗后回到地图，但无法确认节点完成")
            tag = "healer_map_unverified"
        else:
            logger.warning("adventure: 治疗后状态无法确认，停止")
            tag = "healer_after_unknown"
        self._snapshot(after, tag=tag)
        return False

    def _handle_support(self, image) -> bool:
        """选择援军，核验唯一选中、确认与返回地图后继续。"""
        normalized = self._reward_design(image)
        if normalized is None:
            self._snapshot(image, tag="support_unknown")
            return False
        design, scale = normalized
        choices = recognize_support_choices(design)
        if choices is None:
            self._snapshot(
                image, tag="support_unknown"
            )
            return False
        index = pick_support_group([choice.group for choice in choices])
        if index is None:
            logger.warning("adventure: 辅助英雄费用不足以排序，停止")
            self._snapshot(
                image, tag="support_undecided"
            )
            return False
        logger.info("adventure: 选择第 {} 组辅助英雄（英雄 {} 费）", index + 1,
                    choices[index].group.hero_cost)
        report("decided", "support_choice", selection=index, hero_cost=choices[index].group.hero_cost)
        self._tap(*scale.to_device(*choices[index].target.center))
        self._wait(3)
        selected_image = self._frame()
        selected = self._reward_design(selected_image)
        if (selected is None or support_selection(selected[0]) != index
                or not same_support_choices(design, selected[0], index)):
            self._snapshot(
                selected_image, tag="support_selection_failed"
            )
            return False
        report("verified", "support_selected", progress=True, selection=index)
        button = support_confirm_button(selected[0])
        if button is None:
            self._snapshot(
                selected_image, tag="support_confirm_missing"
            )
            return False
        self._tap(*selected[1].to_device(*button.center))
        for _ in range(6):
            self._wait(2, reason="support_transition", wait_s=12)
            next_image = self._frame()
            next_design = self._reward_design(next_image)
            if next_design is None or is_support_screen(next_design[0]):
                continue
            if is_map(next_design[0]):
                report("verified", "support_transition", progress=True, selection=index,
                       reward_credited_verified=False)
                return True
        tag = ("support_confirm_unchanged" if next_design is not None
               and is_support_screen(next_design[0]) else "support_after_unknown")
        self._snapshot(next_image, tag=tag)
        return False

    def _handle_card_reward(self, image) -> bool:
        """核验选中、确认和后继界面后继续；转场不等于证明服务端到账。"""
        normalized = self._reward_design(image)
        if normalized is None:
            self._snapshot(image, tag="card_reward_unknown")
            return False
        design, scale = normalized
        candidates = recognize_card_rewards(design)
        if candidates is None:
            logger.warning("adventure: 卡牌奖励信息不完整或已选中，停止")
            self._snapshot(image, tag="card_reward_unknown")
            return False
        champion_pick = getattr(self.pack, "pick_card_reward", None)
        picked = champion_pick(candidates) if champion_pick is not None else pick_card_reward(
            candidates, getattr(self.pack, "card_preferences", ()),
            getattr(self.pack, "item_preferences", ()),
        )
        if picked is None:
            logger.warning("adventure: 卡牌奖励无法安全排序，停止")
            self._snapshot(image, tag="card_reward_undecided")
            return False
        index = candidates.index(picked.candidate)
        name = picked.candidate.card.name or "未知卡牌"
        record_event("reward_decision", kind="card_reward", selection=index, reason=picked.reason,
                     candidates=[{"slot": slot, "name": candidate.card.name,
                                  "preview_cost": candidate.card.cost,
                                  "quality": candidate.card.quality}
                                 for slot, candidate in enumerate(candidates)])
        report("decided", "card_reward_choice", selection=index,
               recommendation=name, recommendation_reason=picked.reason,
               preview_cost=picked.candidate.card.cost,
               recommendation_quality=picked.candidate.card.quality)
        logger.info("adventure: 选择奖励 {}（{}）", name, picked.reason)
        target = card_reward_target(design, index, picked.candidate.card.name)
        if target is None:
            self._snapshot(
                image, tag="card_reward_target_obscured"
            )
            return False
        self._tap(*scale.to_device(*target.center))
        self._wait(3)
        selected_image = self._frame()
        selected = self._reward_design(selected_image)
        if (selected is None or card_reward_selection(selected[0]) != index
                or not same_card_reward_choices(design, selected[0], index)):
            self._snapshot(
                selected_image, tag="card_reward_selection_failed"
            )
            return False
        report("verified", "card_reward_selected", progress=True, selection=index)
        button = card_reward_confirm_button(selected[0])
        if button is None:
            self._snapshot(
                selected_image, tag="card_reward_confirm_missing"
            )
            return False
        self._tap(*selected[1].to_device(*button.center))
        for _ in range(6):
            self._wait(2, reason="card_reward_transition", wait_s=12)
            next_image = self._frame()
            next_design = self._reward_design(next_image)
            if next_design is None or is_card_reward_screen(next_design[0]):
                continue
            if is_map(next_design[0]) or is_power_screen(next_design[0]):
                # 核验的是奖励交互结束，不能将它记作服务端到账证明。
                report("verified", "card_reward_transition", progress=True, selection=index,
                       reward_credited_verified=False)
                return True
        tag = ("card_reward_confirm_unchanged" if next_design is not None
               and is_card_reward_screen(next_design[0]) else "card_reward_after_unknown")
        self._snapshot(next_image, tag=tag)
        return False

    def _close_panel(self, image) -> bool:
        # 动态找“非节点”的空白区域，不固定某个坐标。
        point = empty_point(image)
        if point is None:
            return False
        for _ in range(2):
            self._tap(*point)
            logger.info("adventure: 点击空白处关闭面板 ({}, {})", *point)
            self._wait(4)
            image = self._frame()
            if is_map(image) and not panel_open(image):
                return True
            if not is_completed_panel(image):
                return False
        return False

    def _handle_node_panel(self, image=None) -> bool:
        """节点面板：点金色「旅行」→「戰鬥」；找不到按钮就停下存快照。"""
        if image is None:
            image = self._frame()
        if is_power_vendor(image):
            return self._handle_astrologer(image)
        if shop_leave_button(image) is not None:
            return self._handle_shop(image)
        if self._is_healer(image):
            return self._handle_healer(image)
        if self._is_support(image):
            return self._handle_support(image)
        if self._is_card_reward(image):
            return self._handle_card_reward(image)
        ui = self.engine.parser.ui.detect(image)
        if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
            return True  # 有些节点直接进战斗
        if is_power_screen(image):
            return self._handle_power(image) is not None
        if not is_map(image) and not is_battle_detail(image):
            logger.warning("adventure: 未识别节点面板，停止（保存快照）")
            self._snapshot(image, tag="panel_unknown")
            return False
        # 点了节点但还在地图：说明这次点击没打开面板（坐标/动画/网络问题）。
        # 此时不能再盲点「旅行」，否则会把地图上的空白当成按钮。
        if is_map(image) and self._find_next(image) is not None:
            logger.warning("adventure: 节点点击后仍在地图，停止盲点（保存快照）")
            self._snapshot(
                image, tag="map_panel_not_open"
            )
            return False
        # 每个阶段只点一次；下一帧必须进入下一阶段，不能重复点同一按钮。
        last_action = None
        for _ in range(2):
            button = action_button(image)
            if button is not None and last_action is None and is_map(image) and button_is(
                image, button, "travel"
            ):
                action = "travel"
            elif (button is not None and last_action != "battle" and is_battle_detail(image)
                  and button_is(image, button, "battle")):
                action = "battle"
            else:
                break
            self._scene("node_" + action)
            self._tap(*button.center)
            last_action = action
            logger.info("adventure: 面板按钮 ({}, {})", *button.center)
            self._wait(4, reason="node_transition", wait_s=24)
            # 旅行或战斗可能先出现载入画面。只等待新帧，绝不重复点击；
            # 看到可识别的场景再交给对应处理，超时仍未知则停止。
            for attempt in range(11):
                image = self._frame()
                if is_power_vendor(image):
                    return self._handle_astrologer(image)
                if shop_leave_button(image) is not None:
                    return self._handle_shop(image)
                if self._is_healer(image):
                    return self._handle_healer(image)
                if self._is_support(image):
                    return self._handle_support(image)
                if self._is_card_reward(image):
                    return self._handle_card_reward(image)
                ui = self.engine.parser.ui.detect(image)
                if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
                    return True
                if is_power_screen(image):
                    return self._handle_power(image) is not None
                if is_map(image) or is_battle_detail(image):
                    break
                if attempt < 10:
                    self._wait(2, reason="node_transition", wait_s=24)
            else:
                logger.warning("adventure: 节点转场后画面仍无法识别，停止")
                self._snapshot(
                    image, tag="panel_transition_timeout"
                )
                return False
        # 旅行后回到地图：说明这个节点只是移动，继续下一轮找节点。
        if last_action == "travel" and is_map(image) and self._find_next(image) is not None:
            return True
        # 没有金色按钮（能力三选一／商店／信息面板）：不盲点，存快照停下。
        logger.warning("adventure: 面板未进入预期的下一阶段，停止（保存快照）")
        self._snapshot(
            image, tag="panel_no_action_button" if last_action else "panel_unknown",
        )
        return False

    def _scene(self, scene: str) -> None:
        changed = scene != self._last_scene
        if changed:
            record_event("adventure_scene", scene=scene)
        self._details.update(scene=scene)
        report("adventure", progress=changed, **self._details)
        self._last_scene = scene

    def _snapshot(self, image, out_dir=None, *, tag: str):
        path = snapshot.save_snapshot(
            image, out_dir or self.settings.perception.snapshot_dir, tag=tag,
        )
        if tag == "healer_completed":
            report("verified", tag, progress=True, snapshot=str(path))
        else:
            self.result = LoopResult("stopped", tag)
            self._details.update(snapshot=str(path))
            if tag == "battle_reward_missing" or tag.startswith("card_reward_"):
                normalized = self._reward_design(image)
                evidence = card_reward_diagnostics(normalized[0] if normalized is not None else image)
                self._details["recognition_diagnostic"] = evidence
                record_event("perception_diagnostic", reason=tag, expected_scene="card_reward",
                             snapshot=str(path), **evidence)
            report("stopped", tag, **self._details)
        return path

    def _tap(self, *point) -> None:
        checkpoint()
        report("execute", "adventure_tap", target=list(point), **self._details)
        self.device.tap(*point)

    def _wait(
        self, seconds: float, *, reason: str = "adventure_transition", wait_s: float | None = None,
    ) -> None:
        # 轮询沿用整个转场的观察期限，不能把每次 sleep 当成新的进展。
        report("waiting", reason, wait_s=seconds + 5 if wait_s is None else wait_s,
               **self._details)
        Engine._wait(seconds)

    def _frame(self):
        checkpoint()
        report("capture", **self._details)
        started = time.time()
        frame = self.device.screencap()
        report("recognize", capture_ms=round((time.time() - started) * 1000), **self._details)
        return frame.image
