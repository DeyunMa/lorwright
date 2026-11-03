"""从真实截图里采数字字形（assets/digits/）。

用法：
    python tools/build_digits.py \
        --sample logs/s6.png:145,262,60,26=30 \
        --sample logs/s6.png:147,433,60,26=50 \
        --sample logs/menu1.png:...=155753

每个 sample 是 `图片路径:x,y,w,h=期望文本`。工具会把矩形里的白色数字切成
单字形、按高度归一化、存成 `<digit>.png`。切出来的字形数和文本长度不一致时
直接报错——那说明矩形给错了，别让错位的样本污染模板库。

换字体/换分辨率后重跑一遍即可（docs/handoff.md §3.4）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2

from lorwright.models import Rect
from lorwright.perceive.digits import GLYPH_SIZE, segment_glyphs


def parse_sample(spec: str) -> tuple[Path, Rect, str]:
    try:
        where, text = spec.split("=", 1)
        path, coords = where.rsplit(":", 1)
        x, y, w, h = (int(v) for v in coords.split(","))
    except ValueError as e:
        raise SystemExit(f"样本格式应为 路径:x,y,w,h=文本，收到：{spec}") from e
    return Path(path), Rect(x, y, w, h), text.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description="采数字字形模板")
    ap.add_argument("--sample", action="append", required=True, help="图片路径:x,y,w,h=文本")
    ap.add_argument("--tag", required=True, help="字号/来源标识，如 hp720；同名重跑会覆盖")
    ap.add_argument("--out", default="assets/digits", help="输出目录")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, tuple[int, str]] = {}   # digit -> (像素面积, 来源)
    failed = 0

    for spec in args.sample:
        path, rect, text = parse_sample(spec)
        img = cv2.imread(str(path))
        if img is None:
            print(f"[skip] 读不到图：{path}")
            failed += 1
            continue

        glyphs = segment_glyphs(img, rect)
        if len(glyphs) != len(text):
            print(f"[fail] {path} {rect} 期望 {text!r}（{len(text)} 个字），切出 {len(glyphs)} 个")
            failed += 1
            continue

        for glyph, ch in zip(glyphs, text, strict=True):
            if not ch.isdigit():
                continue
            ink = int((glyph.image > 0.5).sum())
            prev = saved.get(ch)
            if prev and prev[0] >= ink:
                continue
            canvas = (glyph.image * 255).astype("uint8")
            cv2.imwrite(str(out_dir / f"{ch}-{args.tag}.png"), canvas)
            saved[ch] = (ink, f"{path.name}{rect}")

    print(f"字形：{''.join(sorted(saved))}  →  {out_dir}")
    for ch in sorted(saved):
        ink, src = saved[ch]
        print(f"  {ch}: {ink:4d} px  ({src})")
    if failed:
        print(f"{failed} 个样本失败")
        raise SystemExit(1)

    size = tuple(GLYPH_SIZE)
    bad = [
        ch for ch in saved
        if cv2.imread(str(out_dir / f"{ch}-{args.tag}.png")).shape[:2][::-1] != size
    ]
    if bad:
        print(f"字形尺寸不对：{bad}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
