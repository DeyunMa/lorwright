"""對局外地圖感知：根據英雄位置沿發光線找下一個節點。

坐標空間：**1920×1080 設計尺寸**。模擬器原生 1280×720 由
`perceive/normalize.py` 歸一化；地圖不再使用 960×540 分析空間，
`AdventureLoop` 也不再做縮半/×2 換算。

地圖上的可走路徑是發光的淺藍白線（高亮、帶人字紋），
在亮度閾值下非常容易分離；節點是帶亮環的圓圈。
感知层返回已核实可达节点及图标类型；冒险层按语义优先级选择。
next_node 保留随机选择接口，用于已有诊断调用。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.models import MapNodeKind, Rect

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
    "node_kind",
    "panel_open",
    "reachable_nodes",
]


@dataclass(frozen=True)
class MapNode:
    x: int
    y: int
    radius: int
    needs_reveal: bool = False  # 仅见上方展示图标，需平移后核实真实节点

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
    """当前英雄节点：画面中心附近的节点；附近没有就退回中心。"""
    if nodes is None:
        nodes = detect_nodes(image)
    cx, cy = image.shape[1] // 2, image.shape[0] // 2
    if not nodes:
        return MapNode(cx, cy, 60)
    nearest = min(nodes, key=lambda n: (n.x - cx) ** 2 + (n.y - cy) ** 2)
    if (nearest.x - cx) ** 2 + (nearest.y - cy) ** 2 > 200 ** 2:
        return MapNode(cx, cy, 60)
    return nearest


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
    template = _lit_diamond_template()
    if template is not None:
        region = image[120:, 240:w - 440]
        scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        for dy, dx in zip(*np.where(scores >= 0.93), strict=True):
            x, y = int(dx) + 240, int(dy) + 120
            actual = image[y:y + template.shape[0], x:x + template.shape[1]]
            if float((cv2.absdiff(actual, template) > 45).mean()) >= 0.08:
                continue
            node = MapNode(x + template.shape[1] // 2, y + template.shape[0] // 2, 32)
            if all(math.hypot(node.x - old.x, node.y - old.y) >= 40 for old in nodes):
                nodes.append(node)
    return nodes


@cache
def _lit_diamond_template() -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure/map_lit_diamond.png")))


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


def panel_open(image: np.ndarray) -> bool:
    """检测地图上大型深色节点面板，避免将节点蓝色光效误当面板。

    实测完成面板和旅行面板都有大块深色背景；只接受地图主体范围内
    足够大的连通区域，边缘状态栏及零散阴影不能算面板。
    """
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array((0, 0, 8)), np.array((180, 120, 48)))
    mask[:120, :] = 0
    mask[820:, :] = 0
    mask[:, :240] = 0
    mask[:, 1700:] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((21, 21), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    # 地图中的山洞阴影也可能形成大型连通域；面板背景更接近实心矩形。
    return any(w >= 350 and h >= 160 and area >= 50000 and area / (w * h) >= 0.55
               for _, _, w, h, area in stats[1:])


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


@cache
def _node_kind_templates() -> tuple[tuple[MapNodeKind, np.ndarray], ...]:
    result = []
    for kind in (MapNodeKind.EVENT, MapNodeKind.SHOP, MapNodeKind.GOLD):
        template = cv2.imread(str(Path("assets/adventure") / f"map_{kind.value}_icon.png"))
        if template is not None:
            result.append((kind, template))
    return tuple(result)


def node_kind(image: np.ndarray, node: MapNode) -> MapNodeKind | None:
    """只读节点中心图标，不从左右位置或相邻路线推断类型。"""
    x, y = node.center
    if (image.shape != (1080, 1920, 3) or x < 40 or y < 40
            or x + 40 > image.shape[1] or y + 40 > image.shape[0]):
        return None
    region = image[y - 40:y + 40, x - 40:x + 40]
    matches = []
    for kind, template in _node_kind_templates():
        _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(
            region, template, cv2.TM_CCOEFF_NORMED,
        ))
        h, w = template.shape[:2]
        actual = region[dy:dy + h, dx:dx + w]
        if score >= 0.93 and float((cv2.absdiff(actual, template) > 45).mean()) < 0.08:
            matches.append((score, kind))
    matches.sort(reverse=True)
    if not matches or (len(matches) > 1 and matches[0][0] - matches[1][0] < 0.05):
        return None
    return matches[0][1]


def next_node(
    image: np.ndarray,
    *,
    rng: random.Random | None = None,
    hero: tuple[int, int] | None = None,
) -> MapNode | None:
    """随机返回一个已核实可达节点；冒险层另外按语义优先级选择。"""
    nodes = reachable_nodes(image, hero=hero, rng=rng)
    return (rng or random).choice(nodes) if nodes else None


def reachable_nodes(
    image: np.ndarray, *, hero: tuple[int, int] | None = None, rng: random.Random | None = None,
) -> list[MapNode]:
    """只返回通过亮线和目标状态检查的节点，不在感知层决定优先级。"""
    if panel_open(image):
        return []
    mask = glow_mask(image)
    if hero is not None:
        routes = _lit_routes_from_ability(image, hero, mask)
        if routes is not None:
            return routes
        if _current_battle_node_visible(image, hero):
            return [MapNode(hero[0], hero[1] + 95, 48)]
        if _current_home_node_visible(image, hero):
            return _lit_diamond_routes(image, hero, mask, from_home=True)
        completed = _current_completed_node_visible(image, hero)
        if completed or _current_node_halo_visible(image, hero):
            round_mask = mask
            if completed:
                blue, green, red = (image[:, :, i].astype(np.int16) for i in range(3))
                cyan = (blue > 165) & (green > 145) & (blue - red > 35) & (green - red > 20)
                round_mask = mask | cyan.astype(np.uint8)
            routes = _lit_routes_from_round(image, hero, round_mask, hero_occlusion=completed)
            if completed:
                routes += _lit_diamond_routes(image, hero, mask)
                # 金色方框可能属于同一菱形节点；已有完整目标时不重复加入其图标。
                routes += [node for node in _lit_gold_routes(image, hero, round_mask)
                           if all(math.hypot(node.x - old.x, node.y - old.y) >= 120
                                  for old in routes)]
            return routes
        return []
    nodes = detect_nodes(image)
    current = hero_node(image, nodes)
    reachable = _reachable_nodes(image, current, nodes, mask)
    if not reachable:
        node = next_node_by_path(image, hero=current.center, rng=rng)
        return [node] if node is not None else []
    return reachable


@cache
def _current_completed_template() -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure/map_current_check.png")), cv2.IMREAD_COLOR)


def _check_color_mask(image: np.ndarray) -> np.ndarray:
    """完成勾的亮黄绿色；青绿色图标不直接视为完成。"""
    blue, green, red = (image[:, :, i].astype(np.int16) for i in range(3))
    return (((green > 145) & (green - blue > 50) & (green - red > 25)) * 255).astype(np.uint8)


def _checkmark_visible(image: np.ndarray, bounds: tuple[int, int, int, int]) -> bool:
    template = _current_completed_template()
    if template is None:
        return False
    x1, y1, x2, y2 = bounds
    if x1 < 0 or y1 < 0 or x2 > image.shape[1] or y2 > image.shape[0]:
        return False
    reference = _check_color_mask(template)
    region = _check_color_mask(image[y1:y2, x1:x2])
    height, width = reference.shape
    if region.shape[0] < height or region.shape[1] < width:
        return False
    scores = cv2.matchTemplate(region, reference, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    matched = region[y:y + height, x:x + width] > 0
    check_pixels = reference > 0
    overlap = int(np.count_nonzero(matched & check_pixels))
    return bool(score >= 0.45 and overlap >= int(np.count_nonzero(check_pixels) * 0.8))


def _current_completed_node_visible(image: np.ndarray, hero: tuple[int, int]) -> bool:
    """识别头像脚下的完成勾；不把任意绿色图标视为完成。"""
    x, y = hero
    if (image.shape != (1080, 1920, 3) or x < 65 or y < 0
            or x + 65 >= 1920 or y + 155 >= 1080):
        return False
    return _checkmark_visible(image, (x - 55, y + 55, x + 55, y + 125))


def _node_edge_visible(
    image: np.ndarray, anchor: MapNode, target: MapNode,
) -> bool:
    """拒绝起点边缘与亮线交界处可见的大块暗色遮挡。"""
    dx, dy = target.x - anchor.x, target.y - anchor.y
    distance = math.hypot(dx, dy)
    if not distance:
        return False
    extent = anchor.radius + 60
    if (anchor.x < extent or anchor.y < extent or anchor.x + extent >= image.shape[1]
            or anchor.y + extent >= image.shape[0]):
        return False
    region = image[anchor.y - extent:anchor.y + extent + 1,
                   anchor.x - extent:anchor.x + extent + 1]
    corridor = np.zeros(region.shape[:2], np.uint8)

    def point(length: float) -> tuple[int, int]:
        return (round(extent + dx * length / distance),
                round(extent + dy * length / distance))

    cv2.line(corridor, point(anchor.radius * 0.55), point(anchor.radius + 28), 255, 31)
    value = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)[:, :, 2]
    dark = ((value < 20) & (corridor > 0)).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(dark)
    return count <= 1 or int(stats[1:, cv2.CC_STAT_AREA].max()) < 100


def _component_between_nodes(
    distances: np.ndarray, anchor: MapNode, target: MapNode,
) -> bool:
    """检查同一发光连通域沿两节点间直线经过，而非绕过其他节点。"""
    dx, dy = target.x - anchor.x, target.y - anchor.y
    length = math.hypot(dx, dy)
    positions = np.arange(anchor.radius + 16, length - target.radius - 16, 4)
    if not len(positions):
        return False
    for position in positions:
        x = round(anchor.x + dx * position / length)
        y = round(anchor.y + dy * position / length)
        if distances[y, x] > 10:
            return False
    return True


def _lit_routes_from_round(
    image: np.ndarray, hero: tuple[int, int], mask: np.ndarray,
    *, origin: MapNode | None = None, hero_occlusion: bool = False,
) -> list[MapNode]:
    """从圆节点找与其连续连接的可见蓝环，不按节点类型或坐标选择。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(gray, (9, 9), 2), cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=40, param1=100, param2=20, minRadius=28, maxRadius=70,
    )
    if circles is None:
        return []
    candidates = [MapNode(int(x), int(y), int(r)) for x, y, r in circles[0]]
    guess = (hero[0], hero[1] + 90)
    anchors = [n for n in candidates if (n.x - guess[0]) ** 2 + (n.y - guess[1]) ** 2 < 18 ** 2]
    if origin is None and not anchors:
        return []
    anchor = origin or min(anchors, key=lambda n: (n.x - guess[0]) ** 2 + (n.y - guess[1]) ** 2)
    # 亮线与当前节点的光环可能因阈值分割出现几像素的间隙。
    extent = anchor.radius + 18
    if hero_occlusion:
        extent = max(extent, math.ceil(math.hypot(hero[0] - anchor.x, hero[1] - anchor.y)) + 68)
    if (anchor.x < extent or anchor.y < extent or anchor.x + extent >= image.shape[1]
            or anchor.y + extent >= image.shape[0]):
        return []
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    local = labels[anchor.y - extent:anchor.y + extent + 1,
                   anchor.x - extent:anchor.x + extent + 1]
    yy, xx = np.ogrid[-extent:extent + 1, -extent:extent + 1]
    labels_near_anchor = np.unique(local[xx * xx + yy * yy <= extent ** 2])
    found: list[tuple[float, MapNode]] = []
    for label in labels_near_anchor:
        if label == 0 or stats[label, cv2.CC_STAT_AREA] < 300:
            continue
        distances = cv2.distanceTransform(
            (labels != label).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
        )
        for node in candidates:
            if not (240 < node.x < 1750 and 60 < node.y < 1000):
                continue
            if (node.x - anchor.x) ** 2 + (node.y - anchor.y) ** 2 < 120 ** 2:
                continue
            route_anchor = anchor
            if hero_occlusion:
                # 已识别头像半径约 50px；只沿穿过头像的方向跳过其遮挡，
                # 其他方向及头像之外的断线仍需完整核验。
                dx, dy = node.x - anchor.x, node.y - anchor.y
                length = math.hypot(dx, dy)
                hx, hy = hero[0] - anchor.x, hero[1] - anchor.y
                projection = (hx * dx + hy * dy) / length
                perpendicular_sq = hx * hx + hy * hy - projection * projection
                if 0 < projection < length and perpendicular_sq < 50 ** 2:
                    hidden_until = projection + math.sqrt(50 ** 2 - perpendicular_sq)
                    route_anchor = MapNode(anchor.x, anchor.y,
                                           max(anchor.radius, math.ceil(hidden_until)))
            if not _component_between_nodes(distances, route_anchor, node):
                continue
            if not _node_edge_visible(image, route_anchor, node):
                continue
            if not _lit_unfinished_ring(
                image, labels, int(label), node.x, node.y, node.radius,
                min_cyan=0.15, min_connected_cyan=120,
            ):
                continue
            extent = node.radius + 18
            region = image[node.y - extent:node.y + extent + 1,
                           node.x - extent:node.x + extent + 1]
            yy, xx = np.ogrid[-extent:extent + 1, -extent:extent + 1]
            radius_sq = xx * xx + yy * yy
            annulus = ((radius_sq >= max(10, node.radius - 18) ** 2)
                       & (radius_sq <= extent ** 2))
            blue, green, red = (region[:, :, i].astype(np.int16) for i in range(3))
            cyan = (blue > 165) & (green > 145) & (blue - red > 35) & (green - red > 20)
            found.append((float(cyan[annulus].mean()), node))
    # 同一节点周围的多个 Hough 圆只保留蓝环证据最强的一个。
    result: list[MapNode] = []
    for _, node in sorted(found, key=lambda item: item[0], reverse=True):
        if all((n.x - node.x) ** 2 + (n.y - node.y) ** 2 >= 70 ** 2 for n in result):
            result.append(node)
    return result


