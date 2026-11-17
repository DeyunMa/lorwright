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
from lorwright.core.perceive.adventure_scene import button_is
from lorwright.core.perceive.panels import action_button

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

    這些節點不是圓形，HoughCircles 會漏掉；此處只做形狀檢測，
    不判定可達性。

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
    # 面板阴影可能与地图相连；框内明确的旅行按钮可补充矩形证据。
    regions = [(x, y, w, h, area) for x, y, w, h, area in stats[1:]
               if w >= 350 and h >= 160 and area >= 50000]
    if any(area / (w * h) >= 0.55 for _, _, w, h, area in regions):
        return True
    if not regions:
        return False
    button = action_button(image)
    return (button is not None and button_is(image, button, "travel")
            and any(x <= button.x and y <= button.y
                    and button.x + button.w <= x + w and button.y + button.h <= y + h
                    for x, y, w, h, _ in regions))


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
    """返回当前帧已核实的一跳目标；业务类型及优先级由调用方处理。

    hero 由运行时头像识别器提供。省略时只供已有诊断以画面中心附近
    的真实圆环推断锚点；运行时头像拒识不能调用此诊断模式继续导航。
    """
    if image.shape != (1080, 1920, 3) or panel_open(image):
        return []
    inferred = None
    if hero is None:
        node = hero_node(image)
        if _is_ring_node(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), node.x, node.y, node.radius):
            inferred = _NavigationNode(node, "round")
        hero = (node.x, node.y - 90)
    candidates = _navigation_candidates(image)
    current = inferred or _navigation_origin(image, hero, candidates)
    if current is None:
        return []
    # 尚未挑战的脚下战斗是本地交互，不能当成一条通往其他节点的边。
    if current.shape == "round" and _current_battle_node_visible(image, hero):
        return [MapNode(hero[0], hero[1] + 95, 48)]
    blue, green, red = (image[:, :, i].astype(np.int16) for i in range(3))
    cyan = (blue > 165) & (green > 145) & (blue - red > 35) & (green - red > 20)
    mask = glow_mask(image) | cyan.astype(np.uint8)
    return _connected_navigation_nodes(image, current.node, hero, candidates, mask)


@dataclass(frozen=True)
class _NavigationNode:
    node: MapNode
    shape: str
    connection: MapNode | None = None


