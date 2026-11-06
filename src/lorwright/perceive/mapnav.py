"""對局外地圖感知：找英雄節點、沿發光線找下一個節點。

**坐標空間警告（2026-11-05 踩坑 30 分鐘）**：本模塊返回的坐標是
**輸入圖像像素**。f1-control.py 的 --tap 用的是真實 1920x1080 坐標，
而 960x540 預覽圖上算出的坐標必須 **x2** 才能拿去點擊。
預覽圖坐標直接拿去 tap 會點到空處、且無任何報錯。

地圖上的可走路徑是發光的淺藍白線（高亮、帶人字紋），
在亮度閾值下非常容易分離；節點是帶亮環的圓圈。
用戶規則：英雄節點到下一個節點只有一條線就走它，
分叉多條就隨機選一條。
"""

from __future__ import annotations

import random
from dataclasses import dataclass

import cv2
import numpy as np

from lorwright.models import Rect

__all__ = ["MapNode", "detect_nodes", "glow_mask", "next_node", "hero_node"]


@dataclass(frozen=True)
class MapNode:
    x: int
    y: int
    radius: int

    @property
    def center(self) -> tuple[int, int]:
        return (self.x, self.y)

    def rect(self, margin: int = 10) -> Rect:
        return Rect(self.x - self.radius - margin, self.y - self.radius - margin,
                    2 * (self.radius + margin), 2 * (self.radius + margin))


def glow_mask(image: np.ndarray) -> np.ndarray:
    """發光淺藍白線的二值掩碼。輸入為 BGR 圖。"""
    b = image[:, :, 0].astype(int)
    g = image[:, :, 1].astype(int)
    r = image[:, :, 2].astype(int)
    return ((np.minimum(b, g) > 200) & (r > 170)).astype(np.uint8)


def blue_glow_mask(image: np.ndarray) -> np.ndarray:
    """藍色發光（英雄節點下方的指向標、藍色節點環）。"""
    b = image[:, :, 0].astype(int)
    r = image[:, :, 2].astype(int)
    return ((b > 150) & (b - r > 80)).astype(np.uint8)


def detect_nodes(image: np.ndarray) -> list[MapNode]:
    """偵渭地圖上的節點圆圈（含英雄節點）。

    排除左側主選單、頂欄、右側詳情欄這些固定 UI 區域。
    """
    h, w = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (9, 9), 2)
    found = cv2.HoughCircles(
        blur, cv2.HOUGH_GRADIENT, dp=1.2, minDist=50,
        param1=110, param2=28, minRadius=18, maxRadius=42,
    )
    if found is None:
        return []
    nodes: list[MapNode] = []
    for x, y, radius in found[0]:
        xi, yi, ri = int(x), int(y), int(radius)
        if yi < 60 or xi < 120 or xi > w - 220:
            continue
        nodes.append(MapNode(xi, yi, ri))
    return nodes


def has_checkmark(image: np.ndarray, node: MapNode) -> bool:
    # 已完成节点带绿色对勾徽章（用户确认，2026-11-05）。
    # 绿色判据沿用 hand.py 的绿字掩膜：G 高、R/B 低。
    x0 = max(0, node.x - node.radius)
    y0 = max(0, node.y - node.radius)
    region = image[y0:node.y + node.radius, x0:node.x + node.radius]
    if region.size == 0:
        return False
    b = region[:, :, 0].astype(int)
    g = region[:, :, 1].astype(int)
    r = region[:, :, 2].astype(int)
    return int(((g > 150) & (r < 120) & (b < 150)).sum()) >= 30


def hero_node(nodes: list[MapNode], mask: np.ndarray) -> MapNode | None:
    """英雄節點：環下緣（中心 +8..+45px）有藍色指向標的節點。"""
    best: tuple[int, MapNode] | None = None
    for node in nodes:
        x0, x1 = node.x - 20, node.x + 20
        y0, y1 = node.y + 8, node.y + 45
        region = mask[y0:y1, x0:x1]
        score = int(region.sum())
        if score >= 40 and (best is None or score > best[0]):
            best = (score, node)
    return best[1] if best else None


def _reachable_nodes(
    image: np.ndarray,
    hero: MapNode, nodes: list[MapNode], mask: np.ndarray, max_deg: int = 10,
) -> list[MapNode]:
    """從英雄節點沿發光線方向搜索，返回線上可到達的節點。"""
    reachable: list[MapNode] = []
    for node in nodes:
        if node is hero or has_checkmark(image, node):
            continue
        dx, dy = node.x - hero.x, node.y - hero.y
        dist = (dx * dx + dy * dy) ** 0.5
        if dist < 60:
            continue
        steps = max(2, int(dist / 12))
        hits = 0
        for i in range(1, steps):
            t = i / steps
            x = int(hero.x + dx * t)
            y = int(hero.y + dy * t)
            window = mask[max(0, y - max_deg):y + max_deg, max(0, x - max_deg):x + max_deg]
            if window.any():
                hits += 1
        if hits >= steps * 0.6:
            reachable.append(node)
    return reachable


def next_node(
    image: np.ndarray,
    *,
    rng: random.Random | None = None,
    hero_hint: tuple[int, int] | None = None,
) -> MapNode | None:
    """沿發光線找下一個節點；分叉時隨機選。無可走節點返回 None。"""
    mask = glow_mask(image)
    nodes = detect_nodes(image)
    hero = hero_node(nodes, mask)
    if hero is None and hero_hint:
        hx, hy = hero_hint
        hero = min(nodes, key=lambda n: (n.x - hx) ** 2 + (n.y - hy) ** 2) if nodes else None
    if hero is None:
        return None
    reachable = _reachable_nodes(image, hero, nodes, mask)
    if not reachable:
        return None
    return (rng or random).choice(reachable)

