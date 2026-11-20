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
from lorwright.core.device.base import Device, Frame
from lorwright.core.loop.engine import Engine
from lorwright.core.loop.outcome import LoopResult
from lorwright.core.loop.reconnect import ReconnectTimeout
from lorwright.core.models import Action, ActionType, GameState, UIState
from lorwright.core.perceive.adventure_scene import (
    button_is,
    can_resume_adventure,
    completed_weekly_targets,
    find_home_adventure_entry,
    find_resume_adventure_button,
    find_weekly_entry,
    find_weekly_start,
    gold_chest_collect_button,
    is_battle_detail,
    is_completed_panel,
    is_loading_screen,
    is_map,
    is_weekly_list,
    item_chest_leave_button,
    recognize_weekly_adventures,
    reward_timeout_continue,
    selected_world_hero_matches,
    service_error_confirm,
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
    HeroToken,
    _current_completed_node_visible,
    current_unfinished_node,
    empty_point,
    locate_map_hero,
    node_kind,
    occluded_route_zoom_button,
    panel_open,
    reachable_nodes,
)
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.perceive.panels import action_button
from lorwright.core.perceive.result_screen import (
    adventure_settlement,
    is_task_reward,
    result_screen,
)
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
    hero_item_main_index,
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
    same_hero_item_cards,
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


class _AdventureInputExpired(Exception):
    """准备好的输入所依赖的画面已经过期。"""