@cache
def _gold_node_template() -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure/map_gold_node_visible.png")))


def _lit_gold_routes(
    image: np.ndarray, hero: tuple[int, int], mask: np.ndarray,
) -> list[MapNode]:
    """核实可见金色节点及直连亮线；模板只依赖完整可见的中心和内框。"""
    template = _gold_node_template()
    lock = _map_lock_template()
    if image.shape != (1080, 1920, 3) or template is None or lock is None:
        return []
    region = image[120:, 240:1750]
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    anchor = MapNode(hero[0], hero[1] + 90, 48)
    nearby = np.unique(labels[max(0, anchor.y - 66):anchor.y + 67,
                              max(0, anchor.x - 66):anchor.x + 67])
    result = []
    for dy, dx in zip(*np.where(scores >= 0.93), strict=True):
        x, y = int(dx) + 240, int(dy) + 120
        actual = image[y:y + template.shape[0], x:x + template.shape[1]]
        if float((cv2.absdiff(actual, template) > 45).mean()) >= 0.08:
            continue
        node = MapNode(x + template.shape[1] // 2, y + template.shape[0] // 2, 38,
                       needs_reveal=True)
        if any(math.hypot(node.x - n.x, node.y - n.y) < 60 for n in result):
            continue
        if not 120 < math.hypot(node.x - anchor.x, node.y - anchor.y) < 800:
            continue
        center = cv2.cvtColor(image[node.y - 30:node.y + 31,
                                        node.x - 30:node.x + 31], cv2.COLOR_BGR2GRAY)
        if (cv2.matchTemplate(center, lock, cv2.TM_CCOEFF_NORMED).max() >= 0.8
                or _checkmark_visible(image, (node.x - 35, node.y - 30,
                                              node.x + 36, node.y + 31))):
            continue
        if not _node_edge_visible(image, anchor, node):
            continue
        for label in nearby:
            if label == 0 or stats[label, cv2.CC_STAT_AREA] < 300:
                continue
            distances = cv2.distanceTransform((labels != label).astype(np.uint8),
                                              cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
            if _component_between_nodes(distances, anchor, node):
                result.append(node)
                break
    return result


@cache
def _support_marker_templates() -> tuple[np.ndarray, ...]:
    return tuple(image for name in ("map_support_marker", "map_support_marker_dim")
                 if (image := cv2.imread(str(Path("assets/adventure") / f"{name}.png"))) is not None)


def _support_marker_visible(image: np.ndarray, x: int, y: int) -> bool:
    """辅助英雄金色徽记须完整可见，不能只凭菱形或背景亮色推断。"""
    region = image[y - 130:y - 40, x - 50:x + 50]
    if region.shape[:2] != (90, 100):
        return False
    for template in _support_marker_templates():
        scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
        h, w = template.shape[:2]
        actual = region[dy:dy + h, dx:dx + w]
        error = float((cv2.absdiff(actual, template) > 45).mean())
        if score >= 0.93 and error < 0.08:
            return True
    return False


@cache
def _home_route_template(name: str) -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure") / f"{name}.png"))


def _home_route_marker_visible(image: np.ndarray, name: str, x: int, y: int) -> bool:
    template = _home_route_template(name)
    if template is None or x < 35 or y < 35 or x + 35 >= 1920 or y + 35 >= 1080:
        return False
    region = image[y - 35:y + 35, x - 35:x + 35]
    _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(
        region, template, cv2.TM_CCOEFF_NORMED,
    ))
    h, w = template.shape[:2]
    actual = region[dy:dy + h, dx:dx + w]
    return bool(score >= 0.93 and float((cv2.absdiff(actual, template) > 45).mean()) < 0.08)


