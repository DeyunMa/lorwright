"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time

from lorwright.act.mouse import Mouse
from lorwright.act.translate import ActionTranslator, Layout
from lorwright.config import Settings
from lorwright.decide.router import Router
from lorwright.loop.watchdog import Watchdog
from lorwright.models import GameState
from lorwright.perceive.capture import ScreenCapture
from lorwright.perceive.cards import CardLibrary
from lorwright.perceive.ui_state import UIStateDetector
from lorwright.util.logger import logger
from lorwright.util.snapshot import save_snapshot


class Engine:
    def __init__(
        self,
        settings: Settings,
        router: Router,
        layout: Layout | None = None,
        capture: ScreenCapture | None = None,
        ui_detector: UIStateDetector | None = None,
        cards: CardLibrary | None = None,
        mouse: Mouse | None = None,
    ) -> None:
        self.settings = settings
        self.router = router
        self.layout = layout or Layout()
        self.capture = capture or ScreenCapture(settings.screen.width, settings.screen.height)
        self.ui_detector = ui_detector or UIStateDetector(
            threshold=settings.perception.match_threshold
        )
        self.cards = cards or CardLibrary()
        self.mouse = mouse or Mouse()
        self.translator = ActionTranslator(self.layout)
        self.watchdog = Watchdog(threshold=settings.loop.stuck_threshold)

    def run(self, max_ticks: int | None = None) -> None:
        self.ui_detector.load()
        self.cards.load()
        logger.info(
            "engine started: layers={} cards={} layout={}",
            [getattr(p, "name", type(p).__name__) for p in self.router.layers],
            len(self.cards),
            "ready" if self.layout.end_turn else "missing",
        )

        ticks = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                ticks += 1
                t0 = time.time()

                shot = self.capture.grab()
                state = self._build_state(shot.frame)

                if self.watchdog.observe(state):
                    logger.warning("stuck: {}", state.summary())
                    save_snapshot(shot.frame, self.settings.perception.snapshot_dir, tag="stuck")
                    self.watchdog.reset()

                result = self.router.decide(state)
                plan = self.translator.translate(result.action, state)

                if plan is None:
                    logger.debug("no plan for {} (layer={})", result.action.type, result.layer)
                else:
                    logger.info("{} [{}] -> {} pts", state.summary(), result.layer, len(plan.points))
                    for x, y in plan.points:
                        self.mouse.click(x, y)
                        time.sleep(plan.wait_ms / 1000)

                elapsed = (time.time() - t0) * 1000
                time.sleep(max(0.0, (self.settings.loop.tick_ms - elapsed) / 1000))
        finally:
            self.capture.close()
            logger.info("engine stopped: coverage={}", self.router.coverage())

    def _build_state(self, frame) -> GameState:
        ui = self.ui_detector.detect(frame)
        # TODO(T4): 从截图解析手牌、场面、法力、血量
        return GameState(ui_state=ui)
