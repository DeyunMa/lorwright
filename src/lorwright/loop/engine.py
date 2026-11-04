"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time

from lorwright.act.translate import ActionTranslator
from lorwright.config import Settings
from lorwright.decide.router import Router
from lorwright.device.base import Device
from lorwright.loop.recovery import RecoveryAction, RecoveryPolicy
from lorwright.loop.watchdog import Watchdog
from lorwright.models import ClickPlan, GameState, Layout
from lorwright.perceive.digits import DigitReader
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
        )
        self.watchdog = Watchdog(threshold=settings.loop.stuck_threshold)
        self.recovery = recovery or RecoveryPolicy()
        self.parser = StateParser(
            layout=self.layout,
            ui=self.ui_detector,
            digits=DigitReader(),
            threshold=settings.perception.match_threshold,
        )
        self._last_plan: ClickPlan | None = None

    def run(self, max_ticks: int | None = None) -> None:
        self.parser.load()

        w, h = self.device.size()
        logger.info(
            "engine start: device={} size={}x{} layers={} layout={}",
            self.device.name, w, h,
            [getattr(p, "name", type(p).__name__) for p in self.router.layers],
            "ready" if self.layout.end_turn else "NOT CALIBRATED",
        )
        if not self.layout.end_turn:
            logger.warning("layout 未标定，动作会被跳过。先跑 `lorwright shot` 量坐标。")

        ticks = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                ticks += 1
                t0 = time.time()

                frame = self.device.screencap()
                state = self._build_state(frame.image)

                result = self.router.decide(state)
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

                elapsed_ms = round((time.time() - t0) * 1000)
                emit(
                    tick=ticks,
                    ui=state.ui_state.value,
                    layer=result.layer,
                    action=result.action.type.value,
                    clicks=clicks,
                    stuck=stuck,
                    ms=elapsed_ms,
                )

                time.sleep(max(0.0, (self.settings.loop.tick_ms - elapsed_ms) / 1000))
        finally:
            self.device.close()
            logger.info("engine stop: coverage={}", self.router.coverage())

    def _execute(self, plan: ClickPlan | None) -> int:
        """执行点击计划，返回实际操作次数。"""
        if plan is None:
            return 0
        self._last_plan = plan

        if plan.drags:
            for (x1, y1), (x2, y2) in plan.drags:
                self.device.drag(x1, y1, x2, y2, plan.drag_hold_ms, plan.drag_ms)
                time.sleep(plan.wait_ms / 1000)
            return len(plan.drags)

        if plan.drag and len(plan.points) == 2:
            (x1, y1), (x2, y2) = plan.points
            self.device.drag(x1, y1, x2, y2, plan.drag_hold_ms, plan.drag_ms)
            return 2

        for x, y in plan.points:
            self.device.tap(x, y)
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