def _current_home_node_visible(image: np.ndarray, hero: tuple[int, int]) -> bool:
    return (_current_node_halo_visible(image, hero)
            and _home_route_marker_visible(image, "map_home_icon", hero[0], hero[1] + 90))


def _lit_diamond_routes(
    image: np.ndarray, hero: tuple[int, int], mask: np.ndarray, *, from_home: bool = False,
) -> list[MapNode]:
    """识别完成节点或首页起点直连的高亮菱形；状态不明时弃权。"""
    anchor = (hero[0], hero[1] + 90)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = []
    for node in detect_ability_nodes(image):
        # 菱形上方的方形图标及其直连路径构成一组；限定尺寸和完整可见范围。
        r = node.radius
        if not 30 <= r <= 45:
            continue
        x, y = node.x, node.y
        if x < 80 or x + 80 >= image.shape[1] or y + 60 >= image.shape[0]:
            continue
        support = _support_marker_visible(image, x, y)
        if from_home and not _home_route_marker_visible(image, "map_first_power_arrow", x, y):
            continue
        # 首页箭头和辅助英雄的亮线连接菱形本体；旧方形节点连接其上方图标。
        icon_y = y if support or from_home else y - 3 * r
        if icon_y < 80:
            continue
        # 向上路线被英雄头像遮住一段，只核验头像边缘之外的可见亮线。
        route_anchor = hero if support else anchor
        distance = math.hypot(x - route_anchor[0], icon_y - route_anchor[1])
        if not 110 <= distance <= 800:
            continue
        # 空心菱形四边须具备蓝白高亮，不能仅凭金色装饰判定。
        patch = image[y - 55:y + 56, x - 55:x + 56].astype(np.int16)
        yy, xx = np.ogrid[-55:56, -55:56]
        diamond = (np.abs(xx) + np.abs(yy) >= 43) & (np.abs(xx) + np.abs(yy) <= 55)
        cyan = (patch[:, :, 0] > 170) & (patch[:, :, 1] > 155) & (patch[:, :, 0] - patch[:, :, 2] > 25)
        if any(float(cyan[diamond & quadrant].mean()) < 0.12 for quadrant in (
            (xx < 0) & (yy < 0), (xx >= 0) & (yy < 0),
            (xx < 0) & (yy >= 0), (xx >= 0) & (yy >= 0),
        )):
            continue
        # 中心必须完整且无锁或完成图案；不推断被遮挡的内容。
        if _checkmark_visible(image, (x - 35, y - 30, x + 36, y + 31)):
            continue
        if _checkmark_visible(image, (x - 35, icon_y - 30, x + 36, icon_y + 31)):
            continue
        centers = (image[y - 9:y + 9, x - 9:x + 9],
                   image[icon_y - 14:icon_y + 14, x - 14:x + 14])
        if not from_home and (float(centers[0].std()) < 4
                or any(int((cv2.Canny(center, 70, 140) > 0).sum()) > limit
                       for center, limit in zip(centers, (8, 45), strict=True))):
            continue
        # 首页箭头已按完整图案核验，不能套用旧节点的空中心检查。
        if from_home and not _node_edge_visible(image, MapNode(*anchor, 48), node):
            continue
        # 方形外框需要四边亮起；首页箭头和辅助英雄已独立核实。
        if not support and not from_home:
            icon = gray[icon_y - 48:icon_y + 49, x - 48:x + 49]
            if any(float((edge > 180).mean()) < 0.12 for edge in (
                icon[0:12, 20:77], icon[85:97, 20:77],
                icon[20:77, 0:12], icon[20:77, 85:97],
            )):
                continue
        # 同一亮线连通域须贴近起点及方形，且沿两者间直线贯通。
        for label in range(1, len(stats)):
            left, top, width, height, area = stats[label]
            if (area < 100 or left > max(route_anchor[0], x) + 55
                    or left + width < min(route_anchor[0], x) - 55
                    or top > max(route_anchor[1], icon_y) + 55
                    or top + height < min(route_anchor[1], icon_y) - 55):
                continue
            distances = cv2.distanceTransform((labels != label).astype(np.uint8), cv2.DIST_L2,
                                              cv2.DIST_MASK_PRECISE)
            positions = np.arange(45, distance - 45, 3)
            if len(positions) < 5:
                continue
            if all(distances[round(route_anchor[1] + (icon_y - route_anchor[1]) * t / distance),
                             round(route_anchor[0] + (x - route_anchor[0]) * t / distance)] <= 7
                   for t in positions):
                result.append(node)
                break
    return result


