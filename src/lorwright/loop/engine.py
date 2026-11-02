"""主循环：感知 → 决策 → 执行 → 异常处理。"""

from __future__ import annotations

import time

from lorwright.act.mouse import Mouse
from lorwright.config import Settings
from lorwright.decide.base import Policy
from lorwright.loop.watchdog import Watchdog
from lorwright.models import ActionType, GameState
from lorwright.perceive.capture import ScreenCapture
from lorwright.perceive.cards import CardLibrary
from lorwright.perceive.ui_state import UIStateDetector
from lorwright.util.logger import logger
from lorwright.util.snapshot import save_snapshot


class Engine:
    def __init__(
        self,
        settings: Settings,
        policy: Policy,
        capture: ScreenCapture | None = None,
        ui_detector: UIStateDetector | None = None,
        cards: CardLibrary | None = None,
        mouse: Mouse | None = None,
    ) -> None:
        self.settings = settings
        self.policy = policy
        self.capture = capture or ScreenCapture(settings.screen.width, settings.screen.height)
        self.ui_detector = ui_detector or UIStateDetector()
        self.cards = cards or CardLibrary()
        self.mouse = mouse or Mouse()
        self.watchdog = Watchdog(threshold=settings.loop.stuck_threshold)

    def run(self, max_ticks: int | None = None) -> None:
        self.ui_detector.load()
        self.cards.load()
        logger.info("engine started: policy={} cards={}", self.policy.name, len(self.cards))

        ticks = 0
        while max_ticks is None or ticks < max_ticks:
            ticks += 1
            t0 = time.time()

            shot = self.capture.grab()
            state = self._build_state(shot.frame)

            if self.watchdog.observe(state):
                logger.warning("stuck detected: {}", state.summary())
                save_snapshot(shot.frame, tag="stuck")
                self.watchdog.reset()

            action = self.policy.decide(state)
            if action is not None:
                logger.info("{} -> {}", state.summary(), action)
                self._execute(action, state)

            elapsed = (time.time() - t0) * 1000
            time.sleep(max(0.0, (self.settings.loop.tick_ms - elapsed) / 1000))

        self.capture.close()

    # ---- 内部 ----

    def _build_state(self, frame) -> GameState:
        ui = self.ui_detector.detect(frame)
        # TODO(T5): 从截图解析手牌、场面、法力、血量
        return GameState(ui_state=ui)

    def _execute(self, action, state: GameState) -> None:
        # TODO(T6/T7): 把语义动作翻译成点击坐标
        if action.type is ActionType.END_TURN:
            logger.info("TODO: click end-turn button")
        elif action.type is ActionType.PLAY_CARD:
            logger.info("TODO: click card #{}", action.card_index)
        elif action.type is ActionType.ATTACK:
            logger.info("TODO: drag attacker -> {}", action.target)
        else:
            logger.debug("action ignored: {}", action.type)
