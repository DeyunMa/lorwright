"""對局外地圖感知：英雄固定在畫面中心，沿發光線找下一個節點。

坐標空間：**1920×1080 設計尺寸**。模擬器原生 1280×720 由
`perceive/normalize.py` 歸一化；地圖不再使用 960×540 分析空間，
`AdventureLoop` 也不再做縮半/×2 換算。

地圖上的可走路徑是發光的淺藍白線（高亮、帶人字紋），
在亮度閾值下非常容易分離；節點是帶亮環的圓圈。
用戶規則：英雄節點到下一個節點只有一條線就走它，
分叉多條就隨機選一條。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import cv2
import numpy as np

from lorwright.models import Rect

__all__ = [
    "MapNode",
    "center_hero",
    "detect_ability_nodes",
    "detect_nodes",
    "empty_point",
    "glow_mask",
    "hero_node",
    "next_node",
    "next_node_by_path",
    "panel_open",
]


@dataclass(frozen=True)
class MapNode:
    x: int
    y: int
    radius: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x, self.y)

    def rect(self, margin: int = 20) -> Rect:
        return Rect(self.x - self.radius - margin, self.y - self.radius - margin,
                    2 * (self.radius + margin), 2 * (self.radius + margin))


def center_hero(image: np.ndarray) -> MapNode:
    """1080p 地圖鏡頭以英雄為中心；英雄節點就是畫面正中心。"""
    return MapNode(image.shape[1] // 2, image.shape[0] // 2, 60)


def hero_node(image: np.ndarray, nodes: list[MapNode] | None = None) -> MapNode:
    """当前英雄节点：离画面中心最近的真实节点；没有就退回中心。"""
    if nodes is None:
        nodes = detect_nodes(image)
    cx, cy = image.shape[1] // 2, image.shape[0] // 2
    if not nodes:
        return MapNode(cx, cy, 60)
    return min(nodes, key=lambda n: (n.x - cx) ** 2 + (n.y - cy) ** 2)


def glow_mask(image: np.ndarray) -> np.ndarray:
    """發光淺藍白線的二值掩碼。輸入為 BGR 圖。"""
    b = image[:, :, 0].astype(int)
    g = image[:, :, 1].astype(int)
    r = image[:, :, 2].astype(int)
    return ((np.minimum(b, g) > 200) & (r > 170)).astype(np.uint8)


def blue_glow_mask(image: np.ndarray) -> np.ndarray:
    """藍色發光（節點環/面板藍色 UI）。"""
    b = image[:, :, 0].astype(int)
    r = image[:, :, 2].astype(int)
    return ((b > 150) & (b - r > 80)).astype(np.uint8)


def detect_nodes(image: np.ndarray) -> list[MapNode]:
    """偵測 1080p 地圖上的節點圓圈（含中心英雄節點）。

    排除左側主選單、頂欄、右側詳情欄這些固定 UI 區域。
    1080p 標定：minDist=100、半徑 36–84、param2=40。
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)
    found = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=90,
        param1=110, param2=38, minRadius=30, maxRadius=70,
    )
    if found is None:
        return []
    nodes: list[MapNode] = []
    for x, y, radius in found[0]:
        xi, yi, ri = int(x), int(y), int(radius)
        # 右侧 x>1750 是菜单/缩放/定位按钮列，不是地图节点。
        if yi < 60 or xi < 240 or xi > 1750:
            continue
        if not _is_ring_node(gray, xi, yi, ri):
            continue
        nodes.append(MapNode(xi, yi, ri))
    return nodes


def _is_ring_node(gray: np.ndarray, x: int, y: int, radius: int) -> bool:
    """真实节点：亮环明显高于圆内和圆外，排除地图纹理/大头像误报。"""
    ring: list[int] = []
    inner: list[int] = []
    outer: list[int] = []
    for deg in range(0, 360, 5):
        rad = math.radians(deg)
        for rr, bucket in ((radius, ring), (radius * 0.55, inner), (radius * 1.35, outer)):
            xx = int(x + math.cos(rad) * rr)
            yy = int(y + math.sin(rad) * rr)
            if 0 <= xx < gray.shape[1] and 0 <= yy < gray.shape[0]:
                bucket.append(int(gray[yy, xx]))
    if not ring or not inner or not outer:
        return False
    ring_mean = float(np.mean(ring))
    return ring_mean - float(np.mean(inner)) >= 40 and ring_mean - float(np.mean(outer)) >= 20


