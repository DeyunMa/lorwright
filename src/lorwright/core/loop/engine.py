"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time
from dataclasses import asdict

from lorwright.core.act.translate import ActionTranslator
from lorwright.core.config import Settings
from lorwright.core.decide.discard import choose_discard
from lorwright.core.decide.router import Router
from lorwright.core.device.base import Device
from lorwright.core.loop.outcome import ActionOutcome, LoopResult, OutcomeStatus
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
    ) -> None:
        self._confirm_empty_hand_once = confirm_empty_hand_once
        self.settings = settings
        self.router = router
        self.device = device
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
        )
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self._scale = Scale(1.0, 1.0)
        self._skipped_stale = 0
        #: 连续多少帧读不出法力。0 费时法力数字会整段消失，需要靠这个
        #: 计数器区分「动画遮挡」和「真的没费」。
        self._unreadable_mana_frames = 0
        self._confirmed_zero_mana = False
        self._pending: ActionOutcome | None = None
        #: 待确认的出牌；出现确认按钮只表示还需输入，不算出牌已成功。
        self._staged_play: tuple[Action, GameState] | None = None
        self._wait_deadlines: dict[str, float] = {}
        self._observation: dict = {}
        self._stop_details: dict = {}

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
        inspecting_board = False
        self._wait_deadlines.clear()
        self._stop_details.clear()
        self.result = LoopResult("stopped", "tick_limit")
        self._confirmed_zero_mana = False
        self._unreadable_mana_frames = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                ticks += 1
                t0 = time.time()

                checkpoint()
                report("capture", tick=ticks)
                captured_at = time.time()
                frame = self.device.screencap()
                report("recognize", capture_ms=round((time.time() - captured_at) * 1000))
                recognition_started = time.time()
                image, self._scale = self.normalizer.fit(frame.image)
                state = self._build_state(image)
                age = frame.age_s()
                self._observation = dict(
                    tick=ticks, ui=state.ui_state.value, summary=state.summary(),
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
                    self._confirmed_zero_mana = False
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
                    self._skipped_stale += 1
                    self._report_wait("stale_frame", self.settings.loop.max_frame_age_s)
                    logger.warning(
                        "stale frame: age={:.2f}s > {:.2f}s，本轮不动作（累计 {}）",
                        age, self.settings.loop.max_frame_age_s, self._skipped_stale,
                    )
                    emit(
                        tick=ticks, ui=state.ui_state.value, layer="stale",
                        action="no_op", clicks=0, stuck=False,
                        ms=round((time.time() - t0) * 1000),
                    )
                    if self._pending is not None and time.monotonic() >= self._pending.deadline:
                        emit(
                            tick=ticks, event="action_outcome",
                            action=self._pending.action.type.value, status="timed_out",
                            reason="no_fresh_frame_before_deadline", clicks=0,
                        )
                        self._stop_snapshot(frame.image, "action_timeout")
                        break
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue

                # 奖励详情超时可能覆盖战斗画面；单次确认后只接受明确转场。
                timeout_button = reward_timeout_continue(image)
                if timeout_button is not None:
                    checkpoint()
                    self.device.tap(*self._scale.to_device(*timeout_button.center))
                    for _ in range(6):
                        self._report_wait("reward_timeout_transition", 12)
                        self._wait(2)
                        after = self.device.screencap()
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

                # 对局结束后由外层流程处理结果界面。
                if state.ui_state is UIState.BATTLE_END:
                    self._pending = None
                    self._staged_play = None
                    self.result = LoopResult("completed", "battle_end")
                    report("completed", "battle_end", progress=True)
                    break

                # 单次采样：选中后的行为尚未验证，采集新画面后立即停止。
                if state.ui_state is UIState.DISCARD:
                    candidates = discard_candidates(image, self.parser.digits)
                    if candidates is None:
                        self._stop_snapshot(frame.image, "discard_candidates_unverified")
                        break
                    action = choose_discard(candidates)
                    if action is None:
                        self._stop_snapshot(frame.image, "discard_cost_unverified")
                        break
                    point = candidates.cards[action.card_index].center
                    record_event("discard_sample", card_index=action.card_index,
                                 point=list(point), **action.raw)
                    checkpoint()
                    self.device.tap(*self._scale.to_device(*point))
                    self._wait(1.0)
                    sampled = self.device.screencap()
                    self._stop_snapshot(sampled.image, "discard_sample")
                    break

                # 已发送的输入先等新帧证明结果，不能每 tick 重放同一个手势。
                if self._pending is not None:
                    outcome = self._pending.observe(state, time.monotonic())
                    emit(
                        tick=ticks, event="action_outcome",
                        action=self._pending.action.type.value,
                        card_index=self._pending.action.card_index,
                        status=outcome.status.value, reason=outcome.reason, clicks=0,
                        before=self._pending.before.summary(), after=state.summary(),
                        readings={name: asdict(reading) for name, reading in state.readings.items()},
                    )
                    if outcome.status is OutcomeStatus.TIMED_OUT:
                        if (
                            self._pending.action.type in (ActionType.END_TURN, ActionType.PASS)
                            and state.ui_state is not UIState.UNKNOWN
                        ):
                            logger.warning(
                                "动作结果未确认但状态可读，继续观察：{}",
                                self._pending.action.type.value,
                            )
                            self._pending = None
                            self.watchdog.reset()
                            self.recovery.reset()
                        else:
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
                        self._staged_play = (self._pending.action, self._pending.before)
                    if outcome.status is OutcomeStatus.SUCCEEDED:
                        confirmed_play = False
                        if (self._staged_play is not None
                                and self._pending.action.type is ActionType.CONFIRM):
                            confirmed_play = ActionOutcome(
                                *self._staged_play, float("inf")
                            ).observe(state, time.monotonic()).status is OutcomeStatus.SUCCEEDED
                            if not confirmed_play:
                                # 确认按钮消失并不证明原来的牌已经打出，
                                # 避免策略把同一张火箭当成下一张再次尝试。
                                self._stop_snapshot(frame.image, "staged_play_unverified")
                                logger.warning("确认后无法核实原出牌结果，停止")
                                break
                        if self._pending.action.type is ActionType.COLLAPSE_HAND:
                            inspecting_board = True
                        self._wait_deadlines.clear()
                        report("verified", outcome.reason, progress=True,
                               action=self._pending.action.type.value)
                        for layer in self.router.layers:
                            callback = getattr(layer, "on_action_outcome", None)
                            if callback is not None:
                                callback(self._pending.action, self._pending.before, state)
                                if confirmed_play and self._staged_play is not None:
                                    callback(*self._staged_play, state)
                        if self._pending.action.type is ActionType.CONFIRM:
                            self._staged_play = None
                    self._pending = None
                    self.watchdog.reset()
                    self.recovery.reset()

                # 安全约束由执行入口保障，不能依赖每一个英雄包都正确弃权。
                if state.ui_state is UIState.UNKNOWN:
                    self._report_wait("unknown_ui", self.settings.loop.action_timeout_s)
                    emit(tick=ticks, layer="unknown", action="no_op", clicks=0)
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
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
                        self._report_wait("manual_empty_hand_conflict", self.settings.loop.action_timeout_s)
                        emit(tick=ticks, layer="manual_empty_hand_conflict", action="no_op", clicks=0)
                        self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                        continue

                # 法力/我方血量必须新鲜；敌方血量被特效遮住时不能卡住整局，
                # 它只影响斩杀判断，缺省时按保守策略处理。
                # 例外：0 费时法力数字常常整段消失（读不出来），但上一帧
                # 已经确认是 0；这时允许继续，否则会卡在 0 费永远结束不了回合。
                mana_reading = state.readings.get("mana")
                if mana_reading is not None and mana_reading.fresh:
                    self._unreadable_mana_frames = 0
                    self._confirmed_zero_mana = (
                        state.ui_state is UIState.MY_TURN_IDLE and mana_reading.value == 0
                    )
                elif state.ui_state is UIState.MY_TURN_IDLE:
                    self._unreadable_mana_frames += 1
                else:
                    self._unreadable_mana_frames = 0
                unreadable = [
                    name for name in ("mana", "nexus_hp")
                    if not (state.readings.get(name) and state.readings[name].fresh)
                ]
                zero_mana_stall = (
                    unreadable == ["mana"]
                    and self._unreadable_mana_frames >= 5
                    and state.ui_state is UIState.MY_TURN_IDLE
                    and self._confirmed_zero_mana
                )
                if zero_mana_stall:
                    # 同一优先权中已确认 0，之后连续 5 帧读不出：按 0 费处理，
                    # 让路由走结束回合，而不是整局卡死。
                    state.mana = 0
                    state.max_mana = 0
                # 空手且有攻击令牌时，攻击无需法力；仍要求我方血量新鲜，
                # 并在路由后只放行经确认的攻击动作。
                attack_without_mana = (
                    unreadable == ["mana"]
                    and state.ui_state is UIState.MY_TURN_IDLE
                    and state.hand_empty_confirmed and not state.hand
                    and state.has_attack_token and bool(state.my_units)
                )
                spell_mana_only = (
                    unreadable == ["mana"]
                    and state.ui_state is UIState.MY_TURN_IDLE
                    and state.has_fresh_readings("spell_mana")
                    and state.spell_mana is not None
                    and state.hand_expanded and bool(state.enemy_units)
                )
                if spell_mana_only:
                    # 未知普通法力按零处理；路由后仅允许明确使用法术法力的动作。
                    state.mana = 0
                if (
                    state.ui_state in (UIState.MY_TURN_IDLE, UIState.BLOCKING)
                    and unreadable and not zero_mana_stall and not attack_without_mana
                    and not spell_mana_only
                ):
                    self._report_wait("unreadable", self.settings.loop.action_timeout_s,
                                      missing_readings=unreadable)
                    emit(
                        tick=ticks, layer="unreadable", action="no_op", clicks=0,
                        readings={name: asdict(reading) for name, reading in state.readings.items()},
                    )
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue

                report("decide")
                decision_at = time.time()
                result = (self.router.decide(state, suppress_hand_expansion=True)
                          if inspecting_board else self.router.decide(state))
                if (not inspecting_board and state.ui_state is UIState.MY_TURN_IDLE
                        and state.hand_expanded and state.has_attack_token
                        and self.layout.collapse_hand_point is not None
                        and ((result.action.type is ActionType.NO_OP
                              and result.action.raw.get("inspect_board") is True)
                             or (result.layer == "fallback"
                                 and result.action.type is ActionType.END_TURN))):
                    result.action = Action(type=ActionType.COLLAPSE_HAND)
                    result.layer = "inspect_board"
                if state.ui_state is UIState.TARGETING and result.action.type is ActionType.NO_OP:
                    if target_wait_deadline is None:
                        target_wait_deadline = time.monotonic() + self.settings.loop.action_timeout_s
                    self._report_wait("unknown_target", max(0.0, target_wait_deadline - time.monotonic()))
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue
                target_wait_deadline = None
                if (manual_empty and (
                    result.action.type is not ActionType.ATTACK
                    or not state.has_attack_token or not state.my_units
                    or not (state.readings.get("nexus_hp") and state.readings["nexus_hp"].fresh)
                )) or (attack_without_mana and not zero_mana_stall and not spell_mana_only and (
                    result.action.type is not ActionType.ATTACK
                )) or (spell_mana_only and not zero_mana_stall and not (
                    result.action.type is ActionType.PLAY_CARD
                    and result.action.raw.get("spell_mana_only") is True
                    and any(card.index == result.action.card_index and card.drag_point_valid
                            and 0 <= card.cost <= state.spell_mana for card in state.hand)
                )):
                    self._report_wait("unreadable", self.settings.loop.action_timeout_s,
                                      missing_readings=unreadable)
                    emit(tick=ticks, layer="unreadable", action="no_op", clicks=0,
                         readings={name: asdict(reading) for name, reading in state.readings.items()})
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue
                self._observation.update(action=result.action.type.value, strategy=result.layer)
                report("decided", action=result.action.type.value, strategy=result.layer,
                       decision_ms=round((time.time() - decision_at) * 1000))
                # 网络决策也可能耗时；执行前必须再次确认这张图仍然新鲜。
                if frame.age_s() > self.settings.loop.max_frame_age_s:
                    self._skipped_stale += 1
                    self._report_wait("frame_expired_during_decision",
                                      self.settings.loop.max_frame_age_s)
                    emit(tick=ticks, layer="stale", action="no_op", clicks=0,
                         reason="frame_expired_during_decision")
                    self._wait(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue
                # NO_OP 不计入卡死：对手回合状态本来就不变
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
                    self._report_wait(
                        "action_result" if clicks else (
                            "enemy_turn" if state.ui_state is UIState.ENEMY_TURN else "no_action"
                        ),
                        60 if state.ui_state is UIState.ENEMY_TURN
                        else self.settings.loop.action_timeout_s,
                        execution_ms=round((time.time() - execution_at) * 1000),
                    )
                    if clicks and result.action.type is not ActionType.NO_OP:
                        self._confirmed_zero_mana = False
                        timeout = self.settings.loop.action_timeout_s
                        if (result.action.type is ActionType.CONFIRM
                                and (self._staged_play is not None
                                     or (state.ui_state is UIState.COMBAT_RESOLVING
                                         and result.layer == "combat_confirm"))):
                            # 法术和战斗确认后的结算动画可能超过普通动作观察窗口。
                            timeout = max(timeout, 20.0)
                        self._pending = ActionOutcome(
                            result.action, state, time.monotonic() + timeout,
                            combat_row_min_move_px=self.settings.loop.combat_row_min_move_px,
                        )

                elapsed_ms = round((time.time() - t0) * 1000)
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

    def _report_wait(self, reason: str, wait_s: float, **details) -> None:
        """重复帧沿用首次等待期限，不能靠轮询延后停滞判定。"""
        if current_session() is None:
            return
        now = time.time()
        deadline = self._wait_deadlines.setdefault(reason, now + wait_s)
        remaining = deadline - now
        report("waiting", reason, wait_s=remaining if remaining > 0 else None,
               wait_until=deadline, **(self._observation | details))

    def _stop_snapshot(self, image, reason: str) -> None:
        path = save_snapshot(image, self.settings.perception.snapshot_dir, tag=reason)
        self.result = LoopResult("stopped", reason)
        self._stop_details = dict(snapshot=str(path) if path is not None else None)
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
