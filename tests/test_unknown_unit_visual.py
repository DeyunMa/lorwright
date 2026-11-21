import cv2
import numpy as np

from lorwright.core.perceive.hand import (
    Badge,
    _expanded_drag_point,
    _visible_playable_unit,
)
from tools.test_data import fixtures_root


def _chip(image, x, y, warm=False):
    """展开的数值角标：深色六边形底，中心一枚亮白或暖色字素。"""
    cv2.circle(image, (x, y), 16, (20, 20, 20), -1)
    color = (60, 140, 220) if warm else (240, 240, 240)
    cv2.rectangle(image, (x - 2, y - 7), (x + 2, y + 7), color, -1)


def test_expanded_drag_rejects_crowding_and_screen_clipping():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    badge = Badge((1393, 855), 1.0)
    assert _expanded_drag_point(image, badge, [badge]) == (1457, 960)
    assert _expanded_drag_point(image, badge, [badge, Badge((1550, 855), 1.0)]) is None
    fan = [Badge((362 + 120 * i, 855), 1.0) for i in range(6)]
    assert _expanded_drag_point(image, fan[0], fan) == (426, 960)
    assert _expanded_drag_point(image, fan[0], [fan[0], Badge((470, 855), 1.0), *fan[2:]]) is None
    assert _expanded_drag_point(image[:950], badge, [badge]) is None
    assert _expanded_drag_point(image[:, :1450], badge, [badge]) is None


def test_glow_alone_obscured_and_adjacent_card_are_not_evidence():
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    badge = Badge((1393, 855), 1.0)
    assert not _visible_playable_unit(image, badge, [badge])
    blue_line = np.zeros_like(image)
    cv2.line(blue_line, (1413, 822), (1612, 847), (255, 150, 0), 5)
    assert not _visible_playable_unit(blue_line, badge, [badge])


def test_stat_chip_pair_confirms_unit_type():
    """左下力量 + 右下血量角标同时检出 → 单位类型确认；缺一即弃权。"""
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    badge = Badge((900, 800), 1.0)
    _chip(image, 888, 975)
    _chip(image, 1036, 985, warm=True)
    assert _visible_playable_unit(image, badge, [badge])

    no_health = np.zeros_like(image)
    _chip(no_health, 888, 975)
    assert not _visible_playable_unit(no_health, badge, [badge])
    no_power = np.zeros_like(image)
    _chip(no_power, 1036, 985, warm=True)
    assert not _visible_playable_unit(no_power, badge, [badge])


def test_stat_chip_covered_by_neighbor_or_screen_abstains():
    """窄间距/边缘裁切下角标不可独立验证 → 类型未证实。"""
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    badge = Badge((900, 800), 1.0)
    _chip(image, 888, 975)
    _chip(image, 1036, 985, warm=True)
    # 右邻卡徽章在 168px 覆盖距离内：其左缘盖住本卡右下角标。
    crowded = [badge, Badge((1050, 800), 1.0)]
    assert not _visible_playable_unit(image, badge, crowded)
    # 左邻卡右缘盖住左下角标。
    crowded_left = [Badge((800, 800), 1.0), badge]
    assert not _visible_playable_unit(image, badge, crowded_left)
    # 角标探出屏幕下缘（徽章过低的扇形边缘卡）。
    edge = np.zeros_like(image)
    low = Badge((900, 950), 1.0)
    _chip(edge, 888, 1085)
    _chip(edge, 1036, 1070, warm=True)
    assert not _visible_playable_unit(edge, low, [low])


def test_narrow_fan_corners_covered_on_live_frame_abstains():
    """实机窄间距扇形：全部数值角标被邻牌覆盖或屏幕裁切 → 全部弃权。"""
    path = fixtures_root() / "screens/f1-narrow-hand-covered-chips-20261121.png"
    image = cv2.imread(str(path))
    assert image is not None, f"missing fixture {path}"
    from lorwright.core.models import Rect
    from lorwright.core.perceive.hand import find_badges_expanded
    badges = find_badges_expanded(image, Rect(280, 680, 1640, 400))
    assert len(badges) == 7
    assert not any(_visible_playable_unit(image, b, badges) for b in badges)
