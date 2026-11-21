import cv2
import numpy as np

from lorwright.core.models import Rect
from lorwright.core.perceive.hand import (
    Badge,
    _arched_frame,
    _blue_straight_top_frame,
    _expanded_drag_point,
    _spell_marker,
    _visible_playable_unit,
    find_badges_expanded,
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


def _expanded_badges(image):
    return find_badges_expanded(image, Rect(280, 680, 1640, 400))


def _restored_crop(relative: str) -> np.ndarray:
    crop = cv2.imread(str(fixtures_root() / relative))
    assert crop is not None, relative
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    image[:, 320:] = crop
    return image


def test_wide_fan_unit_without_tribe_banner_uses_blue_top_frame():
    """宽间距展开手牌：无种族横幅且角标不可见的单位，凭蓝色直顶框确认。"""
    image = _restored_crop("screens/f1-handoff-readiness-stop-20261117.png")
    badges = _expanded_badges(image)
    assert len(badges) == 6
    got = [_visible_playable_unit(image, b, badges) for b in badges]
    assert got == [False, False, True, True, True, True]
    # 邻牌收窄到 <210px 时蓝线通道拒绝触发。
    target = badges[2]
    crowded = [target, Badge((target.center[0] + 180, target.center[1]), 1.0)]
    assert not _visible_playable_unit(image, target, crowded)


def test_spell_veto_overrides_blue_straight_top_frame():
    """法术星形标记与拱形框否决均优先于宽距蓝色直顶框证据。"""
    image = _restored_crop("screens/f1-handoff-readiness-stop-20261117.png")
    badges = _expanded_badges(image)
    spell, target = badges[1], badges[2]
    assert _blue_straight_top_frame(image, target, badges)

    marked = image.copy()
    sx, sy = spell.center
    tx, ty = target.center
    h = min(135, 1080 - (sy + 25), 1080 - (ty + 25))
    marked[ty + 25:ty + 25 + h, tx - 62:tx + 70] = image[sy + 25:sy + 25 + h, sx - 62:sx + 70]
    assert _blue_straight_top_frame(marked, target, badges)
    assert _spell_marker(marked, target)
    assert not _visible_playable_unit(marked, target, badges)

    arched = np.zeros((1080, 1920, 3), dtype=np.uint8)
    badge = Badge((900, 800), 1.0)
    cv2.line(arched, (920, 795), (1120, 795), (255, 160, 0), 4)
    cv2.rectangle(arched, (925, 810), (1115, 822), (180, 180, 180), -1)
    cv2.rectangle(arched, (950, 750), (1030, 785), (220, 220, 220), -1)
    assert _blue_straight_top_frame(arched, badge, [badge])
    assert _arched_frame(arched, badge)
    assert not _visible_playable_unit(arched, badge, [badge])


def test_narrow_fan_card_types_on_live_frame():
    """窄间距实机扇形：砰砰法术被标记/拱形否决，其余方形框确认为单位。"""
    image = cv2.imread(str(fixtures_root()
                           / "screens/f1-narrow-hand-covered-chips-20261121.png"))
    assert image is not None
    badges = _expanded_badges(image)
    assert len(badges) == 7
    got = [_visible_playable_unit(image, b, badges) for b in badges]
    assert got == [True, True, False, True, True, True, True]


def test_mana_token_fan_splits_spells_and_units():
    """同一帧内 5 张砰砰法术全部否决，2 张方形框单位确认。"""
    image = cv2.imread(str(fixtures_root()
                           / "screens/f1-weekly-mana-token-20261116.png"))
    assert image is not None
    badges = _expanded_badges(image)
    assert len(badges) == 7
    got = [_visible_playable_unit(image, b, badges) for b in badges]
    assert got == [False, False, False, False, False, True, True]


def test_all_spell_fan_never_confirms_unit():
    """全法术扇形（砰砰+火箭）：任何一张都不得确认单位。"""
    image = cv2.imread(str(fixtures_root()
                           / "jinx/battle-two-rockets-20261114.png"))
    assert image is not None
    badges = _expanded_badges(image)
    assert len(badges) == 6
    assert not any(_visible_playable_unit(image, b, badges) for b in badges)
