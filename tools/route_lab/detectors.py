"""路线识别实验的候选检测器。

不改运行时；这里的每个 detect_* 都是对同一问题（「当前节点能走到哪些节点」）
的一种独立判据，便于在同一批实拍帧 + 对抗变体上横向比较。

判据清单：
  halo      —— 可走节点自带的高亮白环（游戏自己的 affordance）
  line      —— 从当前节点出发的连续亮线（连通域）
  ring      —— 节点圆环 + 图标纹理（旧 detect_nodes 思路）
  组合      —— halo ∧ line（本实验主推）
"""

from __future__ import annotations

import math

import cv2
import numpy as np

MAP_BOX = (240, 60, 1750, 1000)  # x0, y0, x1, y1：地图主体，排除侧栏/顶栏
HALO_RADII = (40, 48, 56)
HALO_MIN_SCORE = 0.30


def white_blue_mask(image: np.ndarray) -> np.ndarray:
    """白青高亮：可走节点环与亮线共用的颜色族。"""
    b = image[:, :, 0].astype(int)
    g = image[:, :, 1].astype(int)
    r = image[:, :, 2].astype(int)
    return ((b > 200) & (g > 170) & (b - r > 25)).astype(np.uint8)


def glow_mask(image: np.ndarray) -> np.ndarray:
    b = image[:, :, 0].astype(int)
    g = image[:, :, 1].astype(int)
    r = image[:, :, 2].astype(int)
    return ((np.minimum(b, g) > 200) & (r > 170)).astype(np.uint8)


def _in_map(x: int, y: int) -> bool:
    x0, y0, x1, y1 = MAP_BOX
    return x0 <= x <= x1 and y0 <= y <= y1


def ring_whiteness(mask: np.ndarray, center: tuple[int, int], radius: int,
                   step_deg: int = 3) -> float:
    cx, cy = center
    hits = total = 0
    for deg in range(0, 360, step_deg):
        rad = math.radians(deg)
        x = int(cx + math.cos(rad) * radius)
        y = int(cy + math.sin(rad) * radius)
        if 0 <= x < mask.shape[1] and 0 <= y < mask.shape[0]:
            total += 1
            hits += int(mask[y, x] > 0)
    return hits / max(total, 1)


def halo_score(image: np.ndarray, center: tuple[int, int]) -> float:
    return max(ring_whiteness(white_blue_mask(image), center, r) for r in HALO_RADII)


def _center_is_node_icon(image: np.ndarray, center: tuple[int, int]) -> bool:
    """环内要有真实图标纹理：纯色遮挡（雾、面板、灰块）过不了。"""
    x, y = center
    inner = image[max(0, y - 22):y + 23, max(0, x - 22):x + 23]
    if inner.size == 0:
        return False
    gray = cv2.cvtColor(inner, cv2.COLOR_BGR2GRAY)
    if float(gray.std()) < 10.0:
        return False
    hsv = cv2.cvtColor(inner, cv2.COLOR_BGR2HSV)
    dark = cv2.inRange(hsv, (0, 0, 0), (180, 255, 60))
    return int(cv2.countNonZero(dark)) >= 60


def _has_green_completion(image: np.ndarray, center: tuple[int, int]) -> bool:
    x, y = center
    region = image[max(0, y - 30):y + 31, max(0, x - 30):x + 31]
    if region.size == 0:
        return False
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    green = cv2.inRange(hsv, (35, 95, 130), (85, 255, 255))
    return int(cv2.countNonZero(green)) >= 100


