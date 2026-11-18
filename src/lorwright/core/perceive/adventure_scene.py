"""对局外画面的保守识别；无法证明画面类型时不授权点击。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.models import Rect
from lorwright.core.perceive.panels import action_button

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


def reward_timeout_continue(image: np.ndarray) -> Rect | None:
    """仅识别已采样的奖励详情超时弹窗及其继续按钮。"""
    if image.shape != (1080, 1920, 3):
        return None
    if (_matches(image, "reward_timeout_message", (630, 420, 1280, 510), 0.93)
            and _matches(image, "reward_timeout_continue", (890, 710, 1030, 800), 0.93)):
        return Rect(810, 710, 300, 95)
    return None


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
    # 两种控件外观位置一致；放大后加号变灰，仍须核验完整形状和字迹亮度。
    plus_mask = template[30:85, 15:70] >= 170
    minus_mask = template[115:160, 15:70] >= 85
    if not plus_mask.any() or not minus_mask.any():
        return False
    plus = region[30:85, 15:70][plus_mask]
    minus = region[115:160, 15:70][minus_mask]
    for reference, plus_min in ((template, 150), (_template("map_zoom_expanded"), 140)):
        if reference is None or reference.shape != template.shape:
            continue
        # 只匹配控件内部，地图背景变化不影响控件判断。
        score = cv2.matchTemplate(region[12:-12, 12:-12], reference[12:-12, 12:-12],
                                  cv2.TM_CCOEFF_NORMED)[0, 0]
        if score >= 0.9 and np.percentile(plus, 10) >= plus_min and np.percentile(minus, 10) >= 100:
            return True
    return False


def is_map(image: np.ndarray) -> bool:
    """同时识别地图返回键与可见缩放控件，不能仅凭蓝色像素认地图。"""
    return (_matches(image, "map_back", (80, 65, 118, 105), 0.9)
            and _map_zoom_visible(image))


def is_battle_detail(image: np.ndarray) -> bool:
    return (_matches(image, "map_back", (80, 65, 118, 105), 0.9)
            and _matches(image, "battle_detail", (1572, 133, 1703, 166), 0.9))


def is_completed_panel(image: np.ndarray) -> bool:
    return is_map(image) and _matches(image, "completed", (400, 300, 1100, 650), 0.9)


def find_resume_adventure_button(image: np.ndarray) -> Rect | None:
    """在冒险选择页识别可点击的「繼續冒險」，不依赖具体冒险插画。"""
    if image.shape != (1080, 1920, 3):
        return None
    if not _matches(image, "map_back", (60, 40, 140, 125), 0.9):
        return None
    button = action_button(image)
    if button is None or button.x < 1200 or button.y < 850:
        return None
    return button if button_is(image, button, "resume_adventure") else None


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


def gold_chest_collect_button(image: np.ndarray) -> Rect | None:
    """金币宝箱标题与取走宝藏文字须同时完整可见，不推断奖励到账。"""
    if _visible_patch(image, "gold_chest_title", (545, 345, 805, 430)) is None:
        return None
    return _visible_patch(image, "gold_chest_collect", (1320, 960, 1565, 1050))


def item_chest_leave_button(image: np.ndarray) -> Rect | None:
    """宝箱标题与离开文字须同时明亮完整，不依赖候选卡牌身份。"""
    if _visible_patch(image, "item_chest_title", (545, 345, 805, 430)) is None:
        return None
    return _visible_patch(image, "shop_leave", (630, 920, 760, 990))


@dataclass(frozen=True)
class WeeklyAdventure:
    target: Rect
    stars: float | None


def _visible_patch(image: np.ndarray, name: str, bounds: tuple[int, int, int, int],
                   threshold: float = 0.94) -> Rect | None:
    """模板定位后还检查亮度和像素残差，排除遮罩及部分遮挡。"""
    template = _template(name)
    if template is None or image.shape != (1080, 1920, 3):
        return None
    x1, y1, x2, y2 = bounds
    if x1 < 0 or y1 < 0 or x2 > 1920 or y2 > 1080:
        return None
    gray = cv2.cvtColor(image[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    h, w = template.shape
    if gray.shape[0] < h or gray.shape[1] < w:
        return None
    scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    patch = gray[y:y + h, x:x + w]
    bright = template >= 130
    if (score < threshold or not bright.any()
            or np.mean(cv2.absdiff(patch, template)[bright]) > 15
            or np.percentile(patch[bright], 10) < 110):
        return None
    return Rect(x1 + x, y1 + y, w, h)


def _world_controls(image: np.ndarray) -> bool:
    return (_visible_patch(image, "world_back", (65, 45, 140, 125)) is not None
            and _map_zoom_visible(image))


def find_weekly_entry(image: np.ndarray) -> Rect | None:
    """世界地图上同时看见每周文字和紫色图标才授权入口。"""
    if not _world_controls(image):
        return None
    label = _visible_patch(image, "weekly_entry", (350, 150, 1750, 940))
    if label is None:
        return None
    # 图标相对文字定位，地图上的入口可移动。
    icon = _visible_patch(image, "weekly_icon",
                          (label.x + label.w + 10, label.y - 50,
                           label.x + label.w + 145, label.y + 75))
    return icon


def _weekly_markers(image: np.ndarray, name: str) -> list[Rect]:
    template = _template("weekly_completed_check" if name == "weekly_completed" else name)
    if template is None or not _world_controls(image):
        return []
    if name == "weekly_completed":
        # 仅核验绿色勾字形，关卡肖像不是完成标记的一部分。
        gray = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV),
                           (35, 80, 110), (90, 255, 255))
    else:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(gray, template, cv2.TM_CCOEFF_NORMED)
    h, w = template.shape
    hits = []
    for _ in range(5):
        _, score, _, (x, y) = cv2.minMaxLoc(scores)
        if score < 0.88:
            break
        bright = template >= 170
        patch = gray[y:y + h, x:x + w]
        if not bright.any() or np.percentile(patch[bright], 10) < 150:
            return []
        hits.append(Rect(x, y, w, h))
        scores[max(0, y - h):y + h, max(0, x - w):x + w] = -1
    return sorted(hits, key=lambda hit: (hit.y, hit.x))


def _rating_matches(image: np.ndarray, name: str, bounds: tuple[int, int, int, int]) -> bool:
    hit = _visible_patch(image, name, bounds)
    if hit is None:
        return False
    template = _template(name)
    # 星标占徽章大部分面积；单独核对数字及小数点，不能让星标掩盖未知数字。
    patch = cv2.cvtColor(image[hit.y:hit.y + hit.h, hit.x:hit.x + hit.w],
                         cv2.COLOR_BGR2GRAY)
    expected = template[44:73, 18:84] >= 160
    actual = patch[44:73, 18:84] >= 160
    union = np.count_nonzero(expected | actual)
    if not union or np.count_nonzero(expected & actual) / union < 0.94:
        return False
    # 小数点面积很小，整体相似度会掩盖其缺失；每个笔画连通块都必须在。
    count, labels, stats, _ = cv2.connectedComponentsWithStats(expected.astype(np.uint8))
    for component in range(1, count):
        mask = labels == component
        if stats[component, cv2.CC_STAT_AREA] >= 3 and np.mean(actual[mask]) < 0.95:
            return False
    return True


def is_weekly_list(image: np.ndarray) -> bool:
    """三个时钟或完成勾齐全即为每周列表，包含全部已完成的情况。"""
    return len(_weekly_markers(image, "weekly_clock")) + len(
        _weekly_markers(image, "weekly_completed"),
    ) == 3


def recognize_weekly_adventures(image: np.ndarray) -> tuple[WeeklyAdventure, ...] | None:
    """动态定位未完成时钟，结合完成勾核对三个位置，再读取星级。

    当前视觉字库仅含实拍 1.5 和 2，未采样数字一律弃权。没有借用只读
    整数的 DigitReader，以免小数点被分割规则滤掉后错误排序。
    """
    clocks = _weekly_markers(image, "weekly_clock")
    completed = _weekly_markers(image, "weekly_completed")
    if not clocks or len(clocks) + len(completed) != 3:
        return None
    adventures = []
    for clock in clocks:
        bounds = (clock.x - 40, clock.y + 109, clock.x + 70, clock.y + 197)
        values = {
            value for name, value in (("weekly_rating_2_top", 2.0),
                                      ("weekly_rating_2_left", 2.0),
                                      ("weekly_rating_2_current", 2.0),
                                      ("weekly_rating_2_remaining_left", 2.0),
                                      ("weekly_rating_1_5", 1.5))
            if _rating_matches(image, name, bounds)
        }
        # 点击动态定位的关卡肖像中心，坐标只来自当前帧的时钟标记。
        adventures.append(WeeklyAdventure(Rect(clock.x - 15, clock.y + 45, 60, 50),
                                           values.pop() if len(values) == 1 else None))
    return tuple(adventures)


def weekly_detail_stars(image: np.ndarray) -> float | None:
    """只接受已采样的每周详情、难度星标和完整小数。"""
    if (_visible_patch(image, "world_back", (65, 45, 140, 125)) is None
            or _visible_patch(image, "weekly_detail_label", (1385, 108, 1555, 150)) is None
            or not any(_visible_patch(image, name, (1385, 295, 1505, 375)) is not None
                       for name in ("weekly_detail_difficulty", "weekly_detail_difficulty_2"))):
        return None
    ratings = [value for name, value in (("weekly_detail_rating", 1.5),
                                        ("weekly_detail_rating_2", 2.0))
               if _visible_patch(image, name, (1444, 340, 1487, 368), threshold=0.99) is not None]
    return ratings[0] if len(ratings) == 1 else None


def find_weekly_start(image: np.ndarray) -> Rect | None:
    if weekly_detail_stars(image) is None:
        return None
    button = action_button(image)
    if button is None or button.x < 1300 or button.y < 900:
        return None
    if _visible_patch(image, "weekly_start", (button.x, button.y,
                                             button.x + button.w, button.y + button.h)) is None:
        return None
    return button


def button_is(image: np.ndarray, button: Rect, name: str) -> bool:
    """金色外观不足以区分按钮：还需匹配按钮上的文字。"""
    return _matches(image, name, (button.x, button.y, button.x + button.w, button.y + button.h))
