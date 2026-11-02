"""卡牌识别：用手牌区域的卡面模板匹配。

第一版只支持「蜘蛛快攻」卡组（20-30 张），图库放在 assets/cards/。
文件名约定：<card_id>.png，例如 `spiderling.png`。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import CardInHand, Rect
from lorwright.perceive.locate import load_template


@dataclass
class CardTemplate:
    card_id: str
    name: str
    cost: int
    image: np.ndarray


class CardLibrary:
    """卡牌模板库。"""

    def __init__(self, root: str | Path = "assets/cards") -> None:
        self.root = Path(root)
        self._templates: list[CardTemplate] = []

    def load(self) -> None:
        self._templates.clear()
        if not self.root.exists():
            return
        for png in sorted(self.root.glob("*.png")):
            # 约定：文件名即 card_id，cost 从 metadata.txt 读取（可选）
            img = load_template(png)
            self._templates.append(
                CardTemplate(card_id=png.stem, name=png.stem, cost=-1, image=img)
            )

    def __len__(self) -> int:
        return len(self._templates)

    def recognize_hand(self, frame: np.ndarray, hand_roi: Rect, threshold: float = 0.85) -> list[CardInHand]:
        """在手牌区域识别卡牌。

        TODO(T3): 先定位手牌区域内的卡牌边界（边缘检测/固定间距），
                  再对每张卡做模板匹配；当前返回空列表。
        """
        _ = (frame, hand_roi, threshold)
        return []


def save_card_crop(frame: np.ndarray, rect: Rect, out_path: str | Path) -> None:
    """把手牌中的一张卡裁出来存成模板（供采集脚本使用）。"""
    crop = frame[rect.y : rect.y + rect.h, rect.x : rect.x + rect.w]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), crop)
