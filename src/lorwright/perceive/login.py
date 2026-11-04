"""登录界面识别。

LoR 登录只有两屏：
1. splash：满屏插画 + 「登入以開始遊戲」+ 四个登录方式按钮
2. form  ：「登入」标题 + 使用者名稱 / 密碼 + 提交箭头

两屏都没有动作按钮、没有手牌，`ui_state` 只会是 `UNKNOWN`，
所以「卡在登录」在旧逻辑里表现为「什么都不做」，很难区分于「游戏卡死」。
这里单独认，才能让上层主动去登录。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

from lorwright.perceive.locate import exists

__all__ = ["LoginScreen", "LoginDetector"]


class LoginScreen(StrEnum):
    NONE = "none"        # 不在登录界面（已登录 / 别处）
    SPLASH = "splash"    # 「登入以開始遊戲」
    FORM = "form"        # 账号密码表单


class LoginDetector:
    """按模板判断当前是登录的哪一屏。"""

    def __init__(
        self,
        root: str | Path = "assets/ui",
        threshold: float = 0.80,
    ) -> None:
        self.root = Path(root)
        self.threshold = threshold
        self._splash: np.ndarray | None = None
        self._form: np.ndarray | None = None

    def load(self) -> None:
        self._splash = _read(self.root / "login_splash.png")
        self._form = _read(self.root / "login_form.png")

    def detect(self, image: np.ndarray) -> LoginScreen:
        # form 先判：表单页上半部分也是插画，splash 的标题模板不会命中，但顺序上更稳
        if self._form is not None and _hits(image, self._form, self.threshold):
            return LoginScreen.FORM
        if self._splash is not None and _hits(image, self._splash, self.threshold):
            return LoginScreen.SPLASH
        return LoginScreen.NONE


def _read(path: Path) -> np.ndarray | None:
    img = cv2.imread(str(path))
    return img if img is not None else None


def _hits(image: np.ndarray, template: np.ndarray, threshold: float) -> bool:
    return exists(image, template, threshold=threshold)