def _current_node_halo_visible(image: np.ndarray, hero: tuple[int, int]) -> bool:
    """未识别菱形时，仅在英雄脚下的蓝环和中心图标可见时使用旧路径。"""
    x, y = hero[0], hero[1] + 95
    extent = 75
    if (image.shape != (1080, 1920, 3) or x < extent or y < extent
            or x + extent >= image.shape[1] or y + extent >= image.shape[0]):
        return False
    region = image[y - extent:y + extent + 1, x - extent:x + extent + 1]
    yy, xx = np.ogrid[-extent:extent + 1, -extent:extent + 1]
    distance = xx * xx + yy * yy
    annulus = (distance >= 40 ** 2) & (distance <= extent ** 2)
    blue, green, red = (region[:, :, i].astype(np.int16) for i in range(3))
    cyan = (blue > 165) & (green > 145) & (blue - red > 35) & (green - red > 20)
    center = image[y - 18:y + 18, x - 18:x + 18]
    # 商店等节点的图标和头像会遮住一部分光环；仍要求中心可见、
    # 且后续由连续亮线与未完成目标共同验证，避免仅凭微弱蓝光移动。
    return float(cyan[annulus].mean()) >= 0.12 and float(center.std()) >= 12


@cache
def _map_lock_template() -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure/map_lock.png")), cv2.IMREAD_GRAYSCALE)


