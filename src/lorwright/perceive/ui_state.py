"""UI 状态机：颜色探针 + 按钮文字模板。

动作按钮（右侧圆形）在**三种**情况下都是同一块蓝色：
    略過        → 我方回合空闲，可以出牌
    略過格擋    → 对手在攻击，等我方声明格挡（**手牌拖不动**）
    結算        → 提交格挡 / 攻击声明
    選擇目標    → 已拖出一张需要选目标的牌（例如「擊殺1個友軍單位」），
                  这个状态下拖手牌没反应，必须先取消

只靠颜色分不出这三者。把「略過格擋」当成「我方回合」会让策略每帧都试着
出牌、每帧都失败，看起来像「拖拽没反应」——所以按钮文字必须参与判定。
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect, UIState
from lorwright.perceive.locate import exists, load_template

# OpenCV HSV：蓝色 H≈100-125
#: 按钮文字搜索区 = 按钮中段（圆形按钮上下是装饰，文字在中间一条）
TEXT_BAND = (0.18, 0.18, 1.36, 0.64)
#: 按钮文字模板的匹配阈值。三种文字互相区分度很高（实测 1.00 vs ≤0.50）
TEXT_MIN_SCORE = 0.75

BLUE_LO = (95, 120, 120)
BLUE_HI = (125, 255, 255)
MIN_BLUE_RATIO = 0.45


def blue_ratio(img: np.ndarray, rect: Rect) -> float:
    """矩形区域内「蓝色像素」占比。"""
    patch = img[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array(BLUE_LO), np.array(BLUE_HI))
    return float(mask.sum()) / 255.0 / (patch.shape[0] * patch.shape[1])


class UIStateDetector:
    """判断当前处于哪个界面。

    优先级：
      1. 模板匹配 mulligan → MULLIGAN（必须最先：它和动作按钮同位置同颜色）
      2. 模板匹配 victory/defeat → BATTLE_END
      3. 动作按钮文字 → 对应状态（文字优先，见下方注释）
      4. 动作按钮蓝色占比 → MY_TURN_IDLE
      5. 模板匹配 enemy_turn → ENEMY_TURN
      6. 都没有 → UNKNOWN
    """

    #: 动作按钮文字 → UI 状态
    ACTION_TEXTS = {
        "action_block": UIState.BLOCKING,
        "action_commit": UIState.COMBAT_RESOLVING,
        "action_confirm": UIState.COMBAT_RESOLVING,
        "action_pass": UIState.MY_TURN_IDLE,
        "action_target": UIState.TARGETING,
    }

    def __init__(
        self,
        root: str | Path = "assets/buttons",
        threshold: float = 0.85,
        action_button: Rect | None = None,
    ) -> None:
        self.root = Path(root)
        self.threshold = threshold
        self.action_button = action_button
        self._tpl: dict[str, np.ndarray] = {}
        self._text_tpl: dict[str, np.ndarray] = {}

    def load(self) -> None:
        self._tpl.clear()
        if not self.root.exists():
            return
        for png in self.root.glob("*.png"):
            if png.stem in self.ACTION_TEXTS:
                img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    self._text_tpl[png.stem] = img
                continue
            self._tpl[png.stem] = load_template(png)

    def action_text(self, frame: np.ndarray) -> UIState | None:
        """读动作按钮上的文字。认不出返回 None（调用方按颜色兜底）。"""
        if not self.action_button or not self._text_tpl:
            return None
        b = self.action_button
        dx, dy, kw, kh = TEXT_BAND
        area = Rect(
            b.x - int(b.w * (kw - 1) / 2),   # 水平居中放宽
            b.y + int(b.h * dy),
            int(b.w * kw),
            int(b.h * kh),
        )
        patch = frame[area.y : area.y + area.h, area.x : area.x + area.w]
        if patch.size == 0:
            return None
        gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)

        best: tuple[float, UIState] | None = None
        for name, tpl in self._text_tpl.items():
            if tpl.shape[0] > gray.shape[0] or tpl.shape[1] > gray.shape[1]:
                continue
            score = float(cv2.matchTemplate(gray, tpl, cv2.TM_CCOEFF_NORMED).max())
            if best is None or score > best[0]:
                best = (score, self.ACTION_TEXTS[name])
        if best is None or best[0] < TEXT_MIN_SCORE:
            return None
        return best[1]

    def detect(self, frame: np.ndarray) -> UIState:
        # 1. 起手换牌。它的「確定」按钮和动作按钮**同位置同颜色**
        #    （实测蓝色占比 0.89 vs 0.88），必须先判掉，
        #    否则开局第一帧就被当成「我方优先权」去点牌。
        if "mulligan" in self._tpl and exists(frame, self._tpl["mulligan"], self.threshold):
            return UIState.MULLIGAN

        # 2. 对局结束
        t = self._tpl
        if "victory" in t and exists(frame, t["victory"], self.threshold):
            return UIState.BATTLE_END
        if "defeat" in t and exists(frame, t["defeat"], self.threshold):
            return UIState.BATTLE_END

        # 3. 动作按钮：**先读文字，再看颜色**。
        #    「選擇目標」按钮是深色半透明的，蓝色占比只有 0.2 上下，
        #    先判颜色会把整个状态漏掉；文字模板区分度很高（实测 1.00 vs ≤0.51），
        #    先读文字更可靠，颜色只用来兜底「认不出字但按钮在」的情况。
        by_text = self.action_text(frame)
        if by_text is not None:
            return by_text

        if self.action_button and blue_ratio(frame, self.action_button) >= MIN_BLUE_RATIO:
            return UIState.MY_TURN_IDLE

        # 4. 对手回合
        if "enemy_turn" in t and exists(frame, t["enemy_turn"], self.threshold):
            return UIState.ENEMY_TURN

        return UIState.UNKNOWN
