
import cv2
import numpy as np

from lorwright.core.perceive.adventure_scene import reward_timeout_continue
from tools.test_data import fixtures_root


def test_reward_timeout_requires_message_and_button():
    image = cv2.imread(str(fixtures_root() / "reward_timeout/f1.png"))
    assert image is not None
    assert reward_timeout_continue(image).center == (960, 757)
    for region in ((650, 437, 1255, 495), (910, 735, 1008, 782)):
        modified = image.copy()
        x1, y1, x2, y2 = region
        modified[y1:y2, x1:x2] = 0
        assert reward_timeout_continue(modified) is None
    assert reward_timeout_continue(np.zeros_like(image)) is None
    assert reward_timeout_continue(image[::2, ::2]) is None
