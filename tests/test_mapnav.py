"""mapnav 在真實地圖截圖上的回歸驗證。

Fixtures 是 2026-11-05 月度挑戰 3 的實泊截圖（960x540 預覽橁式）。
"""

from pathlib import Path

import cv2
import pytest

from lorwright.perceive.mapnav import blue_glow_mask, detect_nodes, hero_node

FIXTURES = Path(__file__).parent / "fixtures" / "mapnav"
CASES = ["m3-re", "m3-g7", "m3-shopD"]


def load(name):
    image = cv2.imread(str(FIXTURES / f"{name}.jpg"))
    assert image is not None, f"missing fixture {name}"
    return image


@pytest.mark.parametrize("name", CASES)
def test_hero_node_detected(name):
    image = load(name)
    mask = blue_glow_mask(image)
    nodes = detect_nodes(image)
    assert nodes, name
    hero = hero_node(nodes, mask)
    assert hero is not None, name
    # 英雄節點在三张圖裡都在上半屏中部區域
    assert 400 < hero.x < 700, (name, hero)
    assert 100 < hero.y < 260, (name, hero)

