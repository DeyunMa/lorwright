"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time
from dataclasses import asdict, replace

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.config import Settings
from lorwright.core.decide.discard import choose_discard
from lorwright.core.decide.router import Router, RouteResult
from lorwright.core.device.base import Device
from lorwright.core.loop.outcome import ActionOutcome, LoopResult, Outcome, OutcomeStatus
from lorwright.core.loop.readiness import ActionReadiness
from lorwright.core.loop.reconnect import ReconnectTimeout
from lorwright.core.loop.recovery import RecoveryAction, RecoveryPolicy
from lorwright.core.loop.watchdog import Watchdog
from lorwright.core.models import Action, ActionType, ClickPlan, GameState, Layout, UIState
from lorwright.core.perceive.adventure_scene import (
    find_home_adventure_entry,
    reward_timeout_continue,
)
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.discard import discard_candidates
from lorwright.core.perceive.normalize import Normalizer, Scale
from lorwright.core.perceive.result_screen import is_result_transition
from lorwright.core.perceive.state import StateParser
from lorwright.core.perceive.ui_state import UIStateDetector
from lorwright.core.runtime.session import (
    StopRequested,
    checkpoint,
    current_session,
    record_event,
    report,
)
from lorwright.core.util.events import emit
from lorwright.core.util.logger import logger
from lorwright.core.util.snapshot import save_snapshot


