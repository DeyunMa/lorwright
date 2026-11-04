"""从真实截图里采「动作按钮」的文字模板（略過 / 略過格擋 / 結算）。

动作按钮的颜色和位置固定，但文字会变：略過 = 我方回合空闲，略過格擋 = 对手
在攻击、等我方声明格挡，結算 = 提交格挡/攻击。三者都是同一块蓝色按钮，
**只靠颜色区分不出来**，而把「略過格擋」当成「我的回合」会让策略每帧都
试着出牌，每帧都失败（手牌在格挡阶段根本拖不动）。

用法：
    python tools/build_action_texts.py --image logs/x.png --kind block
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

#: 动作按钮所在的搜索区（1920×1080 标定）
SEARCH = (1660, 495, 180, 85)


def white_text_box(img: np.ndarray, search: tuple[int, int, int, int], pad: int = 6):
    """按钮里的白字外框。蓝底上只有文字是「三通道都亮」。"""
    x, y, w, h = search
    patch = img[y : y + h, x : x + w]
    mask = ((patch.min(axis=2) >= 200) * 255).astype(np.uint8)
    ys, xs = np.where(mask > 0)
    if len(xs) == 0:
        return None
    x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
    y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
    return x + x0, y + y0, x1 - x0, y1 - y0


def main() -> None:
    ap = argparse.ArgumentParser(description="采动作按钮文字模板")
    ap.add_argument("--image", required=True, help="截图路径")
    ap.add_argument("--kind", required=True, choices=["pass", "block", "commit"])
    ap.add_argument("--out", default="assets/buttons")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"读不到图：{args.image}")
    box = white_text_box(img, SEARCH)
    if box is None:
        raise SystemExit("按钮里没找到白字")
    x, y, w, h = box
    crop = img[y : y + h, x : x + w]
    out = Path(args.out) / f"action_{args.kind}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), crop)
    print(f"[ok] {out}  {w}x{h}  @({x},{y})")


if __name__ == "__main__":
    main()
