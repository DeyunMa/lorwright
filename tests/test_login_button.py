"""登录方式按钮必须可见且未变暗，才允许点击。"""

import cv2

from lorwright.core.models import Rect
from lorwright.core.perceive.login import LoginDetector, LoginScreen


def test_riot_button_visible_and_occluded_or_dimmed():
    image = cv2.imread("tests/fixtures/screens/1080p_login_splash.png")
    assert image is not None
    detector = LoginDetector()
    detector.load()
    region = Rect(650, 790, 140, 90)
    assert detector.detect(image) is LoginScreen.SPLASH
    assert detector.riot_button_visible(image, region)

    covered = image.copy()
    covered[820:850, 700:740] = 0
    assert not detector.riot_button_visible(covered, region)

    dimmed = image.copy()
    dimmed[790:880, 650:790] //= 2
    assert not detector.riot_button_visible(dimmed, region)


def test_missing_template_or_outside_frame_does_not_match():
    image = cv2.imread("tests/fixtures/screens/1080p_login_splash.png")
    assert image is not None
    detector = LoginDetector()
    assert not detector.riot_button_visible(image, Rect(650, 790, 140, 90))
    detector.load()
    assert not detector.riot_button_visible(image, Rect(1900, 790, 140, 90))