class Engine:
    def __init__(
        self,
        settings: Settings,
        router: Router,
        device: Device,
        layout: Layout | None = None,
        ui_detector: UIStateDetector | None = None,
        recovery: RecoveryPolicy | None = None,
        card_recognizer=None,
        mulligan_recognizer=None,
        targeted_spell_recognizer=None,
        confirm_empty_hand_once: bool = False,
        capture_frame=None,
        my_unit_recognizer=None,
    ) -> None:
        self._confirm_empty_hand_once = confirm_empty_hand_once
        self.settings = settings
        self.router = router
        self.device = device
        self.capture_frame = capture_frame or (lambda: self.device.screencap())
        self.layout = layout or settings.layout.to_layout()
        self.ui_detector = ui_detector or UIStateDetector(
            threshold=settings.perception.match_threshold,
            action_button=self.layout.end_turn,
        )
        self.translator = ActionTranslator(
            self.layout,
            drag_ms=settings.act.drag_ms,
            drag_hold_ms=settings.act.drag_hold_ms,
            drag_wait_ms=settings.act.drag_wait_ms,
            tap_wait_ms=settings.act.tap_wait_ms,
            expand_wait_ms=settings.act.expand_wait_ms,
        )
        self.watchdog = Watchdog(threshold=settings.loop.stuck_threshold)
        self.recovery = recovery or RecoveryPolicy()
        self.parser = StateParser(
            layout=self.layout,
            ui=self.ui_detector,
            digits=DigitReader(),
            threshold=settings.perception.match_threshold,
            card_recognizer=card_recognizer,
            mulligan_recognizer=mulligan_recognizer,
            targeted_spell_recognizer=targeted_spell_recognizer,
            my_unit_recognizer=my_unit_recognizer,
        )
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self._scale = Scale(1.0, 1.0)
        self._skipped_stale = 0
        self._pending: ActionOutcome | None = None
        #: 待确认的出牌保留原后验及截止，附加确认不新建父动作预算。
        self._staged_play: ActionOutcome | None = None
        self._readiness = ActionReadiness()
        self._readiness_deadline: float | None = None
        self._wait_deadlines: dict[str, tuple[float, float]] = {}
        self._observation: dict = {}
        self._stop_details: dict = {}

    def observe_hand(self, *, expanded: bool, close_device: bool = True) -> LoopResult:
        """单次视图调整：整体固定截止、最多一次输入、两张新鲜目标帧。"""
        action = Action(ActionType.EXPAND_HAND if expanded else ActionType.COLLAPSE_HAND)
        self._readiness.reset()
        self._observation = {}
        self._stop_details.clear()
        deadline = time.monotonic() + self.settings.loop.action_timeout_s
        pending = None
        target_frames = 0
        self.result = LoopResult("stopped", "hand_view_unverified")
        try:
            self.parser.load()
            while True:
                checkpoint()
                report("capture", action=action.type.value)
                frame = self.capture_frame()
                image, self._scale = self.normalizer.fit(frame.image)
                state = self._build_state(image)
                self._observation = dict(ui=state.ui_state.value, summary=state.summary(),
                                         action=action.type.value, hand_expanded=state.hand_expanded)
                report("recognized", **self._observation)
                if time.monotonic() >= deadline:
                    if pending is not None:
                        self._observe_outcome(pending, state, 0)
                    self._stop_snapshot(frame.image, "hand_view_unverified")
                    break
                if frame.age_s() > self.settings.loop.max_frame_age_s:
                    target_frames = 0
                    self._readiness.reset()
                elif state.ui_state is UIState.UNKNOWN:
                    target_frames = 0
                    self._readiness.reset()
                elif state.ui_state is not UIState.MY_TURN_IDLE:
                    self._stop_snapshot(frame.image, "hand_view_unavailable")
                    break
                else:
                    self._readiness.observe(state)
                    at_target = state.hand_expanded is expanded and (not expanded or bool(state.hand))
                    target_frames = target_frames + 1 if at_target else 0
                    if target_frames >= 2:
                        if pending is not None:
                            self._observe_outcome(pending, state, 0)
                        path = save_snapshot(frame.image, self.settings.perception.snapshot_dir,
                                             tag="hand_view_verified")
                        report("verified", "hand_view_verified", progress=True,
                               snapshot=str(path) if path is not None else None,
                               inputs=0 if pending is None else 1, **self._observation)
                        self.result = LoopResult("completed", "hand_view_verified")
                        break
                    if not at_target and pending is None:
                        if expanded and not state.hand:
                            self._stop_snapshot(frame.image, "hand_view_unavailable")
                            break
                        if self._readiness.ready(action):
                            plan = self.translator.translate(action, state)
                            if plan is None or frame.age_s() > self.settings.loop.max_frame_age_s:
                                self._stop_snapshot(frame.image, "hand_view_unavailable")
                                break
                            if time.monotonic() >= deadline:
                                self._stop_snapshot(frame.image, "hand_view_unverified")
                                break
                            inputs = self._execute(plan)
                            self._readiness.reset()
                            record_event("input_sent", action=action.type.value, inputs=inputs)
                            pending = ActionOutcome(action, state, deadline)
                report("waiting", "hand_view_result", wait_s=max(0.0, deadline - time.monotonic()))
                self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
        finally:
            if close_device:
                self.device.close()
        return self.result

    def run(self, max_ticks: int | None = None, *, close_device: bool = True) -> LoopResult:
        self.parser.load()

        w, h = self.device.size()
        logger.info(
            "engine start: device={} size={}x{} design={}x{} layers={} layout={}",
            self.device.name, w, h,
            self.settings.screen.width, self.settings.screen.height,
            [getattr(p, "name", type(p).__name__) for p in self.router.layers],
            "ready" if self.layout.end_turn else "NOT CALIBRATED",
        )
        if (w, h) != (self.settings.screen.width, self.settings.screen.height):
            logger.info(
                "分辨率与设计尺寸不一致（{}x{} vs {}x{}），已按设计尺寸归一化",
                w, h, self.settings.screen.width, self.settings.screen.height,
            )
        if not self.layout.end_turn:
            logger.warning("layout 未标定，动作会被跳过。先跑 `lorwright shot` 量坐标。")

        ticks = 0
        previous_ui = None
        target_wait_deadline = None
        result_transition_deadline = None
        result_transition_used = False
        inspecting_board = False
        self._readiness.reset()
        self._readiness_deadline = None
        self._wait_deadlines.clear()
        self._stop_details.clear()
        self.result = LoopResult("stopped", "tick_limit")
        try:
            while max_ticks is None or ticks < max_ticks:
                ticks += 1
                t0 = time.monotonic()

                checkpoint()
                report("capture", tick=ticks)
                captured_at = time.time()
                frame = self.capture_frame()
                report("recognize", capture_ms=round((time.time() - captured_at) * 1000))
                recognition_started = time.time()
                image, self._scale = self.normalizer.fit(frame.image)
                state = self._build_state(image)
                age = frame.age_s()
                self._observation = dict(
                    tick=ticks, ui=state.ui_state.value, summary=state.summary(),
                    unknown_cards=[card.index for card in state.hand if not card.name],
                    readings={name: asdict(reading) for name, reading in state.readings.items()},
                )
                changed = (age <= self.settings.loop.max_frame_age_s
                           and state.ui_state is not UIState.UNKNOWN
                           and state.ui_state != previous_ui)
                if changed:
                    self._wait_deadlines.clear()
                    record_event("battle_scene", ui=state.ui_state.value)
                report("recognized", ui=state.ui_state.value, summary=state.summary(),
                       progress=changed,
                       recognition_ms=round((time.time() - recognition_started) * 1000))
                if changed:
                    previous_ui = state.ui_state
                if state.ui_state is not UIState.MY_TURN_IDLE:
                    if state.ui_state is not UIState.UNKNOWN:
                        inspecting_board = False

                if target_wait_deadline is not None:
                    if age <= self.settings.loop.max_frame_age_s and state.ui_state not in (
                        UIState.TARGETING, UIState.UNKNOWN,
                    ):
                        target_wait_deadline = None
                    elif time.monotonic() >= target_wait_deadline:
                        self._stop_snapshot(frame.image, "unknown_target")
                        break

                # 帧时效：截图 + 识别 + 决策如果已经花了太久，画面可能早变了。
                # 拿旧帧去点就是「状态不明还点」，宁可这一轮什么都不做。
                if age > self.settings.loop.max_frame_age_s:
                    self._readiness.observe(None)
                    self._skipped_stale += 1
                    self._report_wait("stale_frame", self.settings.loop.max_frame_age_s)
                    logger.warning(
                        "stale frame: age={:.2f}s > {:.2f}s，本轮不动作（累计 {}）",
                        age, self.settings.loop.max_frame_age_s, self._skipped_stale,
                    )
                    emit(
                        tick=ticks, ui=state.ui_state.value, layer="stale",
                        action="no_op", clicks=0, stuck=False,
                        ms=round((time.monotonic() - t0) * 1000),
                    )
                    if result_transition_deadline is not None:
                        if time.monotonic() >= result_transition_deadline:
                            self._stop_snapshot(frame.image, "battle_result_transition_unverified")
                            break
                        self._report_wait("battle_result_transition",
                                          result_transition_deadline - time.monotonic())
                        self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                        continue
                    pending = self._staged_play or self._pending
                    if pending is not None and time.monotonic() >= pending.deadline:
                        emit(
                            tick=ticks, event="action_outcome",
                            action=pending.action.type.value, status="timed_out",
                            reason="no_fresh_frame_before_deadline", clicks=0,
                        )
                        self._stop_snapshot(frame.image, "action_timeout")
                        break
                    if not self._wait_or_stop(
                        frame.image, "stale_frame", self.settings.loop.max_frame_age_s,
                    ):
                        break
                    continue

                if state.ui_state is UIState.DISCARD:
                    state.discard_candidates = discard_candidates(image, self.parser.digits)
                self._readiness.observe(state)
                # 相关证据抖动、UI 来回变化都不能给同一次输入准备重新计时。
                if (self._readiness_deadline is not None
                        and time.monotonic() >= self._readiness_deadline):
                    self._stop_snapshot(frame.image, "action_readiness_unverified")
                    break

                # 奖励详情超时可能覆盖战斗画面；单次确认后只接受明确转场。
                timeout_button = reward_timeout_continue(image)
                if timeout_button is not None:
                    checkpoint()
                    self.device.tap(*self._scale.to_device(*timeout_button.center))
                    for _ in range(6):
                        self._report_wait("reward_timeout_transition", 12)
                        self._wait(2)
                        after = self.capture_frame()
                        after_image, _ = self.normalizer.fit(after.image)
                        if (after.age_s() > self.settings.loop.max_frame_age_s
                                or reward_timeout_continue(after_image) is not None):
                            continue
                        after_ui = self.parser.ui.detect(after_image)
                        if (find_home_adventure_entry(after_image) is not None
                                or after_ui in {UIState.MULLIGAN, UIState.MY_TURN_IDLE,
                                                UIState.BLOCKING, UIState.BATTLE_END}):
                            self.result = LoopResult("stopped", "reward_timeout_transition")
                            report("verified", "reward_timeout_transition", progress=True)
                            break
                    else:
                        self._stop_snapshot(after.image, "reward_timeout_transition_unverified")
                    break

                if (result_transition_deadline is not None
                        and time.monotonic() >= result_transition_deadline):
                    self._stop_snapshot(frame.image, "battle_result_transition_unverified")
                    break

                # 对局结束后由外层流程处理结果界面。
                if state.ui_state is UIState.BATTLE_END:
                    self._pending = None
                    self._staged_play = None
                    self.result = LoopResult("completed", "battle_end")
                    report("completed", "battle_end", progress=True)
                    break

                # 明确结算背景只交接观察权，不宣告原动作成功或重发输入。
                pending = self._staged_play or self._pending
                if (not result_transition_used and state.ui_state is UIState.UNKNOWN
                        and (pending is None or time.monotonic() < pending.deadline)
                        and is_result_transition(image)):
                    result_transition_used = True
                    result_transition_deadline = time.monotonic() + 60.0
                    self._readiness_deadline = None
                    target_wait_deadline = None
                    record_event("battle_result_transition", timeout_s=60,
                                 interrupted_action=pending.action.type.value if pending else None,
                                 action_deadline=pending.deadline if pending else None)
                if result_transition_deadline is not None:
                    if state.ui_state is UIState.UNKNOWN:
                        self._report_wait("battle_result_transition",
                                          result_transition_deadline - time.monotonic())
                        self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                        continue
                    # 返回战斗时仍核验原动作及原截止；不能借转场刷新动作预算。
                    result_transition_deadline = None

                if (self._staged_play is not None
                        and time.monotonic() >= self._staged_play.deadline):
                    self._observe_outcome(self._staged_play, state, ticks)
                    self._stop_snapshot(frame.image, "action_timeout")
                    break

                # 已发送的输入先等新帧证明结果，不能每 tick 重放同一个手势。
                if self._pending is not None:
                    outcome = self._observe_outcome(self._pending, state, ticks)
                    if (outcome.status is OutcomeStatus.SUCCEEDED
                            and self._pending.action.type is ActionType.CONFIRM
                            and self._staged_play is not None):
                        self._notify_outcome(self._pending, state)
                        report("verified", outcome.reason, progress=True, action="confirm")
                        self._pending = self._staged_play
                        self._staged_play = None
                        self._pending.resume_after_confirmation()
                        outcome = self._observe_outcome(self._pending, state, ticks)
                    if outcome.status is OutcomeStatus.TIMED_OUT:
                        self._stop_snapshot(frame.image, "action_timeout")
                        logger.error("动作结果未确认，停止主循环：{}", self._pending.action.type.value)
                        break
                    if outcome.status is OutcomeStatus.WAITING:
                        self._report_wait(outcome.reason,
                                          max(0.0, self._pending.deadline - time.monotonic()),
                                          action=self._pending.action.type.value)
                        self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                        continue
                    if (outcome.status is OutcomeStatus.NEEDS_INPUT
                            and outcome.reason == "confirmation_required"):
                        self._staged_play = self._pending
                    if outcome.status is OutcomeStatus.SUCCEEDED:
                        if self._pending.action.type is ActionType.COLLAPSE_HAND:
                            inspecting_board = True
                        self._wait_deadlines.clear()
                        report("verified", outcome.reason, progress=True,
                               action=self._pending.action.type.value)
                        self._notify_outcome(self._pending, state)
                    self._pending = None
                    self.watchdog.reset()
                    self.recovery.reset()

                # 安全约束由执行入口保障，不能依赖每一个英雄包都正确弃权。
                if state.ui_state is UIState.UNKNOWN:
                    emit(tick=ticks, layer="unknown", action="no_op", clicks=0)
                    if not self._wait_or_stop(
                        frame.image, "unknown_ui", self.settings.loop.action_timeout_s,
                    ):
                        break
                    continue

                # 人工确认仅用于第一张新鲜的己方行动画面，不跨帧沿用。
                manual_empty = False
                if self._confirm_empty_hand_once and state.ui_state is UIState.MY_TURN_IDLE:
                    self._confirm_empty_hand_once = False
                    manual_empty = not state.hand
                    if manual_empty:
                        state.hand_empty_confirmed = True
                    record_event("manual_empty_hand_consumed", accepted=manual_empty)
                    if not manual_empty:
                        emit(tick=ticks, layer="manual_empty_hand_conflict", action="no_op", clicks=0)
                        if not self._wait_or_stop(
                            frame.image, "manual_empty_hand_conflict", self.settings.loop.action_timeout_s,
                        ):
                            break
                        continue

                # 缺失读数只限制依赖它的动作，不把旧法力交给策略当作可用资源。
                decision_state = replace(
                    state,
                    mana=state.mana if state.has_fresh_readings("mana") else -1,
                    spell_mana=(state.spell_mana
                                if state.has_fresh_readings("spell_mana") else None),
                )

                report("decide")
                decision_at = time.time()
                if state.ui_state is UIState.DISCARD:
                    candidates = state.discard_candidates
                    if candidates is None:
                        self._stop_snapshot(frame.image, "discard_candidates_unverified")
                        break
                    action = choose_discard(candidates)
                    if action is None:
                        self._stop_snapshot(frame.image, "discard_cost_unverified")
                        break
                    result = RouteResult(action, "discard", "按已核实重复牌及费用选择弃牌")
                else:
                    result = (self.router.decide(decision_state, suppress_hand_expansion=True)
                              if inspecting_board else self.router.decide(decision_state))
                if (not inspecting_board and state.ui_state is UIState.MY_TURN_IDLE
                        and state.hand_expanded and state.has_attack_token
                        and self.layout.collapse_hand_point is not None
                        and (result.action.type is ActionType.ATTACK
                             or (result.action.type is ActionType.NO_OP
                                 and result.action.raw.get("inspect_board") is True)
                             or result.action.type is ActionType.END_TURN)):
                    result.action = Action(type=ActionType.COLLAPSE_HAND)
                    result.layer = "inspect_board"
                    result.reason = "展开手牌可能遮挡友军，先收起并重新评估攻击"
                if state.ui_state is UIState.TARGETING and result.action.type is ActionType.NO_OP:
                    if target_wait_deadline is None:
                        target_wait_deadline = time.monotonic() + self.settings.loop.action_timeout_s
                    self._report_wait("unknown_target", max(0.0, target_wait_deadline - time.monotonic()))
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue
                target_wait_deadline = None
                self._observation.update(
                    action=result.action.type.value, strategy=result.layer,
                    decision_reason=result.reason,
                    unknown_cards=[card.index for card in state.hand if not card.name],
                )
                report("decided", **self._observation,
                       decision_ms=round((time.time() - decision_at) * 1000))
                missing = self._missing_action_evidence(result.action, state)
                if manual_empty and result.action.type is not ActionType.ATTACK:
                    missing.append("manual_attack")
                if missing:
                    emit(tick=ticks, layer="unreadable", action="no_op", clicks=0,
                         missing_readings=missing,
                         readings={name: asdict(reading) for name, reading in state.readings.items()})
                    if not self._wait_or_stop(
                        frame.image, "action_preconditions_unverified",
                        self.settings.loop.action_timeout_s, missing_readings=missing,
                    ):
                        break
                    continue
                # 网络决策也可能耗时；执行前必须再次确认这张图仍然新鲜。
                if frame.age_s() > self.settings.loop.max_frame_age_s:
                    self._readiness.observe(None)
                    self._skipped_stale += 1
                    emit(tick=ticks, layer="stale", action="no_op", clicks=0,
                         reason="frame_expired_during_decision")
                    if not self._wait_or_stop(
                        frame.image, "frame_expired_during_decision",
                        self.settings.loop.max_frame_age_s,
                    ):
                        break
                    continue
                if result.action.type is ActionType.NO_OP:
                    reason = "enemy_turn" if state.ui_state is UIState.ENEMY_TURN else "no_action"
                    emit(tick=ticks, ui=state.ui_state.value, layer=result.layer,
                         action="no_op", clicks=0, reason=reason)
                    if not self._wait_or_stop(
                        frame.image, reason,
                        60.0 if reason == "enemy_turn" else self.settings.loop.action_timeout_s,
                    ):
                        break
                    continue

                if not self._action_ready(result.action):
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue

                stuck = self.watchdog.observe(state, result.action.type)
                if self.watchdog.progressed:
                    self.recovery.reset()

                clicks = 0
                if stuck:
                    logger.warning("stuck: {}", state.summary())
                    path = save_snapshot(
                        frame.image, self.settings.perception.snapshot_dir, tag="stuck"
                    )
                    self._stop_details = dict(snapshot=str(path) if path is not None else None)
                    if not self._recover(state):
                        break
                    self._stop_details.clear()
                else:
                    report("execute", action=result.action.type.value)
                    execution_at = time.time()
                    plan = self.translator.translate(result.action, state)
                    if plan is None or not plan.points:
                        if not self._wait_or_stop(
                            frame.image, "action_plan_unavailable", self.settings.loop.action_timeout_s,
                        ):
                            break
                        continue
                    if result.action.type is ActionType.PLAY_CARD:
                        card = next((c for c in state.hand
                                     if c.index == result.action.card_index), None)
                        emit(
                            tick=ticks, event="play_card_attempt", layer=result.layer,
                            card_index=result.action.card_index,
                            card=asdict(card) if card is not None else None,
                            hand_expanded=state.hand_expanded, mana=state.mana,
                            spell_mana=state.spell_mana,
                            readings={name: asdict(reading)
                                      for name, reading in state.readings.items()},
                            action_raw=result.action.raw,
                            plan=asdict(plan) if plan is not None else None,
                            scale=asdict(self._scale),
                        )
                    clicks = self._execute(plan)
                    if clicks:
                        for layer in self.router.layers:
                            callback = getattr(layer, "on_action_sent", None)
                            if callback is not None:
                                callback(result.action, state)
                    report("input_sent", action=result.action.type.value, inputs=clicks,
                           decision_reason=result.reason)
                    self._report_wait(
                        "action_result" if clicks else (
                            "enemy_turn" if state.ui_state is UIState.ENEMY_TURN else "no_action"
                        ),
                        60 if state.ui_state is UIState.ENEMY_TURN
                        else self.settings.loop.action_timeout_s,
                        execution_ms=round((time.time() - execution_at) * 1000),
                    )
                    if clicks and result.action.type is not ActionType.NO_OP:
                        timeout = self.settings.loop.action_timeout_s
                        if (result.action.type is ActionType.END_TURN
                                or (result.action.type is ActionType.CONFIRM
                                    and (self._staged_play is not None
                                         or state.ui_state is UIState.MULLIGAN
                                         or state.ui_state is UIState.COMBAT_RESOLVING))):
                            # 换牌入场、回合结束、法术和战斗确认可能超过普通观察窗口。
                            timeout = max(timeout, 20.0)
                        self._pending = self._make_outcome(result.action, state, timeout)
                        if self._staged_play is not None:
                            self._pending.deadline = min(
                                self._pending.deadline, self._staged_play.deadline,
                            )

                elapsed_ms = round((time.monotonic() - t0) * 1000)
                emit(
                    tick=ticks,
                    ui=state.ui_state.value,
                    layer=result.layer,
                    action=result.action.type.value,
                    clicks=clicks,
                    stuck=stuck,
                    ms=elapsed_ms,
                    # 决策依据：事后能看出「为什么没出牌」，不然只能靠复现
                    mana=state.mana,
                    hand=[c.cost for c in state.hand],
                    readings={name: asdict(reading) for name, reading in state.readings.items()},
                )

                self._wait(max(0.0, (self.settings.loop.tick_ms - elapsed_ms) / 1000))
            report(self.result.status, self.result.reason, **self._observation, **self._stop_details)
            return self.result
        except ReconnectTimeout:
            raise
        except StopRequested:
            report("stopping", "stop_requested")
            raise
        except Exception as exc:
            report("error", type(exc).__name__, error=str(exc))
            raise
        finally:
            if close_device:
                self.device.close()
            logger.info("engine stop: coverage={}", self.router.coverage())

    def _action_ready(self, action: Action) -> bool:
        if self._readiness.ready(action):
            return True
        if self._readiness_deadline is None:
            self._readiness_deadline = time.monotonic() + self.settings.loop.action_timeout_s
        report("waiting", "action_readiness_unverified",
               wait_s=max(0.0, self._readiness_deadline - time.monotonic()),
               **self._observation)
        return False

    @staticmethod
    def _observe_outcome(pending: ActionOutcome, state: GameState, tick: int) -> Outcome:
        outcome = pending.observe(state, time.monotonic())
        emit(
            tick=tick, event="action_outcome", action=pending.action.type.value,
            card_index=pending.action.card_index, status=outcome.status.value,
            reason=outcome.reason, clicks=0,
            before=pending.before.summary(), after=state.summary(),
            before_action_prompt=pending.before.action_prompt,
            after_action_prompt=state.action_prompt,
            readings={name: asdict(reading) for name, reading in state.readings.items()},
        )
        return outcome

    def _notify_outcome(self, pending: ActionOutcome, state: GameState) -> None:
        for layer in self.router.layers:
            callback = getattr(layer, "on_action_outcome", None)
            if callback is not None:
                callback(pending.action, pending.before, state)

    def _make_outcome(self, action: Action, before: GameState, timeout: float) -> ActionOutcome:
        expectation = None
        if action.type is ActionType.PLAY_CARD and before.hand_expanded:
            card = next((card for card in before.hand if card.index == action.card_index), None)
            if card is not None and (card.visible_playable_unit
                                     or action.raw.get("unit_card") is True):
                # 已展开且确认单位卡的实际出牌包含召唤/触发动画；从发送时固定预算。
                timeout = max(timeout, 20.0)
            for layer in self.router.layers:
                factory = getattr(layer, "play_expectation", None)
                if factory is not None:
                    expectation = factory(action, before)
                    if expectation is not None:
                        timeout = max(timeout, expectation.timeout_s)
                        break
        return ActionOutcome(
            action, before, time.monotonic() + timeout,
            combat_row_min_move_px=self.settings.loop.combat_row_min_move_px,
            play_expectation=expectation,
        )

    @staticmethod
    def _missing_action_evidence(action: Action, state: GameState) -> list[str]:
        """只校验当前动作的必要证据；血量和无关手牌不作全局门槛。"""
        if action.type is ActionType.SKIP_CHOICE:
            return [] if state.ui_state is UIState.OPTIONAL_CHOICE else ["optional_choice"]
        if action.type is ActionType.PICK_CHOICE:
            return [] if state.ui_state is UIState.REQUIRED_CHOICE else ["required_choice"]
        if action.type is ActionType.ATTACK:
            if (state.ui_state is not UIState.MY_TURN_IDLE or not state.has_attack_token
                    or not any(unit.can_attack and not unit.stunned for unit in state.my_units)):
                return ["attack_priority"]
        if action.type in (ActionType.END_TURN, ActionType.PASS):
            if state.ui_state is not UIState.MY_TURN_IDLE:
                return ["my_turn"]
        if action.type is not ActionType.PLAY_CARD:
            return []
        if state.ui_state is not UIState.MY_TURN_IDLE:
            return ["my_turn"]
        if not state.hand_expanded:
            return ["expanded_hand"]
        card = next((card for card in state.hand if card.index == action.card_index), None)
        if card is None or not card.drag_point_valid:
            return ["card_position"]
        if card.cost < 0:
            return ["card_cost"]
        if card.cost == 0:
            return []
        if action.raw.get("spell_mana_only"):
            if (state.has_fresh_readings("spell_mana") and state.spell_mana is not None
                    and card.cost <= state.spell_mana):
                return []
            return ["spell_mana"]
        if not state.has_fresh_readings("mana"):
            return ["mana"]
        spell_available = (
            0 if action.raw.get("unit_card")
            else (state.spell_mana if state.has_fresh_readings("spell_mana")
                  and state.spell_mana is not None else 0)
        )
        available = state.mana + spell_available
        return [] if card.cost <= available else ["affordable_cost"]

    def _report_wait(self, reason: str, wait_s: float, **details) -> float:
        """核心以单调时钟计时，CLI 接收对应的墙钟截止时间。"""
        now = time.monotonic()
        deadline, wait_until = self._wait_deadlines.setdefault(reason, (now + wait_s, time.time() + wait_s))
        remaining = max(0.0, deadline - now)
        report("waiting", reason, wait_s=remaining,
               wait_until=wait_until, **(self._observation | details))
        return remaining

    def _wait_or_stop(self, image, reason: str, wait_s: float, **details) -> bool:
        if self._report_wait(reason, wait_s, **details) <= 0:
            self._stop_details.update(details)
            self._stop_snapshot(image, reason)
            return False
        self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
        return True

    def _stop_snapshot(self, image, reason: str) -> None:
        path = save_snapshot(image, self.settings.perception.snapshot_dir, tag=reason)
        self.result = LoopResult("stopped", reason)
        self._stop_details.update(snapshot=str(path) if path is not None else None)
        report("stopped", reason, **self._observation, **self._stop_details)

    @staticmethod
    def _wait(seconds: float) -> None:
        if current_session() is None:
            time.sleep(seconds)
            return
        remaining = max(0.0, seconds)
        while remaining > 0:
            checkpoint()
            step = min(0.1, remaining)
            time.sleep(step)
            remaining -= step
        checkpoint()

    def _execute(self, plan: ClickPlan | None) -> int:
        """执行点击计划，返回实际操作次数。

        `ClickPlan` 里的坐标是**设计坐标**，这里按当前帧的缩放系数换成设备像素。
        """
        if plan is None:
            return 0
        sc = self._scale
        self._readiness.reset()
        self._readiness_deadline = None

        if plan.drags:
            for (x1, y1), (x2, y2) in plan.drags:
                dx1, dy1 = sc.to_device(x1, y1)
                dx2, dy2 = sc.to_device(x2, y2)
                checkpoint()
                self.device.drag(dx1, dy1, dx2, dy2, plan.drag_hold_ms, plan.drag_ms)
                self._wait(plan.wait_ms / 1000)
            return len(plan.drags)

        if plan.drag and len(plan.points) == 2:
            (x1, y1), (x2, y2) = plan.points
            dx1, dy1 = sc.to_device(x1, y1)
            dx2, dy2 = sc.to_device(x2, y2)
            checkpoint()
            self.device.drag(dx1, dy1, dx2, dy2, plan.drag_hold_ms, plan.drag_ms)
            return 2

        for x, y in plan.points:
            checkpoint()
            self.device.tap(*sc.to_device(x, y))
            self._wait(plan.wait_ms / 1000)
        return len(plan.points)

    def _recover(self, state: GameState) -> bool:
        """按分级策略处理卡住。返回 False 表示应当停下。"""
        action = self.recovery.next_action()
        logger.warning(
            "recovery: {} (累计 {}/{})",
            action.value, self.recovery.attempts, self.recovery.total_limit,
        )

        if action is RecoveryAction.RETRY:
            # 上一次计划可能来自不同画面或动作；无法证明仍安全时停止。
            self.result = LoopResult("stopped", "recovery_unverified")
            report("stopped", self.result.reason)
            return False
        elif action in (RecoveryAction.RESTART_BATTLE, RecoveryAction.RESTART_CLIENT):
            if action is RecoveryAction.RESTART_BATTLE:
                # 退出对局要「投降 / 离开」界面的模板，现在还没有（issue #2）。
                logger.warning("recovery: 没有投降界面模板，restart_battle 退化为重启客户端")
            if not self.settings.recovery.allow_client_restart:
                # 重启会掉登录态（Riot 登入页），而自动登录还没做。
                # 状态不明不点击 → 停下等人，而不是把卡住升级成要人工登录。
                logger.error(
                    "recovery: 重启客户端会掉登录态，未开启 recovery.allow_client_restart；停止主循环"
                )
                self.result = LoopResult("stopped", "recovery_disabled")
                report("stopped", self.result.reason)
                return False
            self._restart_client()
        else:
            logger.error("recovery: 已耗尽，停止主循环（{}）", state.summary())
            self.result = LoopResult("stopped", "recovery_exhausted")
            report("stopped", self.result.reason)
            return False

        self.watchdog.reset()
        return True

    def _restart_client(self) -> None:
        package = self.settings.adb.package
        logger.warning("recovery: 重启客户端 {}", package)
        checkpoint()
        self.device.restart_app(package)

    def _build_state(self, image) -> GameState:
        return self.parser.parse(image)
