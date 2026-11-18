import cv2
import numpy as np

from lorwright.core.perceive.hand import (
    Badge,
    _expanded_drag_point,
    _visible_playable_unit,
)


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
