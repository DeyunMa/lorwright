"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time

from lorwright.act.translate import ActionTranslator
from lorwright.config import Settings
from lorwright.decide.router import Router
from lorwright.device.base import Device
from lorwright.loop.watchdog import Watchdog
from lorwright.models import GameState, Layout
from lorwright.perceive.cards import CardLibrary
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
        cards: CardLibrary | None = None,
    ) -> None:
        self.settings = settings
        self.router = router
        self.device = device
        self.layout = layout or settings.layout.to_layout()
        self.ui_detector = ui_detector or UIStateDetector(
            threshold=settings.perception.match_threshold,
            action_button=self.layout.end_turn,
        )
        self.cards = cards or CardLibrary()
        self.translator = ActionTranslator(self.layout)
        self.watchdog = Watchdog(threshold=settings.loop.stuck_threshold)

    def run(self, max_ticks: int | None = None) -> None:
        self.ui_detector.load()
        self.cards.load()

        w, h = self.device.size()
        logger.info(
            "engine start: device={} size={}x{} layers={} cards={} layout={}",
            self.device.name, w, h,
            [getattr(p, "name", type(p).__name__) for p in self.router.layers],
            len(self.cards),
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

                stuck = self.watchdog.observe(state)
                if stuck:
                    logger.warning("stuck: {}", state.summary())
                    save_snapshot(frame.image, self.settings.perception.snapshot_dir, tag="stuck")

                result = self.router.decide(state)
                plan = self.translator.translate(result.action, state)

                clicks = 0
                if plan is not None:
                    if plan.drags:
                        for (x1, y1), (x2, y2) in plan.drags:
                            self.device.swipe(x1, y1, x2, y2, plan.drag_ms)
                            clicks += 1
                            time.sleep(plan.wait_ms / 1000)
                    elif plan.drag and len(plan.points) == 2:
                        (x1, y1), (x2, y2) = plan.points
                        self.device.swipe(x1, y1, x2, y2, plan.drag_ms)
                        clicks = len(plan.points)
                    else:
                        for x, y in plan.points:
                            self.device.tap(x, y)
                            time.sleep(plan.wait_ms / 1000)
                        clicks = len(plan.points)

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

    def _build_state(self, frame) -> GameState:
        ui = self.ui_detector.detect(frame)
        # TODO(#4): 从截图解析手牌、场面、法力、血量
        return GameState(ui_state=ui)