def _current_battle_node_visible(image: np.ndarray, hero: tuple[int, int]) -> bool:
    """识别脚下仍待挑战的战斗节点；其他节点不能仅凭蓝光重进。"""
    if (_current_completed_node_visible(image, hero)
            or not _current_node_halo_visible(image, hero)):
        return False
    x, y = hero[0], hero[1] + 95
    extent = 75
    region = image[y - extent:y + extent + 1, x - extent:x + extent + 1]
    yy, xx = np.ogrid[-extent:extent + 1, -extent:extent + 1]
    distance = xx * xx + yy * yy
    lower_ring = (distance >= 28 ** 2) & (distance <= 48 ** 2) & (yy >= 0)
    blue, green, red = (region[:, :, i].astype(np.int16) for i in range(3))
    orange = (red > 140) & (red - green > 30) & (green - blue > 10) & (green > 45)
    bright_halo = (blue > 220) & (green > 200) & (blue - red > 35)
    center = cv2.cvtColor(image[y - 5:y + 5, x - 5:x + 5], cv2.COLOR_BGR2GRAY)
    lock = _map_lock_template()
    if lock is None:
        return False
    center_region = cv2.cvtColor(image[y - 30:y + 30, x - 30:x + 30], cv2.COLOR_BGR2GRAY)
    if cv2.matchTemplate(center_region, lock, cv2.TM_CCOEFF_NORMED).max() >= 0.8:
        return False
    return (float(orange[lower_ring].mean()) >= 0.04
            and int(bright_halo.sum()) >= 200 and float(center.std()) >= 5)


