"""对局外画面的保守识别；无法证明画面类型时不授权点击。"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.models import Rect

_ASSETS = Path("assets/adventure")


@cache
def _template(name: str) -> np.ndarray | None:
    return cv2.imread(str(_ASSETS / f"{name}.png"), cv2.IMREAD_GRAYSCALE)


@cache
def _home_label_gold_mask() -> np.ndarray | None:
    template = cv2.imread(str(_ASSETS / "home_poc_label.png"))
    if template is None:
        return None
    return cv2.inRange(cv2.cvtColor(template, cv2.COLOR_BGR2HSV),
                       (8, 80, 145), (40, 255, 255))


def _matches(image: np.ndarray, name: str, rect: tuple[int, int, int, int],
             threshold: float = 0.85) -> bool:
    tpl = _template(name)
    if tpl is None or image.shape[:2] != (1080, 1920):
        return False
    x1, y1, x2, y2 = rect
    region = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
        return False
    return float(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED).max()) >= threshold


def find_home_adventure_entry(image: np.ndarray) -> Rect | None:
    """定位主页卡片的「快來玩 英雄之路」文字；不明确时弃权。

    输入输出均为 1920×1080 设计坐标。只匹配卡片文字而不依赖经常
    变化的宣传画；文字必须仍有明亮的金色，避免弹窗遮罩下误点击。
    调用方点击已识别文字的位置，而不是可能被遮挡的卡片中心。
    """
    if image.ndim != 3 or image.shape != (1080, 1920, 3):
        return None
    template = _template("home_poc_label")
    if template is None:
        return None
    x1, y1, x2, y2 = 1485, 835, 1799, 904
    region = image[y1:y2, x1:x2]
    if template.shape[0] > region.shape[0] or template.shape[1] > region.shape[1]:
        return None
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if score < 0.83:
        return None
    h, w = template.shape
    hsv = cv2.cvtColor(region[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
    bright_gold = cv2.inRange(hsv, (8, 80, 145), (40, 255, 255))
    if np.count_nonzero(bright_gold) / bright_gold.size < 0.08:
        return None
    # 检查模板实际字迹的位置，避免弹窗遮暗后被另一层明亮金色装饰蒙混。
    gold_mask = _home_label_gold_mask()
    if gold_mask is None or gold_mask.shape != (h, w) or not np.any(gold_mask):
        return None
    if cv2.mean(hsv[:, :, 2], mask=gold_mask)[0] < 140:
        return None
    # 检查每条字迹有足够的亮色，避免文字局部被遮挡时点击。
    count, labels, stats, _ = cv2.connectedComponentsWithStats(gold_mask)
    for component_id in range(1, count):
        cx, cy, cw, ch, area = stats[component_id]
        if area < 12:
            continue
        component = (labels[cy:cy + ch, cx:cx + cw] == component_id).astype(np.uint8)
        value = hsv[cy:cy + ch, cx:cx + cw, 2]
        if cv2.mean(value, mask=component)[0] < 130:
            return None
    return Rect(x1 + x, y1 + y, w, h)


def _map_zoom_visible(image: np.ndarray) -> bool:
    template = _template("map_zoom")
    if template is None or template.shape != (190, 84) or image.shape != (1080, 1920, 3):
        return False
    region = cv2.cvtColor(image[240:430, 1780:1864], cv2.COLOR_BGR2GRAY)
    # 控件四周的背景随地图变化；只匹配控件内部，避免背景导致漏识别。
    score = cv2.matchTemplate(region[12:-12, 12:-12], template[12:-12, 12:-12],
                              cv2.TM_CCOEFF_NORMED)[0, 0]
    if score < 0.9:
        return False
    # 相关系数对整体变暗不敏感；检查加减号字迹，排除已验证的遮暗和遮挡。
    plus_mask = template[30:85, 15:70] >= 170
    minus_mask = template[115:160, 15:70] >= 85
    if not plus_mask.any() or not minus_mask.any():
        return False
    plus = region[30:85, 15:70][plus_mask]
    minus = region[115:160, 15:70][minus_mask]
    return bool(np.percentile(plus, 10) >= 150 and np.percentile(minus, 10) >= 100)


def is_map(image: np.ndarray) -> bool:
    """同时识别地图返回键与可见缩放控件，不能仅凭蓝色像素认地图。"""
    return (_matches(image, "map_back", (80, 65, 118, 105), 0.9)
            and _map_zoom_visible(image))


def is_battle_detail(image: np.ndarray) -> bool:
    return (_matches(image, "map_back", (80, 65, 118, 105), 0.9)
            and _matches(image, "battle_detail", (1572, 133, 1703, 166), 0.9))


def is_completed_panel(image: np.ndarray) -> bool:
    return is_map(image) and _matches(image, "completed", (400, 300, 1100, 650), 0.9)


def shop_leave_button(image: np.ndarray) -> Rect | None:
    """商店标题和明亮的离开文字同时可见才允许离开。"""
    if image.shape != (1080, 1920, 3):
        return None
    if not _matches(image, "shop_title", (545, 345, 715, 430), 0.94):
        return None
    if not _matches(image, "shop_leave", (630, 970, 760, 1040), 0.94):
        return None
    # CCOEFF 对整体变暗不敏感，不能点击被遮罩的商店。
    region = cv2.cvtColor(image[984:1025, 648:735], cv2.COLOR_BGR2GRAY)
    template = _template("shop_leave")
    if template is None or region.shape != template.shape:
        return None
    bright = template > 180
    if not bright.any() or float(region[bright].mean()) < 160:
        return None
    return Rect(648, 984, 87, 41)


def button_is(image: np.ndarray, button: Rect, name: str) -> bool:
    """金色外观不足以区分按钮：还需匹配按钮上的文字。"""
    return _matches(image, name, (button.x, button.y, button.x + button.w, button.y + button.h))
