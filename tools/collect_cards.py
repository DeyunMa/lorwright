"""半自动采集卡牌模板。

用法（在 Windows 上、游戏开着时）：
    python tools/collect_cards.py

流程：
  1. 截一帧
  2. 你用鼠标框选一张手牌（或用固定网格）
  3. 输入卡牌 id
  4. 保存到 assets/cards/<id>.png

当前是占位实现：先保存整帧，人工用图像工具裁剪。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from lorwright.perceive.capture import ScreenCapture


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="logs/collect")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    args = ap.parse_args()

    cap = ScreenCapture(args.width, args.height)
    frame = cap.grab().frame
    cap.close()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "frame.png"
    cv2.imwrite(str(path), frame)
    print(f"已保存整帧: {path}")
    print("下一步：用截图工具裁出手牌卡面，存到 assets/cards/<card_id>.png")


if __name__ == "__main__":
    main()