def detect_ability_nodes(image: np.ndarray) -> list[MapNode]:
    """金色/黃色邊框的菱形能力節點。

    這些節點不是圓形，HoughCircles 會漏掉；它們也不作為「下一節點」候選，
    只用於標註和空白點避讓。

    地圖上的金色地形/裝飾也是同一色系，只靠 HSV 會大量誤報。真正的
    節點是「金環 + 深色中心圖標」；實心金塊的中心也是金色。因此要求
    中心 1/3 區域的金色佔比低，並限制節點尺寸（實測 56×56，範圍 40–90）。
    """
    h, w = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([15, 120, 120]), np.array([40, 255, 255]))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    nodes: list[MapNode] = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if area < 500 or not (0.6 <= cw / max(ch, 1) <= 1.6):
            continue
        if y < 120 or x < 240 or x > w - 440:
            continue
        if not (30 <= cw <= 90 and 30 <= ch <= 90):
            continue
        center = mask[y + ch // 3 : y + 2 * ch // 3, x + cw // 3 : x + 2 * cw // 3]
        if center.size and float((center > 0).mean()) >= 0.3:
            continue
        nodes.append(MapNode(x + cw // 2, y + ch // 2, max(cw, ch) // 2))
    return nodes


def has_checkmark(image: np.ndarray, node: MapNode) -> bool:
    """已完成/已選取節點中心的青綠徽章。1080p 門檻 100 像素。"""
    x0 = max(0, node.x - node.radius)
    y0 = max(0, node.y - node.radius)
    region = image[y0:node.y + node.radius, x0:node.x + node.radius]
    if region.size == 0:
        return False
    b = region[:, :, 0].astype(int)
    g = region[:, :, 1].astype(int)
    r = region[:, :, 2].astype(int)
    return int(((g > 135) & (r < 135) & (g - r >= 20) & (b - g <= 15)).sum()) >= 100


def _reachable_nodes(
    image: np.ndarray,
    hero: MapNode, nodes: list[MapNode], mask: np.ndarray, max_deg: int = 24,
) -> list[MapNode]:
    """從中心英雄節點沿發光線搜索可到達節點。

    1080p 標定：採樣間距 dist/16、窗口 ±24px、閾值 0.38。
    已完成/已選取節點排除，否則會回走亮著的舊線。
    """
    reachable: list[MapNode] = []
    for node in nodes:
        if node is hero or has_checkmark(image, node):
            continue
        dx, dy = node.x - hero.x, node.y - hero.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < 120:
            continue
        steps = max(2, int(dist / 16))
        hits = 0
        for i in range(1, steps):
            t = i / steps
            x = int(hero.x + dx * t)
            y = int(hero.y + dy * t)
            window = mask[max(0, y - max_deg):y + max_deg, max(0, x - max_deg):x + max_deg]
            if window.any():
                hits += 1
        if hits >= steps * 0.38:
            reachable.append(node)
    return reachable


#: 大塊藍色 UI（節點面板/支援英雄卡）打開時 blue_glow 像素數門檻。
#: 1080p 實測：地圖態 ~3760，面板態 4789–6787（動畫中會波動）。
_PANEL_BLUE_MIN = 4500


def panel_open(image: np.ndarray) -> bool:
    """地圖上是否打開了藍色面板（能力/獎勵/節點詳情）。"""
    return int(blue_glow_mask(image).sum()) >= _PANEL_BLUE_MIN


def empty_point(image: np.ndarray) -> tuple[int, int] | None:
    """找一個遠離節點、發光線和面板藍色的空白點，用於關閉面板。"""
    h, w = image.shape[:2]
    nodes = detect_nodes(image) + detect_ability_nodes(image)
    best: tuple[tuple[int, float], tuple[int, int]] | None = None
    # 避开左侧菜单、顶栏和右侧详情栏；在真正的地图空白区里找。
    for y in range(250, h - 250, 80):
        for x in range(400, w - 500, 80):
            if (x - w // 2) ** 2 + (y - h // 2) ** 2 < 150 ** 2:
                continue
            dist = min((((x - n.x) ** 2 + (y - n.y) ** 2) ** 0.5 for n in nodes), default=999)
            if dist < 150:
                continue
            patch = image[max(0, y - 30):y + 30, max(0, x - 30):x + 30]
            if patch.size == 0:
                continue
            noise = int(blue_glow_mask(patch).sum()) + int(glow_mask(patch).sum())
            # 优先右下象限：面板/能力说明通常在左中，右下更可能是纯地图背景。
            quadrant = 0 if x > w // 2 and y > h // 2 else 1
            key = (quadrant, noise, -dist)
            if best is None or key < best[0]:
                best = (key, (x, y))
    return best[1] if best else None


def next_node(
    image: np.ndarray,
    *,
    rng: random.Random | None = None,
    hero: tuple[int, int] | None = None,
) -> MapNode | None:
    """沿發光線找下一個節點；分叉時隨機選。無可走節點/面板打開返回 None。"""
    if panel_open(image):
        return None
    mask = glow_mask(image)
    nodes = detect_nodes(image)
    hero = hero_node(image, nodes)
    reachable = _reachable_nodes(image, hero, nodes, mask)
    if not reachable:
        return next_node_by_path(image, hero=hero, rng=rng)
    return (rng or random).choice(reachable)


def next_node_by_path(
    image: np.ndarray,
    *,
    hero: tuple[int, int] | None = None,
    rng: random.Random | None = None,
) -> MapNode | None:
    """用最大发光路径的端点找下一节点。

    有些地图的节点环对比不足，HoughCircles + _is_ring_node 会漏掉；但路径
    本身很亮。取最大发光连通域，找离英雄最远的端点，再在端点附近找圆形
    节点。找不到圆就用端点本身作为可点位置。
    """
    glow = glow_mask(image)
    contours, _ = cv2.findContours(
        (glow * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 300:
        return None
    points = contour.reshape(-1, 2)
    endpoints = [
        tuple(points[np.argmin(points[:, 0])]),
        tuple(points[np.argmax(points[:, 0])]),
        tuple(points[np.argmin(points[:, 1])]),
        tuple(points[np.argmax(points[:, 1])]),
    ]
    if hero is not None:
        endpoint = max(endpoints, key=lambda p: (p[0] - hero[0]) ** 2 + (p[1] - hero[1]) ** 2)
    else:
        endpoint = max(endpoints, key=lambda p: p[0])
    circle = _circle_near(image, endpoint)
    if circle is not None:
        return MapNode(*circle)
    return MapNode(int(endpoint[0]), int(endpoint[1]), 40)


def _circle_near(
    image: np.ndarray, point: tuple[int, int], radius: int = 100,
) -> tuple[int, int, int] | None:
    """在端点附近找最接近的圆形节点（低阈值 Hough）。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)
    found = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=40,
        param1=100, param2=20, minRadius=15, maxRadius=70,
    )
    if found is None:
        return None
    candidates = [
        (int(x), int(y), int(r)) for x, y, r in found[0]
        if (x - point[0]) ** 2 + (y - point[1]) ** 2 <= radius ** 2
    ]
    if not candidates:
        return None
    # 路径发光/地形也会被 Hough 当成圆。真正的节点有密集的图标/圆环，
    # 用候选框内的 Canny 边缘密度区分（实测节点 0.22–0.27，背景 0.11–0.14）。
    edges = cv2.Canny(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), 40, 120)
    scored = []
    for x, y, r in candidates:
        patch = edges[max(0, y - r) : y + r, max(0, x - r) : x + r]
        if patch.size == 0:
            continue
        scored.append((float((patch > 0).mean()), r, x, y))
    node_like = [item for item in scored if item[0] >= 0.18]
    if node_like:
        # 节点整圆比圆内小图案得分高：密度 × 半径，避免选中节点边缘的小圆。
        _density, r, x, y = max(node_like, key=lambda item: item[0] * item[1])
        return (x, y, r)
    return max(candidates, key=lambda c: c[2])
