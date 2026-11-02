"""模板匹配：用合成图像验证，不依赖游戏。"""

import cv2
import numpy as np

from lorwright.perceive.locate import find_all, find_one


def _frame_with_block(x=100, y=120, size=40):
    frame = np.zeros((300, 400, 3), np.uint8)
    cv2.rectangle(frame, (x, y), (x + size - 1, y + size - 1), (0, 255, 0), -1)
    # 加一点噪声，避免完全均匀
    frame += np.random.randint(0, 10, frame.shape, dtype=np.uint8)
    tpl = frame[y : y + size, x : x + size].copy()
    return frame, tpl


def test_find_one_hits_exact_position() -> None:
    frame, tpl = _frame_with_block()
    hit = find_one(frame, tpl, threshold=0.9)
    assert hit is not None
    rect, score = hit
    assert (rect.x, rect.y) == (100, 120)
    assert score > 0.99


def test_find_one_returns_none_when_absent() -> None:
    frame = np.zeros((100, 100, 3), np.uint8)
    tpl = np.full((20, 20, 3), 255, np.uint8)
    assert find_one(frame, tpl, threshold=0.9) is None


def test_find_all_dedups_overlapping_matches() -> None:
    frame, tpl = _frame_with_block()
    hits = find_all(frame, tpl, threshold=0.8)
    # 同一个目标不应返回多个重叠框
    assert len(hits) == 1