class AdventureLoop:
    SERVICE_ERROR_LIMIT = 3
    LOADING_EXTENSION_S = 90
    SETTLEMENT_ANIMATION_S = 30
    SETTLEMENT_STAGES = (
        "victory", "rewards", "silver_vault", "silver_vault_reward", "relic_chest", "relic_reward",
    )
    BATTLE_STATES = {
        UIState.MULLIGAN,
        UIState.MY_TURN_IDLE,
        UIState.BLOCKING,
        UIState.TARGETING,
        UIState.OPTIONAL_CHOICE,
        UIState.DISCARD,
        UIState.COMBAT_RESOLVING,
        UIState.ENEMY_TURN,
    }

    def __init__(self, settings, engine, device: Device, *, pack,
                 sample_hero_item_jinx: bool = False, weekly_replay_slot: int | None = None,
                 capture_frame=None) -> None:
        self.settings = settings
        self.engine = engine
        self.device = device
        self.capture_frame = capture_frame or (lambda: self.device.screencap())
        self.pack = pack
        self.sample_hero_item_jinx = sample_hero_item_jinx
        self.weekly_replay_slot = weekly_replay_slot
        self.coords = settings.adventure.to_coords()
        self.translator = ActionTranslator(settings.layout.to_layout())
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self.rng = random.Random()
        self.result = LoopResult("stopped", "iteration_limit")
        self._last_scene = None
        self._details: dict = {}
        self._awaiting_battle_reward = False
        self._latest_frame: Frame | None = None
        self._late_transition_capture = False
        self._service_errors = 0

    def run(self, max_nodes: int = 30) -> LoopResult:
        """max_nodes 是冒险循环迭代预算，不是已完成节点数。"""
        self.result = LoopResult("stopped", "iteration_limit")
        self._details = dict(iteration=0, iteration_limit=max_nodes)
        try:
            battle_result = self._run(max_nodes)
        except _AdventureInputExpired:
            assert self._latest_frame is not None
            self._snapshot(self._latest_frame.image, tag="adventure_input_frame_expired")
            return self.result
        except ReconnectTimeout:
            raise
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
        replay_slot = self.weekly_replay_slot
        if replay_slot is not None:
            self._details["weekly_replay_slot"] = replay_slot
        route_zoom_used = False
        reentry_used = False
        for iteration in range(1, max_nodes + 1):
            self._details.update(iteration=iteration)
            report("adventure", **self._details)
            image = pending_image if pending_image is not None else self._frame()
            pending_image = None
            normalized = self._reward_design(image)
            if normalized is not None and adventure_settlement(normalized[0]) is not None:
                self._complete_adventure(image)
                return
            if normalized is not None and is_task_reward(normalized[0]):
                self._scene("task_reward")
                pending_image = self._handle_task_reward(image)
                if pending_image is None:
                    return
                continue
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
                pending_image = self._handle_reward_timeout(image, normalized, timeout_button)
                if pending_image is None:
                    return
                continue
            service_error = service_error_confirm(normalized[0]) if normalized else None
            if service_error is not None:
                pending_image = self._handle_service_error(image, normalized, service_error)
                if pending_image is None:
                    return
                continue
            revive = find_revive_button(normalized[0]) if normalized is not None else None
            if revive is not None:
                pending_image = self._handle_revive(image, normalized, revive)
                if pending_image is None:
                    return
                self._awaiting_battle_reward = False
                continue
            if self._is_card_reward(image):
                self._scene("card_reward")
                pending_image = self._handle_card_reward(image)
                if pending_image is None:
                    return
                self._awaiting_battle_reward = False
                continue
            post_battle_ui = None
            if self._awaiting_battle_reward:
                # 战斗结束后的地图背景不授权找节点，先核实奖励或结算页面。
                for reward_image in self._transition_frames("battle_reward_pending", initial=image):
                    image = reward_image
                    design = self._reward_design(image)
                    if design is not None and adventure_settlement(design[0]) is not None:
                        self._complete_adventure(image)
                        return
                    if design is not None and (
                        is_task_reward(design[0])
                        or service_error_confirm(design[0]) is not None
                        or reward_timeout_continue(design[0]) is not None
                        or find_revive_button(design[0]) is not None
                    ):
                        pending_image = image
                        break
                    post_battle_ui = self.engine.parser.ui.detect(
                        design[0] if design is not None else image
                    )
                    if post_battle_ui is UIState.BATTLE_END:
                        break
                    if (self._is_hero_item_reward(image)
                            or is_power_screen(image)
                            or self._is_support(image)):
                        break
                    if self._is_card_reward(image):
                        pending_image = image
                        break
                else:
                    self._snapshot(image, tag="battle_reward_missing")
                    return
                if pending_image is not None:
                    continue
            if is_power_vendor(image):
                self._scene("astrologer")
                if not self._handle_astrologer(image):
                    return
                continue
            if gold_chest_collect_button(image) is not None:
                if not self._collect_gold_chest(image):
                    return
                continue
            if item_chest_leave_button(image) is not None:
                self._scene("item_chest")
                if not self._leave_item_chest(image):
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
                self._awaiting_battle_reward = False
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
                route_zoom_used = False
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
                    pending_image = self._handle_missions_result(image, normalized)
                    if pending_image is None:
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
                after = image
                for after in self._transition_frames("continue_transition"):
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
                self._awaiting_battle_reward = False
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
                    pending_image = self._handle_resume_adventure(
                        image, design_image, scale, resume, replay_slot,
                    )
                    if pending_image is None:
                        return
                    continue
                weekly_entry = find_weekly_entry(design_image)
                if weekly_entry is not None:
                    pending_image = self._handle_weekly_entry(image, scale, weekly_entry)
                    if pending_image is None:
                        return
                    continue
                target = None
                expected_stars = None
                if replay_slot is not None:
                    completed = completed_weekly_targets(design_image)
                    if completed is not None:
                        target = completed[replay_slot - 1]
                        report("decided", "weekly_replay_target", **self._details)
                else:
                    weekly = recognize_weekly_adventures(design_image)
                    if weekly is not None:
                        stars = [candidate.stars for candidate in weekly]
                        index = pick_lowest_weekly(stars, rng=self.rng)
                        if index is None:
                            self._snapshot(image, tag="weekly_stars_unknown")
                            return
                        target, expected_stars = weekly[index].target, weekly[index].stars
                        report("decided", "lowest_weekly_stars", stars=expected_stars,
                               candidates=stars, **self._details)
                if target is not None:
                    self._scene("weekly_list")
                    self._tap(*scale.to_device(*target.center))
                    after = image
                    for after in self._transition_frames("weekly_selection_transition"):
                        after_design = self._reward_design(after)
                        if after_design is None:
                            continue
                        stars = weekly_detail_stars(after_design[0])
                        if (stars is not None
                                and (replay_slot is not None or stars == expected_stars)
                                and find_weekly_start(after_design[0], replay=replay_slot is not None)
                                is not None):
                            selected_weekly_stars = stars
                            pending_image = after
                            report("verified", "weekly_selected", progress=True,
                                   stars=stars, **self._details)
                            break
                    else:
                        self._snapshot(after, tag="weekly_selection_unverified")
                        return
                    continue
                if is_weekly_list(design_image):
                    self._scene("weekly_list")
                    reason = ("weekly_replay_list_unverified" if replay_slot is not None
                              else "weekly_already_completed")
                    self._snapshot(image, tag=reason)
                    return
                detail_stars = weekly_detail_stars(design_image)
                if detail_stars is not None:
                    self._scene("weekly_detail")
                    if selected_weekly_stars is None:
                        self._snapshot(image, tag="weekly_detail_without_selection")
                        return
                    start = find_weekly_start(design_image, replay=replay_slot is not None)
                    if detail_stars != selected_weekly_stars or start is None:
                        self._snapshot(image, tag="weekly_selection_unverified")
                        return
                    if replay_slot is not None and not selected_world_hero_matches(design_image, self.pack):
                        self._snapshot(image, tag="weekly_replay_hero_unknown")
                        return
                    self._tap(*scale.to_device(*start.center))
                    pending_image = self._await_transition(
                        "weekly_start_transition",
                        is_map,
                        initial_image=image,
                        unverified_tag="weekly_start_unverified",
                        verified_reason="weekly_started",
                    )
                    if pending_image is None:
                        return
                    selected_weekly_stars = None
                    replay_slot = None
                    continue
                entry = find_home_adventure_entry(design_image)
                if entry is not None:
                    pending_image = self._handle_home_entry(image, scale, entry)
                    if pending_image is None:
                        return
                    continue
            if (is_battle_detail(image) or (is_map(image) and panel_open(image)
                                          and not is_completed_panel(image))):
                self._scene("node_panel")
                if not self._handle_node_panel(image):
                    return
                route_zoom_used = False
                continue
            if not is_map(image):
                logger.warning("adventure: 未识别地图画面，停止（保存快照）")
                self._snapshot(image, tag="unknown_scene")
                return
            self._scene("map")
            reentering = False
            hero = locate_map_hero(image)
            nxt = self._find_next(image, hero)
            if nxt is None and not route_zoom_used:
                zoom = occluded_route_zoom_button(image, hero)
                if zoom is not None:
                    route_zoom_used = True
                    revealed = self._reveal_occluded_map_route(image, zoom)
                    if revealed is None:
                        return
                    image, hero, nxt = revealed
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
                for image in self._transition_frames("map_next_node"):
                    if (self._is_card_reward(image) or self._is_hero_item_reward(image)
                            or self._is_support(image) or is_power_screen(image)):
                        pending_image = image
                        break
                    if is_map(image) and not is_completed_panel(image):
                        hero = locate_map_hero(image)
                        nxt = self._find_next(image, hero)
                        if nxt is not None:
                            break
                        if not route_zoom_used:
                            zoom = occluded_route_zoom_button(image, hero)
                            if zoom is not None:
                                route_zoom_used = True
                                revealed = self._reveal_occluded_map_route(image, zoom)
                                if revealed is None:
                                    return
                                image, hero, nxt = revealed
                                break
                if pending_image is not None:
                    continue
                if nxt is None and not reentry_used:
                    nxt = self._current_reentry(image)
                    reentering = nxt is not None
                if nxt is None:
                    logger.warning("adventure: 地图上找不到下一节点，停止（保存快照）")
                    self._snapshot(image, tag="map_no_next")
                    return
            if nxt.needs_reveal or nxt.y + max(nxt.radius, 80) >= image.shape[0] - 40:
                revealed = self._reveal_bottom_map_node(image, nxt, hero)
                if revealed is None:
                    return
                image, nxt = revealed
            # mapnav 返回的是输入帧像素坐标；_find_next 已统一换算到设计尺寸。
            self._tap(nxt.x, nxt.y)
            self._wait(3)
            if not self._handle_node_panel():
                return
            route_zoom_used = False
            # 重进后仍无可走后继就停止；正常走到下一节点后才再次允许。
            reentry_used = reentering

    def _handle_reward_timeout(self, image, normalized, timeout_button):
        self._scene("reward_timeout")
        self._tap(*normalized[1].to_device(*timeout_button.center))

        def _accepted(after) -> bool:
            after_design = self._reward_design(after)
            if after_design is None or reward_timeout_continue(after_design[0]) is not None:
                return False
            after_ui = self.engine.parser.ui.detect(after_design[0])
            return (
                find_home_adventure_entry(after_design[0]) is not None
                or self._recognized_after_home(after)
                or after_ui in self.BATTLE_STATES | {UIState.BATTLE_END}
            )

        return self._await_transition(
            "reward_timeout_transition",
            _accepted,
            initial_image=image,
            unverified_tag="reward_timeout_transition_unverified",
            verified_reason="reward_timeout_transition",
        )

    def _handle_service_error(self, image, normalized, button):
        self._scene("service_error")
        if self._service_errors >= self.SERVICE_ERROR_LIMIT:
            self._snapshot(image, tag="service_error_repeated")
            return None
        self._service_errors += 1
        self._details.update(service_errors=self._service_errors)
        self._tap(*normalized[1].to_device(*button.center))

        def _accepted(after) -> bool:
            after_design = self._reward_design(after)
            if after_design is None or service_error_confirm(after_design[0]) is not None:
                return False
            after_ui = self.engine.parser.ui.detect(after_design[0])
            return (
                find_home_adventure_entry(after_design[0]) is not None
                or self._recognized_after_home(after)
                or after_ui in self.BATTLE_STATES | {UIState.BATTLE_END}
            )

        return self._await_transition(
            "service_error_transition",
            _accepted,
            initial_image=image,
            unverified_tag="service_error_transition_unverified",
            verified_reason="service_error_dismissed",
            wait_s=20,
            attempts=8,
        )

    def _handle_revive(self, image, normalized, revive):
        self._scene("revive")
        self._tap(*normalized[1].to_device(*revive.center))

        def _accepted(after) -> bool:
            after_design = self._reward_design(after)
            return (
                after_design is not None
                and find_revive_button(after_design[0]) is None
                and find_resume_adventure_button(after_design[0]) is None
                and self._recognized_after_home(after)
            )

        return self._await_transition(
            "revive_transition",
            _accepted,
            initial_image=image,
            unverified_tag="revive_transition_unverified",
            verified_reason="revive_transition",
        )

    def _handle_missions_result(self, image, normalized):
        # 用户确认该任务结算页通过右下角继续；只点击一次。
        self._tap(*normalized[1].to_device(1850, 1020))

        def _accepted(after) -> bool:
            after_design = self._reward_design(after)
            if after_design is not None and result_screen(after_design[0]) == "missions":
                return False
            return (
                (after_design is not None and result_screen(after_design[0]) == "vault")
                or self._recognized_after_home(after)
            )

        return self._await_transition(
            "missions_transition",
            _accepted,
            initial_image=image,
            unverified_tag="missions_transition_unverified",
            verified_reason="missions_transition",
        )

    def _handle_resume_adventure(self, image, design_image, scale, resume, replay_slot):
        if replay_slot is not None:
            self._snapshot(image, tag="weekly_replay_active_adventure")
            return None
        if not can_resume_adventure(design_image, self.pack):
            logger.warning("adventure: 无法确认所选英雄，停止")
            self._snapshot(image, tag="resume_hero_unknown")
            return None
        self._tap(*scale.to_device(*resume.center))

        def _accepted(after) -> bool:
            after_design = self._reward_design(after)
            return is_map(after) or (
                after_design is not None and find_revive_button(after_design[0]) is not None
            )

        next_image = self._await_transition(
            "resume_transition",
            _accepted,
            initial_image=image,
            unverified_tag="resume_transition_unverified",
        )
        if next_image is not None:
            logger.info("adventure: 已继续冒险，进入可处理场景")
        return next_image

    def _handle_weekly_entry(self, image, scale, weekly_entry):
        self._scene("world_map")
        self._tap(*scale.to_device(*weekly_entry.center))

        def _accepted(after) -> bool:
            after_design = self._reward_design(after)
            return after_design is not None and is_weekly_list(after_design[0])

        return self._await_transition(
            "weekly_entry_transition",
            _accepted,
            initial_image=image,
            unverified_tag="weekly_entry_unverified",
            verified_reason="weekly_entry_transition",
        )

    def _handle_home_entry(self, image, scale, entry):
        self._tap(*scale.to_device(*entry.center))
        # 实机载入英雄之路需 10–16 秒，冷启动更久；窗口仍有界。
        return self._await_transition(
            "home_entry_transition",
            self._recognized_after_home,
            initial_image=image,
            unverified_tag="home_entry_after",
            verified_reason="home_entry_transition",
            wait_s=30,
            attempts=14,
        )

    def _handle_task_reward(self, image):
        # 奖励物品飞入动画播完才出现「繼續」（20261120T100029）；期间只观察不输入。
        image, button = self._await_continue_button(
            image, lambda design: is_task_reward(design), reason="task_reward_animation",
        )
        if button is None:
            self._snapshot(image, tag="task_reward_continue_missing")
            return None
        self._tap(*button.center)
        after = image
        for after in self._transition_frames("task_reward_transition"):
            normalized = self._reward_design(after)
            if normalized is None:
                continue
            if is_task_reward(normalized[0]):
                # 新任务也可用同位置按钮；内容未变化时只观察，不重复点击。
                if np.mean(cv2.absdiff(_continue_view(after), _continue_view(image))) < 15:
                    continue
            elif not (self._recognized_after_home(after)
                      or find_home_adventure_entry(normalized[0]) is not None
                      or self.engine.parser.ui.detect(normalized[0]) is UIState.BATTLE_END):
                continue
            report("verified", "task_reward_transition", progress=True, **self._details)
            return after
        self._snapshot(after, tag="task_reward_transition_unverified")
        return None

    def _complete_adventure(self, image) -> None:
        self._scene("adventure_victory")
        path = snapshot.save_snapshot(
            image, self.settings.perception.snapshot_dir, tag="adventure_victory",
        )
        normalized = self._reward_design(image)
        stage = adventure_settlement(normalized[0]) if normalized is not None else None
        victory = stage in {"victory", "rewards"}
        self._details.update(snapshot=str(path) if path is not None else None,
                             outcome="victory" if victory else "unverified", settlement_closed=False)
        stages = self.SETTLEMENT_STAGES
        seen = set()
        for _ in range(len(stages) + 6):
            if stage == "task_reward":
                after = self._handle_task_reward(image)
            elif stage in stages and stage not in seen:
                seen.add(stage)
                self._scene("adventure_" + stage)
                after = self._continue_final_page(image, stage=stage)
            else:
                self._snapshot(image, tag="adventure_settlement_unknown")
                return
            if after is None:
                return
            normalized = self._reward_design(after)
            next_stage = adventure_settlement(normalized[0]) if normalized is not None else None
            if normalized is not None and is_task_reward(normalized[0]):
                next_stage = "task_reward"
            if next_stage is not None:
                image, stage = after, next_stage
                continue
            if normalized is None or not self._settlement_destination(normalized[0]):
                self._snapshot(after, tag="adventure_victory_transition_unverified")
                return
            self._details.update(settlement_closed=True)
            report("verified", "adventure_victory_transition", progress=True, **self._details)
            self.result = LoopResult("completed", "adventure_victory" if victory
                                     else "reward_settlement_closed")
            return

        self._snapshot(image, tag="adventure_settlement_limit")

    @staticmethod
    def _settlement_destination(design) -> bool:
        return (find_home_adventure_entry(design) is not None
                or find_weekly_entry(design) is not None or is_weekly_list(design))

    def _await_continue_button(self, image, still_on_page, *, reason):
        """「繼續」在页面动画播完后才出现：在固定窗口内只观察，不输入。

        返回 ``(最后一帧, 按钮)``；只采信 ``still_on_page`` 认可的帧，到期仍无按钮时按钮为 ``None``。
        """
        button = find_continue_button(image)
        deadline = time.monotonic() + self.SETTLEMENT_ANIMATION_S
        while button is None and (remaining := deadline - time.monotonic()) > 0:
            self._wait(min(2, remaining), reason=reason, wait_s=self.SETTLEMENT_ANIMATION_S)
            frame = self._frame()
            normalized = self._reward_design(frame)
            if normalized is None or not still_on_page(normalized[0]):
                continue
            image, button = frame, find_continue_button(frame)
        return image, button

    def _continue_final_page(self, image, *, stage: str):
        stages = self.SETTLEMENT_STAGES
        # 胜利页的经验条和各奖励页都有动画，「繼續」播完才出现；期间只观察不输入。
        image, button = self._await_continue_button(
            image, lambda design: adventure_settlement(design) == stage,
            reason="adventure_reward_animation",
        )
        if button is None:
            self._snapshot(image, tag="adventure_victory_continue_missing")
            return
        fresh = self._frame()
        normalized = self._reward_design(fresh)
        fresh_button = find_continue_button(fresh)
        if (normalized is None or adventure_settlement(normalized[0]) != stage
                or fresh_button is None
                or any(abs(a - b) > 12 for a, b in zip(button.center, fresh_button.center, strict=True))):
            self._snapshot(fresh, tag="adventure_victory_continue_unverified")
            return
        self._tap(*fresh_button.center)
        after = fresh
        for after in self._transition_frames("adventure_victory_transition"):
            normalized = self._reward_design(after)
            if normalized is None:
                continue
            design = normalized[0]
            next_stage = adventure_settlement(design)
            if next_stage is not None:
                if stages.index(next_stage) > stages.index(stage):
                    return after
                continue
            if is_task_reward(design) or self._settlement_destination(design):
                return after
        self._snapshot(after, tag="adventure_victory_transition_unverified")

    def _recognized_after_home(self, image) -> bool:
        """只在现有冒险处理器可识别场景时结束主页转场等待。"""
        normalized = self._reward_design(image)
        if normalized is not None and (adventure_settlement(normalized[0]) is not None
                                       or is_task_reward(normalized[0])):
            return True
        if (is_power_vendor(image) or shop_leave_button(image) is not None
                or item_chest_leave_button(image) is not None
                or gold_chest_collect_button(image) is not None or self._is_healer(image)
                or self._is_support(image) or self._is_card_reward(image)
                or self._is_hero_item_reward(image)
                or is_power_screen(image) or is_battle_detail(image) or is_map(image)):
            return True
        height, width = image.shape[:2]
        if width and height and abs(width / height - 16 / 9) <= 0.02:
            design, _ = self.normalizer.fit(image)
            if (find_resume_adventure_button(design) is not None
                    or find_weekly_entry(design) is not None
                    or is_weekly_list(design)
                    or weekly_detail_stars(design) is not None):
                return True
        # 主页转场中的动画可能触发战斗按钮探针；单独的战斗 UI 状态
        # 不能证明已进入冒险，应等待可识别的冒险页面。
        return False

    def _reveal_occluded_map_route(self, image, button):
        self._tap(*button.center)
        after = image
        for after in self._transition_frames("map_zoom_transition", wait_s=6, attempts=3):
            if is_map(after) and not panel_open(after):
                hero = locate_map_hero(after)
                fresh = self._find_next(after, hero)
                if fresh is not None:
                    report("verified", "map_zoom_transition", progress=True)
                    return after, hero, fresh
        self._snapshot(after, tag="map_zoom_unverified")
        return None

    def _reveal_bottom_map_node(self, image, node, hero: HeroToken | None):
        """底边目标先平移一次；新帧重新核实位置和路线后才允许点击。"""
        point = empty_point(image) if is_map(image) and not panel_open(image) else None
        if hero is None or point is None:
            self._snapshot(image, tag="map_pan_precondition_failed")
            return None
        distance = min(240, node.y - (image.shape[0] - 240), point[1] - 150)
        if distance < 80:
            self._snapshot(image, tag="map_pan_precondition_failed")
            return None
        self._require_fresh_input()
        report("execute", "map_pan", start=list(point),
               end=[point[0], point[1] - distance], **self._details)
        self._require_fresh_input()
        self.device.drag(*point, point[0], point[1] - distance, 150, 600)
        after = image
        for after in self._transition_frames("map_pan_transition"):
            if not is_map(after) or panel_open(after):
                continue
            moved = locate_map_hero(after)
            if (moved is None or abs(moved.x - hero.x) > 75
                    or abs(moved.y - (hero.y - distance)) > 75):
                continue
            fresh = self._find_next(after, moved)
            if (fresh is not None and not fresh.needs_reveal
                    and fresh.y + fresh.radius + 20 < after.shape[0]):
                report("verified", "map_pan_transition", progress=True, **self._details)
                return after, fresh
        self._snapshot(after, tag="map_pan_unverified")
        return None

    def _current_reentry(self, image):
        """后继全部锁定时重进脚下未完成节点，结果交由节点处理逐项核验。"""
        if not is_map(image):
            return None
        node = current_unfinished_node(image, locate_map_hero(image))
        if node is not None:
            record_event("map_current_reentry", x=node.x, y=node.y)
        return node

    def _find_next(self, image, hero: HeroToken | None):
        """从调用方在本帧识别的棋子选择已核实路线。"""
        if hero is None:
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
        after = image
        for after in self._transition_frames("power_transition"):
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
        overlay_dismissed = False
        hero_art = getattr(self.pack, "hero_item_art", None)

        def observe_selection():
            nonlocal image, overlay_dismissed
            normalized = self._reward_design(image)
            if normalized is None:
                return None
            design, scale = normalized
            if overlay_dismissed or hero_item_hero_selection(design) is not None:
                return normalized
            hero_index = hero_item_main_index(design, hero_art)
            items = recognize_hero_items(design)
            index = hero_item_item_selection(design)
            if (hero_index is None or items is None
                    or index is None or index < 0 or not hero_item_choose_enabled(design)):
                return normalized
            # 道具关键词提示会遮住英雄边框；已知奖励页右下空白只点一次，
            # 重新采图后仍按完整边框核验，不能因按钮启用就直接确认。
            overlay_dismissed = True
            self._tap(*scale.to_device(1500, 900))
            self._wait(2, reason="hero_item_overlay_dismiss", wait_s=2)
            image = self._frame()
            normalized = self._reward_design(image)
            if normalized is None:
                return None
            after = normalized[0]
            if (not same_hero_item_cards(design, after)
                    or hero_item_main_index(after, hero_art) != hero_index
                    or recognize_hero_items(after) != items
                    or hero_item_item_selection(after) != index):
                return None
            return normalized

        normalized = observe_selection()
        if normalized is None:
            self._snapshot(image, tag="hero_item_selection_unverified")
            return
        design, scale = normalized
        initial_design = design
        hero_index = hero_item_main_index(design, hero_art)
        selected = hero_item_hero_selection(design)
        items = recognize_hero_items(design)
        item_index = hero_item_item_selection(design)
        if (hero_index is None or selected is None or items is None
                or item_index is None
                or (selected == -1 and not hero_item_choose_disabled(design))
                or (item_index == -1 and not hero_item_choose_disabled(design))):
            self._snapshot(image, tag="hero_item_selection_unverified")
            return
        if selected == -1:
            self._tap(*scale.to_device((780, 1125)[hero_index], 430))
            self._wait(2, reason="hero_item_hero_selection", wait_s=2)
            image = self._frame()
            normalized = observe_selection()
            if normalized is None:
                self._snapshot(image, tag="hero_item_hero_unverified")
                return
            design, scale = normalized
            if (not same_hero_item_cards(initial_design, design)
                    or hero_item_main_index(design, hero_art) != hero_index
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
            normalized = observe_selection()
            if normalized is None:
                self._snapshot(image, tag="hero_item_selected_unverified")
                return None
            design, scale = normalized
        if (not same_hero_item_cards(initial_design, design)
                or hero_item_main_index(design, hero_art) != hero_index
                or hero_item_hero_selection(design) != hero_index
                or recognize_hero_items(design) != items
                or hero_item_item_selection(design) != item_index
                or not hero_item_choose_enabled(design)):
            self._snapshot(image, tag="hero_item_selected_unverified")
            return None
        self._tap(*scale.to_device(960, 1003))
        after = image
        for after in self._transition_frames("hero_item_transition"):
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
        after = image
        for after in self._transition_frames("astrologer_leave"):
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
        after = selected
        for after in self._transition_frames("astrologer_purchase"):
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

    def _collect_gold_chest(self, image) -> bool:
        button = gold_chest_collect_button(image)
        if button is None:
            self._snapshot(image, tag="gold_chest_collect_missing")
            return False
        self._scene("gold_chest")
        self._tap(*button.center)
        after = image
        for after in self._transition_frames("gold_chest_transition"):
            if is_map(after) and not panel_open(after):
                report("verified", "gold_chest_map_transition", progress=True,
                       reward_credited_verified=False)
                return True
        self._snapshot(after, tag="gold_chest_transition_unverified")
        return False

    def _leave_item_chest(self, image) -> bool:
        """放弃宝箱强化，单次离开后核验回图。"""
        button = item_chest_leave_button(image)
        if button is None:
            self._snapshot(image, tag="item_chest_leave_missing")
            return False
        self._scene("item_chest")
        self._tap(*button.center)
        after = image
        for after in self._transition_frames("item_chest_leave_transition"):
            if is_map(after) and not panel_open(after):
                report("verified", "item_chest_map_transition", progress=True,
                       reward_skipped=True)
                return True
        self._snapshot(after, tag="item_chest_leave_unverified")
        return False

    def _handle_shop(self, image) -> bool:
        """按当前通用规则离开商店，核实返回地图后继续。"""
        button = shop_leave_button(image)
        if button is None:
            self._snapshot(image, tag="shop_leave_missing")
            return False
        self._tap(*button.center)
        after = image
        for after in self._transition_frames("shop_leave_transition"):
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
        after = image
        # 治疗提示动画结束后才出现完成勾；只观察，不重复点击。
        for after in self._transition_frames("healer_transition", first_delay=3):
            if is_map(after) and not panel_open(after):
                hero = locate_map_hero(after)
                if hero is not None and _current_completed_node_visible(after, hero.center):
                    break
        if self._is_healer(after):
            logger.warning("adventure: 治疗后仍在治疗师页面，停止")
            tag = "healer_unchanged"
        elif is_map(after) and not panel_open(after):
            hero = locate_map_hero(after)
            if hero is not None and _current_completed_node_visible(after, hero.center):
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
        next_image, next_design = selected_image, selected
        for next_image in self._transition_frames("support_transition"):
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

    def _handle_card_reward(self, image) -> np.ndarray | None:
        """核验选中、确认和后继界面后返回后继帧。"""
        normalized = self._reward_design(image)
        if normalized is None:
            self._snapshot(image, tag="card_reward_unknown")
            return None
        design, scale = normalized
        candidates = recognize_card_rewards(design)
        if candidates is None:
            logger.warning("adventure: 卡牌奖励信息不完整或已选中，停止")
            self._snapshot(image, tag="card_reward_unknown")
            return None
        champion_pick = getattr(self.pack, "pick_card_reward", None)
        picked = champion_pick(candidates) if champion_pick is not None else pick_card_reward(
            candidates, getattr(self.pack, "card_preferences", ()),
            getattr(self.pack, "item_preferences", ()),
        )
        if picked is None:
            logger.warning("adventure: 卡牌奖励无法安全排序，停止")
            self._snapshot(image, tag="card_reward_undecided")
            return None
        index = candidates.index(picked.candidate)
        name = picked.candidate.card.name or "未知卡牌"
        record_event("reward_decision", kind="card_reward", selection=index, reason=picked.reason,
                     candidates=[{"slot": slot, "name": candidate.card.name,
                                  "card_kind": candidate.kind,
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
            return None
        self._tap(*scale.to_device(*target.center))
        self._wait(3)
        selected_image = self._frame()
        selected = self._reward_design(selected_image)
        if (selected is None or card_reward_selection(selected[0]) != index
                or not same_card_reward_choices(design, selected[0], index)):
            self._snapshot(
                selected_image, tag="card_reward_selection_failed"
            )
            return None
        report("verified", "card_reward_selected", progress=True, selection=index)
        button = card_reward_confirm_button(selected[0])
        if button is None:
            self._snapshot(
                selected_image, tag="card_reward_confirm_missing"
            )
            return None
        self._tap(*selected[1].to_device(*button.center))
        previous_scene = None
        next_image, next_design = selected_image, selected
        for next_image in self._transition_frames("card_reward_transition"):
            next_design = self._reward_design(next_image)
            next_scene = None
            if next_design is not None and not is_card_reward_screen(next_design[0]):
                if is_map(next_design[0]):
                    next_scene = "map"
                elif is_power_screen(next_design[0]):
                    next_scene = "power"
            # 奖励消退时可能短暂露出地图，等连续两帧核验后再交接。
            if next_scene is not None and next_scene == previous_scene:
                report("verified", "card_reward_transition", progress=True, selection=index,
                       reward_credited_verified=False)
                return next_image
            previous_scene = next_scene
        tag = ("card_reward_confirm_unchanged" if next_design is not None
               and is_card_reward_screen(next_design[0]) else "card_reward_after_unknown")
        self._snapshot(next_image, tag=tag)
        return None

    def _close_panel(self, image) -> bool:
        # 动态找“非节点”的空白区域，不固定某个坐标。
        for _ in range(2):
            point = empty_point(image)
            if point is None:
                return False
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
        if gold_chest_collect_button(image) is not None:
            return self._collect_gold_chest(image)
        if item_chest_leave_button(image) is not None:
            return self._leave_item_chest(image)
        if shop_leave_button(image) is not None:
            return self._handle_shop(image)
        if self._is_healer(image):
            return self._handle_healer(image)
        if self._is_support(image):
            return self._handle_support(image)
        if self._is_hero_item_reward(image):
            return self._handle_hero_item_reward(image) is not None
        if self._is_card_reward(image):
            return self._handle_card_reward(image) is not None
        design = self._reward_design(image)
        if design is not None and (
            service_error_confirm(design[0]) is not None
            or reward_timeout_continue(design[0]) is not None
            or is_task_reward(design[0])
            or adventure_settlement(design[0]) is not None
        ):
            return True
        ui = self.engine.parser.ui.detect(design[0] if design is not None else image)
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
        if is_map(image) and self._find_next(image, locate_map_hero(image)) is not None:
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
            # 旅行或战斗可能先出现载入画面。只等待新帧，绝不重复点击；
            # 看到可识别的场景再交给对应处理，超时仍未知则停止。
            for image in self._transition_frames("node_transition", wait_s=24, attempts=11,
                                                 first_delay=4):
                if is_power_vendor(image):
                    return self._handle_astrologer(image)
                if gold_chest_collect_button(image) is not None:
                    return self._collect_gold_chest(image)
                if item_chest_leave_button(image) is not None:
                    return self._leave_item_chest(image)
                if shop_leave_button(image) is not None:
                    return self._handle_shop(image)
                if self._is_healer(image):
                    return self._handle_healer(image)
                if self._is_support(image):
                    return self._handle_support(image)
                if self._is_hero_item_reward(image):
                    return self._handle_hero_item_reward(image) is not None
                if self._is_card_reward(image):
                    return self._handle_card_reward(image) is not None
                design = self._reward_design(image)
                if design is not None and (
                    service_error_confirm(design[0]) is not None
                    or reward_timeout_continue(design[0]) is not None
                    or is_task_reward(design[0])
                    or adventure_settlement(design[0]) is not None
                ):
                    return True
                ui = self.engine.parser.ui.detect(design[0] if design is not None else image)
                if ui in self.BATTLE_STATES or ui is UIState.BATTLE_END:
                    return True
                if is_power_screen(image):
                    return self._handle_power(image) is not None
                if is_battle_detail(image):
                    break
                if is_map(image):
                    if action != "travel" or panel_open(image):
                        break
                    # 旅行后回到无面板地图且已有下一可达节点：说明只是移动节点，继续下一轮。
                    # 若尚无可达节点，说明英雄仍在路径移动或节点页面尚未弹出，继续观察等待。
                    if self._find_next(image, locate_map_hero(image)) is not None:
                        return True
            else:
                logger.warning("adventure: 节点转场后画面仍无法识别，停止")
                self._snapshot(
                    image, tag="panel_transition_timeout"
                )
                return False
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
        if self._late_transition_capture:
            assert self._latest_frame is not None
            image = self._latest_frame.image
            self._late_transition_capture = False
        path = snapshot.save_snapshot(
            image, out_dir or self.settings.perception.snapshot_dir, tag=tag,
        )
        snapshot_path = str(path) if path is not None else None
        if tag == "healer_completed":
            report("verified", tag, progress=True, snapshot=snapshot_path)
        else:
            self.result = LoopResult("stopped", tag)
            self._details.update(snapshot=snapshot_path)
            if tag == "battle_reward_missing" or tag.startswith("card_reward_"):
                normalized = self._reward_design(image)
                evidence = card_reward_diagnostics(normalized[0] if normalized is not None else image)
                self._details["recognition_diagnostic"] = evidence
                record_event("perception_diagnostic", reason=tag, expected_scene="card_reward",
                             snapshot=snapshot_path, **evidence)
            report("stopped", tag, **self._details)
        return path

    def _require_fresh_input(self) -> None:
        assert self._latest_frame is not None
        checkpoint()
        if self._latest_frame.age_s() > self.settings.loop.max_frame_age_s:
            raise _AdventureInputExpired

    def _tap(self, *point) -> None:
        self._require_fresh_input()
        report("execute", "adventure_tap", target=list(point), **self._details)
        self._require_fresh_input()
        self.device.tap(*point)

    def _wait(
        self, seconds: float, *, reason: str = "adventure_transition", wait_s: float | None = None,
    ) -> None:
        # 轮询沿用整个转场的观察期限，不能把每次 sleep 当成新的进展。
        report("waiting", reason, wait_s=seconds + 5 if wait_s is None else wait_s,
               **self._details)
        Engine._wait(seconds)

    def _transition_frames(self, reason, *, wait_s=12, attempts=6, first_delay=2, initial=None):
        """在固定时间窗口内轮询，跨过截止时间的截图不交给后继判定。"""
        started = time.monotonic()
        deadline = started + wait_s
        if initial is not None:
            yield initial
        for attempt in range(attempts):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            delay = first_delay if attempt == 0 else 2
            # 接近截止时给最后一次截图留出时间，而不是把预算全部用来等待。
            self._wait(min(delay, remaining / 2), reason=reason, wait_s=remaining)
            if time.monotonic() >= deadline:
                break
            image = self._frame()
            elapsed = time.monotonic() - started
            if elapsed >= wait_s:
                self._late_transition_capture = True
                record_event("adventure_transition_deadline", reason=reason, wait_s=wait_s,
                             elapsed_s=round(elapsed, 3))
                break
            yield image
        yield from self._loading_extension_frames(reason)

    def _loading_extension_frames(self, reason):
        """原窗口末仍是已知载入画面时继续有界观察；只截图，不重新决策或输入。"""
        if self._latest_frame is None or not is_loading_screen(self._latest_frame.image):
            return
        self._late_transition_capture = False
        record_event("adventure_loading_extension", reason=reason,
                     wait_s=self.LOADING_EXTENSION_S)
        yield self._latest_frame.image
        deadline = time.monotonic() + self.LOADING_EXTENSION_S
        while (remaining := deadline - time.monotonic()) > 0:
            self._wait(min(2, remaining / 2), reason=f"{reason}_loading", wait_s=remaining)
            if time.monotonic() >= deadline:
                return
            image = self._frame()
            if time.monotonic() >= deadline:
                self._late_transition_capture = True
                return
            yield image

    def _await_transition(
        self,
        reason: str,
        accept,
        *,
        initial_image,
        unverified_tag: str,
        verified_reason: str | None = None,
        wait_s: float = 12,
        attempts: int = 6,
        first_delay: float = 2,
        initial=None,
    ):
        after = initial_image
        for after in self._transition_frames(
            reason, wait_s=wait_s, attempts=attempts, first_delay=first_delay, initial=initial,
        ):
            if accept(after):
                if verified_reason is not None:
                    report("verified", verified_reason, progress=True, **self._details)
                return after
        self._snapshot(after, tag=unverified_tag)
        return None

    def _frame(self):
        checkpoint()
        self._late_transition_capture = False
        report("capture", **self._details)
        started = time.time()
        self._latest_frame = self.capture_frame()
        report("recognize", capture_ms=round((time.time() - started) * 1000), **self._details)
        return self._latest_frame.image