@cache
def _current_diamond_templates() -> tuple[np.ndarray, ...]:
    return tuple(image for name in ("map_current_diamond", "map_current_power_diamond")
                 if (image := cv2.imread(str(Path("assets/adventure") / f"{name}.png")))
                 is not None)


def _current_diamond_visible(image: np.ndarray, hero: tuple[int, int]) -> MapNode | None:
    """在已识别头像下核实菱形，避免同色地形吞并其全图轮廓。"""
    x, y = hero
    if x < 50 or x + 50 >= 1920 or y < 0 or y + 140 >= 1080:
        return None
    region = image[y + 55:y + 140, x - 50:x + 50]
    for template in _current_diamond_templates():
        _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(
            region, template, cv2.TM_CCOEFF_NORMED))
        h, w = template.shape[:2]
        actual = region[dy:dy + h, dx:dx + w]
        if score >= 0.93 and float((cv2.absdiff(actual, template) > 45).mean()) < 0.08:
            return MapNode(x - 50 + dx + w // 2, y + 55 + dy + h // 2, 28)
    return None


def _lit_routes_from_ability(
    image: np.ndarray, hero: tuple[int, int], mask: np.ndarray,
) -> list[MapNode] | None:
    """识别英雄站在菱形节点上时，连续亮线连接的蓝环节点。

    None 表示没有识别到脚下的菱形；空列表表示场景适用但没有可确认
    的路线，不能再使用较宽松的路径回退。
    """
    if image.shape != (1080, 1920, 3):
        return None
    current = _current_diamond_visible(image, hero)
    if current is not None:
        # 当前头像遮住路线的起始部分；从遮挡范围外核验连续青色亮线。
        blue, green, red = (image[:, :, i].astype(np.int16) for i in range(3))
        cyan = ((blue > 165) & (green > 145) & (blue - red > 35) & (green - red > 20))
        origin = MapNode(current.x, current.y, current.y - hero[1])
        return _lit_routes_from_round(image, hero, cyan.astype(np.uint8), origin=origin)
    anchors = [
        node for node in detect_ability_nodes(image)
        if abs(node.x - hero[0]) <= 30 and 55 <= node.y - hero[1] <= 125
    ]
    if not anchors:
        return None
    if len(anchors) != 1:
        return []
    anchor = anchors[0]
    _, labels = cv2.connectedComponents(mask, connectivity=8)
    contours, _ = cv2.findContours(mask * 255, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    nodes: list[MapNode] = []
    for contour in contours:
        if cv2.contourArea(contour) < 300:
            continue
        if cv2.pointPolygonTest(contour, anchor.center, True) < -50:
            continue
        points = contour.reshape(-1, 2)
        cx, cy = points[0]
        label = labels[cy, cx]
        if not _line_touches_ability(image, labels, label, anchor):
            continue
        ends = (
            points[np.argmin(points[:, 0])], points[np.argmax(points[:, 0])],
            points[np.argmin(points[:, 1])], points[np.argmax(points[:, 1])],
        )
        end = max(ends, key=lambda p: (int(p[0]) - anchor.x) ** 2
                  + (int(p[1]) - anchor.y) ** 2)
        circle = _circle_near(image, tuple(end))
        if circle is None:
            continue
        x, y, radius = circle
        if (x - anchor.x) ** 2 + (y - anchor.y) ** 2 < 120 ** 2:
            continue
        if x < 240 or x > 1750 or y < 60 or radius < 45:
            continue
        if not _lit_unfinished_ring(image, labels, label, x, y, radius):
            continue
        if all((node.x - x) ** 2 + (node.y - y) ** 2 >= 50 ** 2 for node in nodes):
            nodes.append(MapNode(x, y, radius))
    return nodes


def _line_touches_ability(
    image: np.ndarray, labels: np.ndarray, label: int, anchor: MapNode,
) -> bool:
    """检查亮线连通域与英雄脚下菱形的实际金色边缘相邻。"""
    extent = anchor.radius + 30
    if (anchor.x < extent or anchor.y < extent or anchor.x + extent >= image.shape[1]
            or anchor.y + extent >= image.shape[0]):
        return False
    x0, x1 = anchor.x - extent, anchor.x + extent + 1
    y0, y1 = anchor.y - extent, anchor.y + extent + 1
    hsv = cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, (15, 120, 120), (40, 255, 255))
    yy, xx = np.ogrid[-extent:extent + 1, -extent:extent + 1]
    gold[xx * xx + yy * yy > (anchor.radius + 8) ** 2] = 0
    component = labels[y0:y1, x0:x1] == label
    if not component.any() or not gold.any():
        return False
    distances = cv2.distanceTransform((~component).astype(np.uint8), cv2.DIST_L2,
                                      cv2.DIST_MASK_PRECISE)
    return float(distances[gold > 0].min()) <= 6


def _lit_unfinished_ring(
    image: np.ndarray, labels: np.ndarray, label: int, x: int, y: int, radius: int,
    *, min_cyan: float = 0.2, min_connected_cyan: int = 200,
) -> bool:
    """检查亮线与蓝环，并拒绝低纹理中心及绿色完成标记。"""
    extent = radius + 18
    if x < extent or y < extent or x + extent >= image.shape[1] or y + extent >= image.shape[0]:
        return False
    region = image[y - extent:y + extent + 1, x - extent:x + extent + 1]
    yy, xx = np.ogrid[-extent:extent + 1, -extent:extent + 1]
    distance = xx * xx + yy * yy
    annulus = (distance >= max(10, radius - 18) ** 2) & (distance <= extent ** 2)
    blue, green, red = (region[:, :, i].astype(np.int16) for i in range(3))
    cyan = (blue > 165) & (green > 145) & (blue - red > 35) & (green - red > 20)
    if float(cyan[annulus].mean()) < min_cyan:
        return False
    component = labels[y - extent:y + extent + 1, x - extent:x + extent + 1] == label
    if int(np.count_nonzero(component & annulus & cyan)) < min_connected_cyan:
        return False
    lock = _map_lock_template()
    center_region = cv2.cvtColor(image[y - 30:y + 30, x - 30:x + 30], cv2.COLOR_BGR2GRAY)
    if lock is None or cv2.matchTemplate(center_region, lock, cv2.TM_CCOEFF_NORMED).max() >= 0.8:
        return False
    center_gray = cv2.cvtColor(image[y - 10:y + 10, x - 10:x + 10], cv2.COLOR_BGR2GRAY)
    if float(center_gray.std()) < 12 or float(center_gray[5:15, 5:15].std()) < 5:
        return False
    visible_radius = int(radius * 0.9)
    visible = image[y - visible_radius:y + visible_radius, x - visible_radius:x + visible_radius]
    darkness = cv2.inRange(cv2.cvtColor(visible, cv2.COLOR_BGR2HSV), (0, 0, 0), (180, 255, 19))
    count, _, stats, _ = cv2.connectedComponentsWithStats(darkness)
    if count > 1 and int(stats[1:, cv2.CC_STAT_AREA].max()) >= 100:
        return False
    return not _checkmark_visible(image, (x - 35, y - 30, x + 36, y + 31))


def next_node_by_path(
    image: np.ndarray,
    *,
    hero: tuple[int, int] | None = None,
    rng: random.Random | None = None,
) -> MapNode | None:
    """用最大发光路径的端点找下一节点。

    有些地图的节点环对比不足，HoughCircles + _is_ring_node 会漏掉；但路径
    本身很亮。只考虑靠近英雄的发光连通域，在远端寻找圆形节点；
    找不到节点或圆心太靠近英雄时弃权，避免将当前节点的光环当成路径。
    """
    if hero is None:
        return None
    glow = glow_mask(image)
    contours, _ = cv2.findContours(
        (glow * 255).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) < 300:
        return None
    # 地图头像位于当前节点上方，已验证的路径与头像相距不超过 120px。
    if cv2.pointPolygonTest(contour, hero, True) < -120:
        return None
    points = contour.reshape(-1, 2)
    endpoints = [
        tuple(points[np.argmin(points[:, 0])]),
        tuple(points[np.argmax(points[:, 0])]),
        tuple(points[np.argmin(points[:, 1])]),
        tuple(points[np.argmax(points[:, 1])]),
    ]
    endpoint = max(endpoints, key=lambda p: (p[0] - hero[0]) ** 2 + (p[1] - hero[1]) ** 2)
    circle = _circle_near(image, endpoint)
    if circle is None:
        return None
    x, y, radius = circle
    if (x - hero[0]) ** 2 + (y - hero[1]) ** 2 < 120 ** 2:
        return None
    return MapNode(x, y, radius)


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
