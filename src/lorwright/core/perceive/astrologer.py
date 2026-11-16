"""占星家付费能力页；费用、金币和按钮均使用本帧证据。"""

from functools import cache

import cv2
import numpy as np

from lorwright.core.decide.rewards import RewardCandidate
from lorwright.core.models import Rect
from lorwright.core.perceive.adventure_scene import _matches
from lorwright.core.perceive.digits import DigitReader, segment_glyphs
from lorwright.core.perceive.reward_screen import _best, _names, _power_quality

SLOTS = (985, 1307, 1629)


def is_astrologer(image: np.ndarray) -> bool:
    return (_matches(image, "astrologer_title", (560, 350, 750, 425), 0.93)
            and _matches(image, "astrologer_leave", (630, 910, 755, 990), 0.93))


@cache
def _digits() -> DigitReader:
    reader = DigitReader("assets/adventure/astrologer_digits", min_score=0.92)
    reader.load()
    return reader


def _number(image: np.ndarray, rect: Rect, *, balance: bool = False) -> int | None:
    glyphs = segment_glyphs(image, rect, threshold=180)
    low, high = (28, 45) if balance else (18, 26)
    if not 1 <= len(glyphs) <= 5 or any(not low <= g.rect.h <= high for g in glyphs):
        return None
    hits = [_digits().classify(g.image) for g in glyphs]
    if any(hit is None for hit in hits):
        return None
    return int("".join(str(hit[0]) for hit in hits))


def astrologer_gold(image: np.ndarray) -> int | None:
    return _number(image, Rect(1064, 977, 140, 52), balance=True) if is_astrologer(image) else None


def astrologer_offers(image: np.ndarray) -> list[RewardCandidate] | None:
    if not is_astrologer(image) or not _matches(
        image, "astrologer_offer_title", (1305, 25, 1575, 95), 0.93,
    ):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = []
    for x in SLOTS:
        title = gray[469:503, x:x + 270]
        art = gray[280:390, x + 80:x + 190]
        if (int((title > 170).sum()) < 100 or float((art < 8).mean()) > 0.05
                or float(art.std()) < 10):
            return None
        quality = _power_quality(image, x, y=503, width=270)
        cost = _number(image, Rect(x + 130, 700, 55, 34))
        if quality is None or cost is None:
            return None
        result.append(RewardCandidate(_best(title, _names()) or "", quality, cost))
    return result


def astrologer_selection(image: np.ndarray) -> int | None:
    if not is_astrologer(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    states = []
    for x in SLOTS:
        edge = gray[300:680, x:x + 3]
        inside = gray[300:680, x + 7:x + 10]
        right_edge = gray[300:680, x + 267:x + 270]
        if all(float((part > 180).mean()) > 0.8 and float(part.mean()) > 200
               for part in (edge, right_edge)):
            states.append(True)
        elif (55 < float(edge.mean()) < 105 and float((edge > 180).mean()) < 0.02
              and float(inside.mean()) < 50):
            states.append(False)
        else:
            return None
    return states.index(True) if sum(states) == 1 else -1 if not any(states) else None


def same_astrologer_offers(before: np.ndarray, after: np.ndarray) -> bool:
    offers = astrologer_offers(before)
    if offers is None or offers != astrologer_offers(after):
        return False
    for x in SLOTS:
        first = before[255:503, x + 35:x + 235]
        second = after[255:503, x + 35:x + 235]
        score = float(cv2.matchTemplate(first, second, cv2.TM_CCOEFF_NORMED).max())
        if score < 0.93 or float((cv2.absdiff(first, second) > 45).mean()) > 0.08:
            return False
    return True


def astrologer_buy_button(image: np.ndarray) -> Rect | None:
    if not is_astrologer(image) or not _matches(
        image, "astrologer_buy", (1375, 970, 1510, 1040), 0.93,
    ):
        return None
    hsv = cv2.cvtColor(image[980:1030, 1300:1585], cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] > 5) & (hsv[:, :, 0] < 30)
            & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 130))
    return Rect(1288, 972, 305, 67) if float(gold.mean()) > 0.08 else None


def astrologer_leave_button(image: np.ndarray) -> Rect | None:
    return Rect(540, 904, 425, 99) if is_astrologer(image) else None
