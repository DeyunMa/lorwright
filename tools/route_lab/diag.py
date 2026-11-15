"""路线识别实验的取证脚本：把每张地图帧的判据摊开。

只读实验工具，不参与运行时，也不修改 `perceive/mapnav.py`。
用法：`.venv/bin/python tools/route_lab/diag.py [关键字]`
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from lorwright.core.champions.jinx.vision import recognize_hero  # noqa: E402
from lorwright.core.perceive import mapnav  # noqa: E402

FIXTURE_DIRS = (
    ROOT / "tests" / "fixtures" / "mapnav",
    ROOT / "tests" / "fixtures" / "healer",
)


def largest_glow_components(mask, limit=5):
    glow = (mask * 255).astype(np.uint8)
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(glow, connectivity=8)
    rows = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        rows.append((int(area), (int(x), int(y), int(w), int(h)),
                     (int(centroids[i][0]), int(centroids[i][1])), i))
    rows.sort(key=lambda r: -r[0])
    return rows[:limit], labels


def describe(name, image):
    hero = recognize_hero(image)
    glow = mapnav.glow_mask(image)
    print(f"\n=== {name} ===")
    print(f"  shape={image.shape} glow_px={int(glow.sum())} panel_open={mapnav.panel_open(image)}")
    print(f"  hero={hero}")
    print("  detect_nodes=", [(n.x, n.y, n.radius) for n in mapnav.detect_nodes(image)])
    print("  ability_nodes=", [(n.x, n.y, n.radius) for n in mapnav.detect_ability_nodes(image)])
    rows, labels = largest_glow_components(glow)
    for area, bbox, centroid, cid in rows:
        line = f"    comp area={area:6d} bbox={bbox} centroid={centroid}"
        if hero:
            hx, hy = hero
            near = int(labels[max(0, hy - 4):hy + 5, max(0, hx - 4):hx + 5].max())
            contour = cv2.findContours((labels == cid).astype(np.uint8) * 255,
                                       cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
            dist = cv2.pointPolygonTest(contour[0], (float(hx), float(hy)), True) if contour else None
            line += f" hero_label={near}{'(same)' if near == cid else ''} dist_to_hero={round(dist, 1)}"
        print(line)
    if hero:
        lit = mapnav._lit_routes_from_ability(image, hero, glow)
        print("  lit_routes_from_ability=", None if lit is None else [(n.x, n.y, n.radius) for n in lit])
        print("  current_completed_visible=", mapnav._current_completed_node_visible(image, hero))
        print("  current_halo_visible=", mapnav._current_node_halo_visible(image, hero))
        reach = mapnav._reachable_nodes(image, mapnav.MapNode(*hero, 60), mapnav.detect_nodes(image), glow)
        print("  reachable_nodes=", [(n.x, n.y, n.radius) for n in reach])
        nxt = mapnav.next_node(image, hero=hero)
        by_path = mapnav.next_node_by_path(image, hero=hero)
        print("  next_node=", None if nxt is None else (nxt.x, nxt.y, nxt.radius))
        print("  next_node_by_path=", None if by_path is None else (by_path.x, by_path.y, by_path.radius))


def main():
    keyword = sys.argv[1] if len(sys.argv) > 1 else ""
    for folder in FIXTURE_DIRS:
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in {".png", ".jpg"} or keyword not in path.name:
                continue
            image = cv2.imread(str(path))
            if image is None:
                print(f"\n=== {path.name} === UNREADABLE")
                continue
            describe(f"{path.parent.name}/{path.name}", image)


main()