def _navigation_candidates(image: np.ndarray) -> list[_NavigationNode]:
    """形状检测只提供位置，不按节点业务类型选择路线。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(gray, (9, 9), 2), cv2.HOUGH_GRADIENT,
        dp=1.2, minDist=40, param1=100, param2=20, minRadius=28, maxRadius=70,
    )
    result = [_NavigationNode(MapNode(int(x), int(y), int(r)), "round")
              for x, y, r in circles[0]
              if 240 < x < 1750 and 60 < y < 1000] if circles is not None else []
    result += [_NavigationNode(node, "diamond") for node in detect_ability_nodes(image)]
    template = _gold_node_template()
    if template is not None:
        region = image[120:, 240:1750]
        scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
        h, w = template.shape[:2]
        for dy, dx in zip(*np.where(scores >= 0.93), strict=True):
            x, y = int(dx) + 240, int(dy) + 120
            actual = image[y:y + h, x:x + w]
            if float((cv2.absdiff(actual, template) > 45).mean()) < 0.08:
                result.append(_NavigationNode(MapNode(x + w // 2, y + h // 2, 38,
                                                       needs_reveal=True), "display"))
    # 展示框和下方菱形属于同一节点；两个可见连接端口共用边核验。
    diamonds = [candidate for candidate in result if candidate.shape == "diamond"]
    result = [candidate for candidate in result if candidate.shape != "display" or not any(
        abs(candidate.node.x - diamond.node.x) < 20
        and 65 <= diamond.node.y - candidate.node.y <= 120 for diamond in diamonds
    )]
    for candidate in diamonds:
        node = candidate.node
        icon_y = node.y - 3 * node.radius
        if node.x < 50 or icon_y < 50:
            continue
        icon = gray[icon_y - 48:icon_y + 49, node.x - 48:node.x + 49]
        if icon.shape != (97, 97):
            continue
        if any(float((edge > 180).mean()) < 0.12 for edge in (
            icon[0:12, 20:77], icon[85:97, 20:77],
            icon[20:77, 0:12], icon[20:77, 85:97],
        )):
            continue
        port = MapNode(node.x, icon_y, 45)
        if (_unlocked_unfinished_center(image, port)
                and int((cv2.Canny(icon[34:62, 34:62], 70, 140) > 0).sum()) <= 45):
            result.append(_NavigationNode(node, candidate.shape, port))
    return result


def _navigation_origin(
    image: np.ndarray, hero: tuple[int, int], candidates: list[_NavigationNode],
) -> _NavigationNode | None:
    """确认当前节点；头像只提供锚点，完成勾或可见轮廓提供节点证据。"""
    diamond = _current_diamond_visible(image, hero)
    if diamond is not None:
        return _NavigationNode(diamond, "diamond")
    nearby = [candidate for candidate in candidates
              if candidate.connection is None and abs(candidate.node.x - hero[0]) <= 30
              and 55 <= candidate.node.y - hero[1] <= 125]
    diamonds = [candidate for candidate in nearby if candidate.shape == "diamond"]
    if diamonds:
        return diamonds[0] if len(diamonds) == 1 else None
    completed = _current_completed_node_visible(image, hero)
    if not (completed or _current_node_halo_visible(image, hero)):
        return None
    rounds = [candidate for candidate in nearby if candidate.shape == "round"
              and math.hypot(candidate.node.x - hero[0], candidate.node.y - hero[1] - 90) < 18]
    if rounds:
        return min(rounds, key=lambda candidate: math.hypot(
            candidate.node.x - hero[0], candidate.node.y - hero[1] - 90,
        ))
    # 完成勾已确认头像脚下节点；动画可使圆环漏检，但不应丢掉已确认的锚点。
    return _NavigationNode(MapNode(hero[0], hero[1] + 90, 48), "round") if completed else None


def _diamond_target_visible(image: np.ndarray, node: MapNode) -> bool:
    x, y = node.center
    if x < 80 or x + 80 >= 1920 or y < 80 or y + 60 >= 1080:
        return False
    patch = image[y - 55:y + 56, x - 55:x + 56].astype(np.int16)
    yy, xx = np.ogrid[-55:56, -55:56]
    rim = (np.abs(xx) + np.abs(yy) >= 43) & (np.abs(xx) + np.abs(yy) <= 55)
    cyan = (patch[:, :, 0] > 170) & (patch[:, :, 1] > 155) & (patch[:, :, 0] - patch[:, :, 2] > 25)
    if any(float(cyan[rim & quadrant].mean()) < 0.12 for quadrant in (
        (xx < 0) & (yy < 0), (xx >= 0) & (yy < 0),
        (xx < 0) & (yy >= 0), (xx >= 0) & (yy >= 0),
    )):
        return False
    center = image[y - 9:y + 9, x - 9:x + 9]
    # 菱形中心只有空底或旅行箭头；锁等有轮廓的内容不能当作空底。
    center_visible = (int((cv2.Canny(center, 70, 140) > 0).sum()) <= 8
                      or _navigation_marker_visible(image, "map_first_power_arrow", x, y))
    return (float(center.std()) >= 4 and center_visible
            and _unlocked_unfinished_center(image, node))


def _unlocked_unfinished_center(image: np.ndarray, node: MapNode) -> bool:
    x, y = node.center
    lock = _map_lock_template()
    center = cv2.cvtColor(image[y - 30:y + 31, x - 30:x + 31], cv2.COLOR_BGR2GRAY)
    return (lock is not None and center.shape == (61, 61)
            and cv2.matchTemplate(center, lock, cv2.TM_CCOEFF_NORMED).max() < 0.8
            and not _checkmark_visible(image, (x - 35, y - 30, x + 36, y + 31)))


def _route_origin(anchor: MapNode, hero: tuple[int, int], target: MapNode) -> MapNode:
    """只有实际穿过头像的边才跳过已知遮挡，方向和节点类型不参与判断。"""
    dx, dy = target.x - anchor.x, target.y - anchor.y
    length = math.hypot(dx, dy)
    if not length:
        return anchor
    hx, hy = hero[0] - anchor.x, hero[1] - anchor.y
    projection = (hx * dx + hy * dy) / length
    perpendicular_sq = hx * hx + hy * hy - projection * projection
    if 0 < projection < length and perpendicular_sq < 50 ** 2:
        hidden_until = projection + math.sqrt(50 ** 2 - perpendicular_sq)
        return MapNode(anchor.x, anchor.y, max(anchor.radius, math.ceil(hidden_until)))
    return anchor


def _connected_navigation_nodes(
    image: np.ndarray, anchor: MapNode, hero: tuple[int, int],
    candidates: list[_NavigationNode], mask: np.ndarray,
) -> list[MapNode]:
    """所有节点共用：同一亮线连通域、连续边、可见起点与有效目标。"""
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    distances = {}
    found = []
    for candidate in candidates:
        node = candidate.node
        if not 120 <= math.hypot(node.x - anchor.x, node.y - anchor.y) <= 800:
            continue
        if candidate.shape == "diamond" and not _diamond_target_visible(image, node):
            continue
        if candidate.shape == "display" and not _unlocked_unfinished_center(image, node):
            continue
        endpoint = candidate.connection or node
        origin = _route_origin(anchor, hero, endpoint)
        if not _node_edge_visible(image, origin, endpoint):
            continue
        extent = origin.radius + 18
        x1, x2 = max(0, anchor.x - extent), min(1920, anchor.x + extent + 1)
        y1, y2 = max(0, anchor.y - extent), min(1080, anchor.y + extent + 1)
        yy, xx = np.ogrid[y1:y2, x1:x2]
        nearby = np.unique(labels[y1:y2, x1:x2][
            (xx - anchor.x) ** 2 + (yy - anchor.y) ** 2 <= extent ** 2])
        for label in nearby:
            if label == 0 or stats[label, cv2.CC_STAT_AREA] < 300:
                continue
            if label not in distances:
                distances[label] = cv2.distanceTransform(
                    (labels != label).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE,
                )
            route_end = (_component_port_contact(labels, int(label), origin, endpoint)
                         if candidate.connection is not None else endpoint)
            if route_end is None or not _component_between_nodes(distances[label], origin, route_end):
                continue
            if candidate.shape == "round" and not _lit_unfinished_ring(
                image, labels, int(label), node.x, node.y, node.radius,
                min_cyan=0.15, min_connected_cyan=120,
            ):
                continue
            if candidate.shape == "diamond" and not _component_touches_node(
                image, labels, int(label), endpoint,
            ):
                continue
            region = image[max(0, node.y - node.radius - 18):min(1080, node.y + node.radius + 19),
                           max(0, node.x - node.radius - 18):min(1920, node.x + node.radius + 19)]
            b, g, r = (region[:, :, i].astype(np.int16) for i in range(3))
            score = float(((b > 165) & (g > 145) & (b - r > 35) & (g - r > 20)).mean())
            found.append((candidate.shape != "display", score, node))
            break
    result = []
    for _, _, node in sorted(found, key=lambda item: item[:2], reverse=True):
        if all(math.hypot(node.x - old.x, node.y - old.y) >=
               (120 if node.needs_reveal or old.needs_reveal else 70) for old in result):
            result.append(node)
    return result


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


def _component_port_contact(
    labels: np.ndarray, label: int, origin: MapNode, port: MapNode,
) -> MapNode | None:
    """展示框的入边可偏离中心；以同一亮线在端口内的末端核验连续性。"""
    extent = port.radius + 6
    x0, x1 = max(0, port.x - extent), min(labels.shape[1], port.x + extent + 1)
    y0, y1 = max(0, port.y - extent), min(labels.shape[0], port.y + extent + 1)
    yy, xx = np.ogrid[y0:y1, x0:x1]
    contact = ((labels[y0:y1, x0:x1] == label)
               & ((xx - port.x) ** 2 + (yy - port.y) ** 2 <= extent ** 2))
    ys, xs = np.where(contact)
    if not len(xs):
        return None
    xs, ys = xs + x0, ys + y0
    end = int(np.argmax((xs - origin.x) ** 2 + (ys - origin.y) ** 2))
    return MapNode(int(xs[end]), int(ys[end]), 0)


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


@cache
def _gold_node_template() -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure/map_gold_node_visible.png")))


@cache
def _navigation_marker_template(name: str) -> np.ndarray | None:
    return cv2.imread(str(Path("assets/adventure") / f"{name}.png"))


def _navigation_marker_visible(image: np.ndarray, name: str, x: int, y: int) -> bool:
    template = _navigation_marker_template(name)
    if template is None or x < 35 or y < 35 or x + 35 >= 1920 or y + 35 >= 1080:
        return False
    region = image[y - 35:y + 35, x - 35:x + 35]
    _, score, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(
        region, template, cv2.TM_CCOEFF_NORMED,
    ))
    h, w = template.shape[:2]
    actual = region[dy:dy + h, dx:dx + w]
    return bool(score >= 0.93 and float((cv2.absdiff(actual, template) > 45).mean()) < 0.08)


def _current_node_halo_visible(image: np.ndarray, hero: tuple[int, int]) -> bool:
    """核实英雄脚下圆节点的蓝环及可见中心，不能只凭零散亮色定位。"""
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


def _component_touches_node(
    image: np.ndarray, labels: np.ndarray, label: int, anchor: MapNode,
) -> bool:
    """核对亮线连通域贴近节点的可见金色或蓝白色边缘。"""
    extent = anchor.radius + 30
    if (anchor.x < extent or anchor.y < extent or anchor.x + extent >= image.shape[1]
            or anchor.y + extent >= image.shape[0]):
        return False
    x0, x1 = anchor.x - extent, anchor.x + extent + 1
    y0, y1 = anchor.y - extent, anchor.y + extent + 1
    region = image[y0:y1, x0:x1]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    gold = cv2.inRange(hsv, (15, 120, 120), (40, 255, 255))
    blue, green, red = (region[:, :, i].astype(np.int16) for i in range(3))
    cyan = (blue > 170) & (green > 155) & (blue - red > 25)
    gold[cyan] = 255
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
    if any(float(cyan[annulus & quadrant].mean()) < 0.05 for quadrant in (
        (xx < 0) & (yy < 0), (xx >= 0) & (yy < 0),
        (xx < 0) & (yy >= 0), (xx >= 0) & (yy >= 0),
    )):
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
    # 大块均匀遮挡可能让 Hough 圆心偏向残留环；不能只检查偏移后的中心。
    gray = cv2.cvtColor(visible, cv2.COLOR_BGR2GRAY).astype(np.float64)
    variance = cv2.boxFilter(gray * gray, -1, (15, 15)) - cv2.boxFilter(gray, -1, (15, 15)) ** 2
    count, _, stats, _ = cv2.connectedComponentsWithStats((variance < 0.01).astype(np.uint8))
    if count > 1 and int(stats[1:, cv2.CC_STAT_AREA].max()) >= 400:
        return False
    return not _checkmark_visible(image, (x - 35, y - 30, x + 36, y + 31))


def next_node_by_path(
    image: np.ndarray,
    *,
    hero: tuple[int, int] | None = None,
    rng: random.Random | None = None,
) -> MapNode | None:
    """保留诊断入口，使用统一算法返回一个已核实可达节点。"""
    if hero is None:
        return None
    return next_node(image, hero=hero, rng=rng)
