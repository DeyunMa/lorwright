"""结算页实图识别；这些截图不是对完整胜利流程的实机验收。"""

from pathlib import Path

import cv2
import pytest

from lorwright.core.models import UIState
from lorwright.core.perceive.buttons import find_continue_button
from lorwright.core.perceive.result_screen import (
    is_adventure_victory,
    is_task_reward,
    result_screen,
)
from lorwright.core.perceive.ui_state import UIStateDetector

FIXTURES = Path("tests/fixtures/continue")


def _load(name):
    image = cv2.imread(str(FIXTURES / name))
    assert image is not None
    return cv2.resize(image, (1920, 1080), interpolation=cv2.INTER_AREA)


@pytest.mark.parametrize(("name", "expected"), [
    ("f1-missions-20261113.jpg", "missions"),
    ("f1-missions-20261115.png", "missions"),
    ("f1-vault-20261113.jpg", "vault"),
    ("vault_experience.png", "vault"),
])
def test_results_require_two_visible_features(name, expected):
    image = _load(name)
    assert result_screen(image) == expected
    assert UIStateDetector().detect(image) is UIState.BATTLE_END
    assert result_screen((image * 0.6).astype("uint8")) is None
    if expected == "missions":
        image[205:255, 548:759] = 0
    else:
        image[40:133, 1178:1367] = 0
    assert result_screen(image) is None


def test_mission_structure_survives_changed_tasks_values_and_rewards():
    image = _load("f1-missions-20261115.png")
    image[275:1050, :1250] = 0  # 任务内容、进度和奖励可变化
    image[125:1050, 1250:] = 0  # 经验数值及宝库可变化
    assert result_screen(image) == "missions"
    image[46:126, 1496:1683] = 0
    assert result_screen(image) is None


def test_mission_page_has_no_confirmed_continue_but_vault_does():
    assert find_continue_button(_load("f1-missions-20261113.jpg")) is None
    button = find_continue_button(_load("f1-vault-20261113.jpg"))
    assert button is not None and abs(button.center[0] - 1270) < 20


@pytest.mark.parametrize("name", ["f1-adventure-victory-20261116.png", "challenge_result.png"])
def test_adventure_victory_requires_all_three_visible_labels(name):
    image = _load(name)
    assert is_adventure_victory(image)
    assert not is_adventure_victory((image * 0.6).astype("uint8"))
    assert not is_adventure_victory(image[:540, :960])
    for x1, y1, x2, y2 in ((205, 96, 288, 146), (182, 266, 321, 315),
                             (182, 389, 321, 438)):
        obscured = image.copy()
        obscured[y1:y2, x1:x2] = 0
        assert not is_adventure_victory(obscured)


def test_task_reward_requires_fixed_title_and_icon_not_task_or_prize():
    image = _load("f1-task-completed-20261116.png")
    assert is_task_reward(image)
    assert not is_task_reward((image * 0.6).astype("uint8"))
    assert not is_task_reward(image[:540, :960])
    for bounds in ((183, 84, 737, 159), (69, 89, 180, 210)):
        obscured = image.copy()
        x1, y1, x2, y2 = bounds
        obscured[y1:y2, x1:x2] = 0
        assert not is_task_reward(obscured)
    image[160:, 185:] = 0  # 抹去任务名、奖励种类/数量及按钮，不影响页面身份。
    assert is_task_reward(image)
    assert not is_task_reward(_load("f1-missions-20261115.png"))
    assert not is_task_reward(_load("f1-adventure-victory-20261116.png"))


def test_adventure_victory_does_not_depend_on_hero_grade_name_or_values():
    image = _load("f1-adventure-victory-20261116.png")
    image[:104] = 0  # 冒险名称和评级顶部
    image[104:250, :205] = 0  # 评级其余部分
    image[145:250] = 0  # 账号
    image[315:389, 180:600] = 0  # 完成时间值
    image[438:] = 0  # 最短时间值、英雄、资源和继续按钮
    image[:, 600:] = 0  # 卡牌与英雄详情
    assert is_adventure_victory(image)


@pytest.mark.parametrize("name", ["f1-missions-20261115.png", "vault_experience.png",
                                  "challenge_experience.png", "victory_banner.png"])
def test_intermediate_results_are_not_adventure_victory(name):
    assert not is_adventure_victory(_load(name))


@pytest.mark.parametrize("name", ["challenge_result.png", "challenge_experience.png",
                                  "victory_banner.png"])
def test_unrelated_result_screens_are_not_assumed_to_be_vault_or_missions(name):
    assert result_screen(_load(name)) is None
