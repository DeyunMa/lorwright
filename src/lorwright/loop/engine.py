"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time
from dataclasses import asdict

from lorwright.act.translate import ActionTranslator
from lorwright.config import Settings
from lorwright.decide.router import Router
from lorwright.device.base import Device
from lorwright.loop.outcome import ActionOutcome, OutcomeStatus
from lorwright.loop.recovery import RecoveryAction, RecoveryPolicy
from lorwright.loop.watchdog import Watchdog
from lorwright.models import ActionType, ClickPlan, GameState, Layout, UIState
from lorwright.perceive.digits import DigitReader
from lorwright.perceive.normalize import Normalizer, Scale
from lorwright.perceive.state import StateParser
from lorwright.perceive.ui_state import UIStateDetector
from lorwright.util.events import emit
from lorwright.util.logger import logger
from lorwright.util.snapshot import save_snapshot


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
    ) -> None:
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
        )
        self._last_plan: ClickPlan | None = None
        self.normalizer = Normalizer((settings.screen.width, settings.screen.height))
        self._scale = Scale(1.0, 1.0)
        self._skipped_stale = 0
        #: 连续多少帧读不出法力。0 费时法力数字会整段消失，需要靠这个
        #: 计数器区分「动画遮挡」和「真的没费」。
        self._unreadable_mana_frames = 0
        self._confirmed_zero_mana = False
        self._pending: ActionOutcome | None = None

    def run(self, max_ticks: int | None = None) -> None:
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
        self._confirmed_zero_mana = False
        self._unreadable_mana_frames = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                ticks += 1
                t0 = time.time()

                frame = self.device.screencap()
                image, self._scale = self.normalizer.fit(frame.image)
                state = self._build_state(image)
                if state.ui_state is not UIState.MY_TURN_IDLE:
                    self._confirmed_zero_mana = False

                # 帧时效：截图 + 识别 + 决策如果已经花了太久，画面可能早变了。
                # 拿旧帧去点就是「状态不明还点」，宁可这一轮什么都不做。
                age = frame.age_s()
                if age > self.settings.loop.max_frame_age_s:
                    self._skipped_stale += 1
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
                        save_snapshot(frame.image, self.settings.perception.snapshot_dir, tag="action_timeout")
                        break
                    time.sleep(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue

                # 已发送的输入先等新帧证明结果，不能每 tick 重放同一个手势。
                if self._pending is not None:
                    outcome = self._pending.observe(state, time.monotonic())
                    emit(
                        tick=ticks, event="action_outcome",
                        action=self._pending.action.type.value,
                        status=outcome.status.value, reason=outcome.reason, clicks=0,
                        before=self._pending.before.summary(), after=state.summary(),
                        readings={name: asdict(reading) for name, reading in state.readings.items()},
                    )
                    if outcome.status is OutcomeStatus.TIMED_OUT:
                        save_snapshot(
                            frame.image, self.settings.perception.snapshot_dir,
                            tag="action_timeout",
                        )
                        logger.error("动作结果未确认，停止主循环：{}", self._pending.action.type.value)
                        break
                    if outcome.status is OutcomeStatus.WAITING:
                        time.sleep(max(0.0, self.settings.loop.tick_ms / 1000))
                        continue
                    if outcome.status is OutcomeStatus.SUCCEEDED:
                        for layer in self.router.layers:
                            callback = getattr(layer, "on_action_outcome", None)
                            if callback is not None:
                                callback(self._pending.action, self._pending.before, state)
                    self._pending = None
                    self.watchdog.reset()
                    self.recovery.reset()

                # 安全约束由执行入口保障，不能依赖每一个英雄包都正确弃权。
                if state.ui_state is UIState.UNKNOWN:
                    emit(tick=ticks, layer="unknown", action="no_op", clicks=0)
                    time.sleep(max(0.0, self.settings.loop.tick_ms / 1000))
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
                if (
                    state.ui_state in (UIState.MY_TURN_IDLE, UIState.BLOCKING)
                    and unreadable and not zero_mana_stall
                ):
                    emit(
                        tick=ticks, layer="unreadable", action="no_op", clicks=0,
                        readings={name: asdict(reading) for name, reading in state.readings.items()},
                    )
                    time.sleep(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue

                result = self.router.decide(state)
                # 网络决策也可能耗时；执行前必须再次确认这张图仍然新鲜。
                if frame.age_s() > self.settings.loop.max_frame_age_s:
                    self._skipped_stale += 1
                    emit(tick=ticks, layer="stale", action="no_op", clicks=0,
                         reason="frame_expired_during_decision")
                    time.sleep(max(0.0, self.settings.loop.tick_ms / 1000))
                    continue
                # NO_OP 不计入卡死：对手回合状态本来就不变
                stuck = self.watchdog.observe(state, result.action.type)
                if self.watchdog.progressed:
                    self.recovery.reset()

                clicks = 0
                if stuck:
                    logger.warning("stuck: {}", state.summary())
                    save_snapshot(
                        frame.image, self.settings.perception.snapshot_dir, tag="stuck"
                    )
                    if not self._recover(state):
                        break
                else:
                    clicks = self._execute(self.translator.translate(result.action, state))
                    if clicks and result.action.type is not ActionType.NO_OP:
                        self._confirmed_zero_mana = False
                        self._pending = ActionOutcome(
                            result.action, state,
                            time.monotonic() + self.settings.loop.action_timeout_s,
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

                time.sleep(max(0.0, (self.settings.loop.tick_ms - elapsed_ms) / 1000))
        finally:
            self.device.close()
            logger.info("engine stop: coverage={}", self.router.coverage())

    def _execute(self, plan: ClickPlan | None) -> int:
        """执行点击计划，返回实际操作次数。

        `ClickPlan` 里的坐标是**设计坐标**，这里按当前帧的缩放系数换成设备像素。
        """
        if plan is None:
            return 0
        self._last_plan = plan
        sc = self._scale

        if plan.drags:
            for (x1, y1), (x2, y2) in plan.drags:
                dx1, dy1 = sc.to_device(x1, y1)
                dx2, dy2 = sc.to_device(x2, y2)
                self.device.drag(dx1, dy1, dx2, dy2, plan.drag_hold_ms, plan.drag_ms)
                time.sleep(plan.wait_ms / 1000)
            return len(plan.drags)

        if plan.drag and len(plan.points) == 2:
            (x1, y1), (x2, y2) = plan.points
            dx1, dy1 = sc.to_device(x1, y1)
            dx2, dy2 = sc.to_device(x2, y2)
            self.device.drag(dx1, dy1, dx2, dy2, plan.drag_hold_ms, plan.drag_ms)
            return 2

        for x, y in plan.points:
            self.device.tap(*sc.to_device(x, y))
            time.sleep(plan.wait_ms / 1000)
        return len(plan.points)

    def _recover(self, state: GameState) -> bool:
        """按分级策略处理卡住。返回 False 表示应当停下。"""
        action = self.recovery.next_action()
        logger.warning(
            "recovery: {} (累计 {}/{})",
            action.value, self.recovery.attempts, self.recovery.total_limit,
        )

        if action is RecoveryAction.RETRY:
            self._execute(self._last_plan)
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
                return False
            self._restart_client()
        else:
            logger.error("recovery: 已耗尽，停止主循环（{}）", state.summary())
            return False

        self.watchdog.reset()
        return True

    def _restart_client(self) -> None:
        package = self.settings.adb.package
        logger.warning("recovery: 重启客户端 {}", package)
        self.device.restart_app(package)

    def _build_state(self, image) -> GameState:
        return self.parser.parse(image)
