"""从真实手牌截图里采「徽章费用」字形（assets/digits/<digit>-hand1080.png）。

用法：
    python tools/build_hand_digits.py --image logs/x.png \
        --badge 1467,970=1 --badge 1564,930=0 --badge 1659,909=6 --tag hand1080

每个 `--badge` 是 `徽章圆心x,圆心y=费用`。工具走的是线上同一套抠图
（`perceive.hand.read_glyph`），所以采出来的原型和推理时的字形形态一致。

为什么要单独采一套：手牌徽章里的数字只有 ~20px 且随卡片倾斜，
和血量/法力那些直立大字形的渲染差异太大，混用会把 2 读成 1。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from lorwright.perceive.digits import GLYPH_SIZE
from lorwright.perceive.hand import read_glyph


def parse_badge(spec: str) -> tuple[tuple[int, int], int]:
    try:
        where, digit = spec.split("=", 1)
        x, y = (int(v) for v in where.split(","))
        return (x, y), int(digit)
    except ValueError as e:
        raise SystemExit(f"徽章格式应为 x,y=费用，收到：{spec}") from e


def main() -> None:
    ap = argparse.ArgumentParser(description="采手牌徽章费用字形")
    ap.add_argument("--image", required=True, help="截图路径")
    ap.add_argument("--badge", action="append", required=True, help="x,y=费用")
    ap.add_argument("--tag", default="hand1080", help="来源标识，同名重跑会覆盖")
    ap.add_argument("--out", default="assets/digits", help="输出目录")
    args = ap.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise SystemExit(f"读不到图：{args.image}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[int, int] = {}
    failed = 0
    for spec in args.badge:
        center, digit = parse_badge(spec)
        glyph = read_glyph(img, center)
        if glyph is None:
            print(f"[fail] {center} 抠不出字形（期望 {digit}）")
            failed += 1
            continue
        ink = int((glyph > 0.5).sum())
        if digit in saved and saved[digit] >= ink:
            continue
        cv2.imwrite(
            str(out_dir / f"{digit}-{args.tag}.png"),
            (glyph * 255).astype("uint8"),
        )
        saved[digit] = ink
        print(f"[ok] {digit}  {center}  {ink} px")

    print(f"字形：{''.join(str(d) for d in sorted(saved))}  →  {out_dir}")
    if failed:
        print(f"{failed} 个样本失败")
        raise SystemExit(1)

    for digit in saved:
        got = cv2.imread(str(out_dir / f"{digit}-{args.tag}.png")).shape[:2][::-1]
        if got != GLYPH_SIZE:
            print(f"{digit} 尺寸不对：{got}")
            raise SystemExit(1)


if __name__ == "__main__":
    main()