def detect_halos(image: np.ndarray) -> list[dict]:
    """自带白环的高亮节点候选（不依赖线）。"""
    mask = white_blue_mask(image)
    closed = cv2.morphologyEx(mask * 255, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(closed, connectivity=8)
    out: list[dict] = []
    for i in range(1, count):
        x, y, w, h, area = stats[i]
        cx, cy = int(centroids[i][0]), int(centroids[i][1])
        if area < 700 or not (55 <= w <= 190 and 55 <= h <= 190):
            continue
        if not (0.55 <= w / max(h, 1) <= 1.8) or not _in_map(cx, cy):
            continue
        score = halo_score(image, (cx, cy))
        if score < HALO_MIN_SCORE:
            continue
        out.append({"center": (cx, cy), "halo": round(score, 3), "area": int(area),
                    "bbox": (int(x), int(y), int(w), int(h))})
    out.sort(key=lambda d: -d["halo"])
    deduped: list[dict] = []
    for cand in out:
        if all((cand["center"][0] - o["center"][0]) ** 2 + (cand["center"][1] - o["center"][1]) ** 2
               > 45 ** 2 for o in deduped):
            deduped.append(cand)
    return deduped


def line_components(mask: np.ndarray, min_area: int = 300, close: int = 0):
    glow = (mask * 255).astype(np.uint8)
    if close > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close, close))
        glow = cv2.morphologyEx(glow, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(glow, connectivity=8)
    comps = []
    for i in range(1, count):
        if stats[i][4] >= min_area:
            comps.append((i, labels, int(stats[i][4])))
    comps.sort(key=lambda c: -c[2])
    return comps


def touches(labels: np.ndarray, cid: int, center: tuple[int, int], radius: int) -> bool:
    x, y = center
    x0, y0 = max(0, x - radius), max(0, y - radius)
    x1, y1 = min(labels.shape[1], x + radius + 1), min(labels.shape[0], y + radius + 1)
    return bool((labels[y0:y1, x0:x1] == cid).any())


def connected_along_line(image: np.ndarray, src: tuple[int, int], dst: tuple[int, int],
                         *, src_r: int = 85, dst_r: int = 60, close: int = 0,
                         min_area: int = 300) -> dict | None:
    """src 与 dst 是否被同一条亮线连通。"""
    for cid, labels, area in line_components(glow_mask(image), min_area, close):
        if touches(labels, cid, src, src_r) and touches(labels, cid, dst, dst_r):
            return {"component": cid, "area": area, "close": close}
    return None


def detect_routes_halo_line(image: np.ndarray, current: tuple[int, int],
                            *, halo_min: float = HALO_MIN_SCORE,
                            line_close: int = 0) -> list[dict]:
    """主推方案：可走白环 ∧ 与当前节点连续亮线 ∧ 未完成。"""
    routes = []
    for cand in detect_halos(image):
        center = cand["center"]
        if (center[0] - current[0]) ** 2 + (center[1] - current[1]) ** 2 < 120 ** 2:
            continue
        if cand["halo"] < halo_min:
            continue
        if _has_green_completion(image, center) or not _center_is_node_icon(image, center):
            continue
        link = connected_along_line(image, current, center, close=line_close)
        if link is None:
            continue
        routes.append({**cand, "link": link})
    return routes


def detect_routes_halo_only(image: np.ndarray, current: tuple[int, int]) -> list[dict]:
    routes = []
    for cand in detect_halos(image):
        center = cand["center"]
        if (center[0] - current[0]) ** 2 + (center[1] - current[1]) ** 2 < 120 ** 2:
            continue
        if _has_green_completion(image, center) or not _center_is_node_icon(image, center):
            continue
        routes.append(cand)
    return routes


def detect_routes_line_only(image: np.ndarray, current: tuple[int, int]) -> list[dict]:
    """只按亮线连通：端点用低阈值 Hough 找圆，不看白环。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)
    found = cv2.HoughCircles(blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=40,
                             param1=100, param2=20, minRadius=15, maxRadius=70)
    circles = [(int(x), int(y), int(r)) for x, y, r in (found[0] if found is not None else [])
               if _in_map(int(x), int(y))]
    routes = []
    for cid, labels, area in line_components(glow_mask(image)):
        if not touches(labels, cid, current, 85):
            continue
        for x, y, r in circles:
            if (x - current[0]) ** 2 + (y - current[1]) ** 2 < 120 ** 2:
                continue
            if not touches(labels, cid, (x, y), max(r, 45) + 15):
                continue
            if _has_green_completion(image, (x, y)):
                continue
            routes.append({"center": (x, y), "radius": r, "area": area, "halo": None})
    return routes
