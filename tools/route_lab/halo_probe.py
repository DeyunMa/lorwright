"""探测「可选节点白环」的像素特征：先量再定判据。

只读实验工具。用法：.venv/bin/python tools/route_lab/halo_probe.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lorwright.core.perceive import mapnav  # noqa: E402

CASES = [
    ("mapnav/f1-healer-route-20261113.jpg", "T-healer", (1173, 521)),
    ("mapnav/f1-before-healer-1080.png", "T-healer", (1180, 600)),
    ("healer/f1-after-heal.png", "T-portal", (1165, 438)),
    ("healer/f1-after-heal.png", "C-healer-done", (963, 540)),
    ("mapnav/1080p_jinx_fork_after_support.png", "T-upper", (1141, 513)),
    ("mapnav/1080p_jinx_fork_after_support.png", "T-lower", (1044, 841)),
    ("mapnav/1080p_jinx_fork_after_support.png", "P-healer", (1355, 600)),
    ("mapnav/1080p_jinx_fork_after_support.png", "P-shop", (1145, 1000)),
    ("mapnav/1080p_jinx_fork_after_support.png", "P-locked", (1573, 505)),
    ("mapnav/1080p_zoommax.png", "T-next", (1189, 370)),
    ("mapnav/1080p_zoommax.png", "C-current", (1011, 507)),
    ("mapnav/1080p_zoommax.png", "P-healer", (1327, 262)),
    ("mapnav/1080p_map.png", "T-next", (1252, 322)),
    ("mapnav/1080p_jinx_map.png", "T-next", (982, 334)),
    ("mapnav/1080p_jinx_support_map.jpg", "C-diamond", (960, 413)),
    ("mapnav/1080p_jinx_support_map.jpg", "P-ability", (472, 399)),
]


def white_blue(image):
    b = image[:, :, 0].astype(int)
    g = image[:, :, 1].astype(int)
    r = image[:, :, 2].astype(int)
    return ((b > 200) & (g > 170) & (b - r > 25)).astype(np.uint8)


def ring_profile(center, mask, radii=range(20, 96, 8)):
    cx, cy = center
    out = []
    for radius in radii:
        hits = total = 0
        for deg in range(0, 360, 3):
            rad = np.deg2rad(deg)
            x = int(cx + np.cos(rad) * radius)
            y = int(cy + np.sin(rad) * radius)
            if 0 <= x < mask.shape[1] and 0 <= y < mask.shape[0]:
                total += 1
                hits += int(mask[y, x] > 0)
        out.append((radius, hits / max(total, 1)))
    return out


def main():
    for name, label, center in CASES:
        path = ROOT / "tests" / "fixtures" / name
        image = cv2.imread(str(path))
        if image is None:
            print(name, "MISSING")
            continue
        mask = white_blue(image)
        prof = ring_profile(center, mask)
        y, x = center
        wb40 = int(mask[y - 40:y + 40, x - 40:x + 40].sum())
        glow40 = int(mapnav.glow_mask(image)[y - 40:y + 40, x - 40:x + 40].sum())
        line = " ".join("r" + str(r) + ":" + format(v, ".2f") for r, v in prof)
        print(name.split("/")[-1].ljust(34), label.ljust(14), str(center).ljust(12),
              "wb40=" + str(wb40).rjust(4), "glow40=" + str(glow40).rjust(4), line)


main()
