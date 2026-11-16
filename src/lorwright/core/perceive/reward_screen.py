"""识别奖励候选；能力名称可未知，候选可见性与品质须有依据。"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import cv2
import numpy as np

from lorwright.core.decide.rewards import CardRewardCandidate, RewardCandidate
from lorwright.core.models import Rect
from lorwright.core.perceive.adventure_scene import _matches, _template
from lorwright.core.perceive.digits import DigitReader, segment_glyphs

_ASSETS = Path("assets/adventure")
_SLOTS = (472, 815, 1158)
_MIN_SCORE = 0.93


@cache
def _names() -> tuple[tuple[str, str], ...]:
    path = _ASSETS / "power_names.json"
    if not path.exists():
        return ()
    return tuple(
        (entry["template"], entry["name"])
        for entry in json.loads(path.read_text(encoding="utf-8"))
    )


def is_power_screen(image: np.ndarray) -> bool:
    return _matches(image, "power_title", (880, 25, 1036, 102), 0.93)


def _best(region: np.ndarray, choices: tuple[tuple[str, str], ...]) -> str | None:
    scores = []
    for template_name, value in choices:
        template = _template(template_name)
        if template is None or template.shape[0] > region.shape[0] or template.shape[1] > region.shape[1]:
            continue
        score = float(cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED).max())
        scores.append((score, value))
    scores.sort(reverse=True)
    if not scores or scores[0][0] < _MIN_SCORE:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.05:
        return None
    return scores[0][1]


def _power_quality(image: np.ndarray, x: int, *, y: int = 584, width: int = 290) -> str | None:
    """品质文字模板与颜色须一致，不从能力插画推断品质。"""
    region = image[y:y + 26, x:x + width]
    quality = _best(cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), (
        ("rarity_legendary", "legendary"), ("rarity_epic", "epic"),
        ("rarity_rare", "rare"), ("rarity_common", "common"),
    ))
    hues = {"common": (35, 60), "rare": (90, 115),
            "epic": (135, 160), "legendary": (15, 30)}
    if quality is None:
        return None
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    visible = (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 100)
    low, high = hues[quality]
    matched = visible & (hsv[:, :, 0] >= low) & (hsv[:, :, 0] <= high)
    if int(visible.sum()) < 60 or float(matched.sum() / visible.sum()) < 0.9:
        return None
    return quality


def recognize_powers(image: np.ndarray) -> list[RewardCandidate] | None:
    """返回左到右的候选；未知名为空串，候选遮挡或品质未知则弃权。"""
    if image.shape != (1080, 1920, 3) or not is_power_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = []
    for x in _SLOTS:
        title = gray[540:583, x:x + 290]
        if int((title > 170).sum()) < 100:
            return None
        name = _best(title, _names())
        quality = _power_quality(image, x)
        if quality is None:
            return None
        result.append(RewardCandidate(name=name or "", quality=quality))
    return result


def power_selection(image: np.ndarray) -> int | None:
    """唯一选中槽位；-1 为未选，遮挡或多个高亮时弃权。"""
    if image.shape != (1080, 1920, 3) or not is_power_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    states = []
    for x in _SLOTS:
        edge = gray[290:760, x:x + 3]
        selected_edge = gray[290:760, x + 7:x + 10]
        if float((selected_edge > 180).mean()) > 0.8 and float(selected_edge.mean()) > 200:
            states.append(True)
        elif (55 < float(edge.mean()) < 105 and float((edge > 180).mean()) < 0.02
              and float(selected_edge.mean()) < 50):
            states.append(False)
        else:
            return None
    if not any(states):
        return -1
    return states.index(True) if sum(states) == 1 else None


def _power_button_gold(image: np.ndarray) -> float | None:
    if image.shape != (1080, 1920, 3) or not is_power_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _visible_match(gray, "card_reward_choose", (800, 960, 1120, 1045)) < 0.93:
        return None
    hsv = cv2.cvtColor(image[975:1030, 815:1105], cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] > 5) & (hsv[:, :, 0] < 30)
            & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 130))
    return float(gold.mean())


def power_unselected(image: np.ndarray) -> bool:
    gold = _power_button_gold(image)
    return power_selection(image) == -1 and gold is not None and gold < 0.02


def power_choose_enabled(image: np.ndarray) -> bool:
    gold = _power_button_gold(image)
    return gold is not None and gold > 0.08


_CARD_SLOTS = (354, 769, 1184)


@cache
def _card_catalog() -> dict:
    path = _ASSETS / "card_rewards.json"
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return catalog if _valid_card_catalog(catalog) else {}


def _valid_card_catalog(catalog: object) -> bool:
    if not isinstance(catalog, dict):
        return False
    cards, items = catalog.get("cards"), catalog.get("items")
    if not isinstance(cards, list) or not cards or not isinstance(items, list) or not items:
        return False
    for entries, fields in ((cards, ("name", "template", "art", "quality")),
                            (items, ("name", "template"))):
        if any(not isinstance(entry, dict) or any(
            not isinstance(entry.get(field), str) or not entry[field].strip() for field in fields
        ) for entry in entries):
            return False
        if len({entry["name"] for entry in entries}) != len(entries):
            return False
    return all(isinstance(item.get("cost_certain"), bool) for item in items)


@cache
def _reward_digits() -> DigitReader:
    reader = DigitReader(_ASSETS / "reward_digits", min_score=0.92)
    reader.load()
    return reader


def _visible_match(gray: np.ndarray, template_name: str, rect: tuple[int, int, int, int]) -> float:
    """匹配图案并拒绝明显变暗的遮罩画面。"""
    template = _template(template_name)
    if template is None:
        return -1.0
    x1, y1, x2, y2 = rect
    region = gray[y1:y2, x1:x2]
    h, w = template.shape
    if region.shape[0] < h or region.shape[1] < w:
        return -1.0
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    matched = region[y:y + h, x:x + w]
    if float(matched.mean()) < float(template.mean()) * 0.78:
        return -1.0
    bright = template >= 180
    if bright.any() and float(matched[bright].mean()) < float(template[bright].mean()) * 0.78:
        return -1.0
    return float(score)


def is_hero_item_reward_screen(image: np.ndarray) -> bool:
    """识别英雄道具奖励页；识别页面本身不授权选择或确认。"""
    if image.shape != (1080, 1920, 3):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return (
        _visible_match(gray, "card_reward_title", (760, 18, 1160, 110)) >= 0.93
        and _visible_match(gray, "hero_item_reward_subtitle", (450, 125, 1460, 195)) >= 0.93
    )


def hero_item_choose_disabled(image: np.ndarray) -> bool:
    """受控采样前确认选择按钮存在且未显示启用金色。"""
    if not is_hero_item_reward_screen(image):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _visible_match(gray, "card_reward_choose", (800, 960, 1120, 1045)) < 0.93:
        return False
    hsv = cv2.cvtColor(image[975:1030, 815:1105], cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] > 5) & (hsv[:, :, 0] < 30)
            & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 130))
    return float(gold.mean()) < 0.02


def hero_item_choose_enabled(image: np.ndarray) -> bool:
    """按钮文字可见且金色区域符合实拍启用状态。"""
    if not is_hero_item_reward_screen(image):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _visible_match(gray, "card_reward_choose", (800, 960, 1120, 1045)) < 0.93:
        return False
    hsv = cv2.cvtColor(image[975:1030, 815:1105], cv2.COLOR_BGR2HSV)
    gold = ((hsv[:, :, 0] > 5) & (hsv[:, :, 0] < 30)
            & (hsv[:, :, 1] > 90) & (hsv[:, :, 2] > 130))
    return float(gold.mean()) > 0.08


def hero_item_item_selection(image: np.ndarray) -> int | None:
    """返回唯一高亮槽，-1 为均未选；遮挡或歧义返回 None。"""
    if not is_hero_item_reward_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    states = []
    for x in (471, 815, 1157):
        edge = gray[690:816, x:x + 4]
        bright, mean = float((edge > 180).mean()), float(edge.mean())
        if bright > 0.6 and mean > 180:
            states.append(True)
        elif bright < 0.05 and 45 < mean < 125:
            states.append(False)
        else:
            return None
    if not any(states):
        return -1
    return states.index(True) if sum(states) == 1 else None


@cache
def _hero_item_templates():
    root = Path(__file__).resolve().parents[1] / "champions"
    orb = cv2.ORB_create(nfeatures=4000)
    templates = {}
    for name, path in (("jinx", root / "jinx/assets/01PZ040.png"),
                       ("elise", root / "elise/assets/01SI053.png")):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            return orb, {}
        _, descriptors = orb.detectAndCompute(image, None)
        if descriptors is None:
            return orb, {}
        templates[name] = descriptors
    return orb, templates


def recognize_hero_item_cards(image: np.ndarray) -> tuple[str, str] | None:
    """识别两张英雄卡的身份；不推断选中状态或授权点击。"""
    if not is_hero_item_reward_screen(image):
        return None
    orb, templates = _hero_item_templates()
    if len(templates) != 2:
        return None
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    result = []
    for x1, x2 in ((680, 875), (1020, 1210)):
        region = cv2.cvtColor(image[275:455, x1:x2], cv2.COLOR_BGR2GRAY)
        _, descriptors = orb.detectAndCompute(region, None)
        if descriptors is None:
            return None
        scores = sorted(
            ((sum(a.distance < 0.75 * b.distance for a, b in
                  matcher.knnMatch(descriptors, reference, k=2)), name)
             for name, reference in templates.items()), reverse=True,
        )
        if scores[0][0] < 60 or scores[0][0] - scores[1][0] < 30:
            return None
        result.append(scores[0][1])
    if len(set(result)) != 2:
        return None
    return result[0], result[1]


def hero_item_hero_selection(image: np.ndarray) -> int | None:
    """返回选中英雄槽，-1 为均未选中；遮挡或歧义返回 None。"""
    if not is_hero_item_reward_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    states = []
    for x in (642, 986):
        edge = gray[245:625, x:x + 4]
        bright = float((edge > 180).mean())
        mean = float(edge.mean())
        if bright > 0.6 and mean > 180:
            states.append(True)
        elif bright < 0.05 and 45 < mean < 125:
            states.append(False)
        else:
            return None
    if states == [False, False]:
        return -1
    if sum(states) == 1:
        return states.index(True)
    return None


def recognize_hero_items(image: np.ndarray) -> list[RewardCandidate] | None:
    """所有道具名称和品质都可靠匹配时才返回候选。"""
    if not is_hero_item_reward_screen(image):
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    names = (("hero_item_vampiric", "吸血鬼權杖"),
             ("hero_item_scout", "鑽探衝鋒"), ("hero_item_sword", "軍隊長劍"))
    qualities = (("hero_item_rare", "rare"), ("hero_item_common", "common"))
    result = []
    for x in (563, 906, 1249):
        name = _best(gray[700:726, x:x + 130], names)
        quality = _best(gray[725:744, x:x + 80], qualities)
        if name is None or quality is None:
            return None
        name_template = next(template for template, value in names if value == name)
        quality_template = next(template for template, value in qualities if value == quality)
        if (_visible_match(gray, name_template, (x, 700, x + 130, 726)) < _MIN_SCORE
                or _visible_match(gray, quality_template, (x, 725, x + 80, 744)) < _MIN_SCORE):
            return None
        result.append(RewardCandidate(name, quality))
    return result


def is_card_reward_screen(image: np.ndarray) -> bool:
    """战斗卡牌奖励：标题、副标题和选择按钮必须同时可见。"""
    if image.shape != (1080, 1920, 3):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return (
        _visible_match(gray, "card_reward_title", (760, 18, 1160, 110)) >= 0.93
        and _visible_match(gray, "card_reward_subtitle", (590, 130, 1330, 195)) >= 0.93
        and _visible_match(gray, "card_reward_choose", (800, 960, 1120, 1045)) >= 0.93
    )


def card_reward_selection(image: np.ndarray) -> int | None:
    """返回选中的 0–2 号槽，-1 为未选中，None 为状态不明。"""
    if not is_card_reward_screen(image):
        return None
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    ratios = []
    for x in _CARD_SLOTS:
        edge = hsv[300:780, x + 6:x + 11]
        ratios.append(float(((edge[:, :, 2] > 180) & (edge[:, :, 1] < 160)).mean()))
    button = hsv[968:1030, 810:1110]
    gold = ((button[:, :, 0] > 5) & (button[:, :, 0] < 30)
            & (button[:, :, 1] > 90) & (button[:, :, 2] > 130))
    enabled = float(gold.mean())
    if max(ratios) < 0.15 and enabled < 0.02:
        return -1 if all(_reward_frame_visible(image, x) for x in _CARD_SLOTS) else None
    selected = [i for i, ratio in enumerate(ratios) if ratio > 0.5]
    if enabled > 0.08 and len(selected) == 1 and all(
        ratio < 0.15 for i, ratio in enumerate(ratios) if i != selected[0]
    ):
        return selected[0]
    return None


def card_reward_target(image: np.ndarray, index: int, name: str) -> Rect | None:
    """定位卡面并核对点击中心未被遮挡，返回设计尺寸坐标。"""
    if index not in range(len(_CARD_SLOTS)) or card_reward_selection(image) != -1:
        return None
    catalog = _card_catalog()
    if not _valid_card_catalog(catalog):
        return None
    card = next((entry for entry in catalog["cards"] if entry["name"] == name), None)
    if card is None:
        if name:
            return None
        x = _CARD_SLOTS[index]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if not _card_visible(gray, x) or _card_cost(image, x) is None:
            return None
        # 卡框内的插画中心；不需要先给这张卡建立身份模板。
        target = Rect(x + 191, 383, 20, 20)
        patch = gray[target.y:target.y + target.h, target.x:target.x + target.w]
        if float((patch < 8).mean()) > 0.05 or float(patch.std()) < 5:
            return None
        return target
    template = _template(card["art"])
    if template is None:
        return None
    x = _CARD_SLOTS[index]
    rect = (x + 55, 300, x + 325, 465)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _visible_match(gray, card["art"], rect) < 0.93:
        return None
    x1, y1, x2, y2 = rect
    scores = cv2.matchTemplate(gray[y1:y2, x1:x2], template, cv2.TM_CCOEFF_NORMED)
    _, _, _, (dx, dy) = cv2.minMaxLoc(scores)
    h, w = template.shape
    cx, cy = w // 2, h // 2
    actual = gray[y1 + dy + cy - 10:y1 + dy + cy + 10,
                  x1 + dx + cx - 10:x1 + dx + cx + 10]
    reference = template[cy - 10:cy + 10, cx - 10:cx + 10]
    if actual.shape != (20, 20) or float((cv2.absdiff(actual, reference) > 40).mean()) > 0.05:
        return None
    return Rect(x1 + dx, y1 + dy, w, h)


def card_reward_confirm_button(image: np.ndarray) -> Rect | None:
    """仅在有唯一已选候选且按钮启用时返回按钮文字位置。"""
    if card_reward_selection(image) not in (0, 1, 2):
        return None
    template = _template("card_reward_choose")
    if template is None:
        return None
    region = cv2.cvtColor(image[960:1045, 800:1120], cv2.COLOR_BGR2GRAY)
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, (x, y) = cv2.minMaxLoc(scores)
    if score < 0.93:
        return None
    h, w = template.shape
    return Rect(800 + x, 960 + y, w, h)


def _card_entry(gray: np.ndarray, entries: list[dict], rect: tuple[int, int, int, int]) -> dict | None:
    scores = sorted(
        ((_visible_match(gray, entry["template"], rect), i) for i, entry in enumerate(entries)),
        reverse=True,
    )
    if not scores or scores[0][0] < 0.93:
        return None
    if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.05:
        return None
    return entries[scores[0][1]]


def _card_cost(image: np.ndarray, x: int) -> int | None:
    glyphs = segment_glyphs(image, Rect(x + 74, 276, 36, 33), threshold=180)
    if len(glyphs) != 1 or not 20 <= glyphs[0].rect.h <= 30:
        return None
    hit = _reward_digits().classify(glyphs[0].image)
    return hit[0] if hit else None


def _reward_frame_visible(image: np.ndarray, x: int) -> bool:
    """奖励外框必须存在，两侧检查带不能被黑色遮挡。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if _visible_match(gray, "card_reward_frame_corner", (x - 3, 228, x + 30, 255)) < 0.75:
        return False
    return all(float((gray[300:780, x + offset:x + offset + 5] < 8).mean()) < 0.01
               for offset in (6, 375))


def _card_visible(gray: np.ndarray, x: int) -> bool:
    """独立识别法术或单位框及相应标题位置，不从插画猜身份。"""
    spell = any(_visible_match(gray, name, (x + 50, 590, x + 85, 640)) >= 0.93
                for name in ("card_reward_spell_frame", "card_reward_spell_frame_teal"))
    unit = _visible_match(gray, "card_reward_unit_frame", (x + 50, 250, x + 100, 290)) >= 0.93
    champion = _visible_match(gray, "card_reward_champion_frame", (x + 265, 245, x + 320, 295)) >= 0.93
    if spell:
        title = gray[487:514, x + 120:x + 300]
    elif unit:
        title = gray[533:554, x + 75:x + 315]
    elif champion:
        title = gray[397:430, x + 75:x + 315]
    else:
        return False
    art = gray[337:450, x + 130:x + 270]
    return (int((title > 170).sum()) >= 120
            and float((art < 8).mean()) < 0.05 and float(art.std()) > 10)


def _card_badge_quality(image: np.ndarray, x: int) -> str:
    """徽记图案及颜色必须一致；缺徽记不等于普通或无品质。"""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    rect = (x + 150, 625, x + 235, 670)
    scores = sorted((_visible_match(gray, "card_reward_" + quality + "_badge", rect), quality)
                    for quality in ("common", "rare"))
    if scores[-1][0] < 0.93 or scores[-1][0] - scores[-2][0] < 0.05:
        return "unknown"
    quality = scores[-1][1]
    template = _template("card_reward_" + quality + "_badge")
    x1, y1, x2, y2 = rect
    _, _, _, (dx, dy) = cv2.minMaxLoc(cv2.matchTemplate(
        gray[y1:y2, x1:x2], template, cv2.TM_CCOEFF_NORMED))
    h, w = template.shape
    hsv = cv2.cvtColor(image[y1 + dy:y1 + dy + h, x1 + dx:x1 + dx + w], cv2.COLOR_BGR2HSV)
    low, high = (35, 85) if quality == "common" else (85, 115)
    colored = ((hsv[:, :, 0] >= low) & (hsv[:, :, 0] <= high)
               & (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 100))
    return quality if int(colored.sum()) >= 60 else "unknown"


def recognize_card_rewards(image: np.ndarray) -> list[CardRewardCandidate] | None:
    """识别可见候选；未知名为空，预览费用与道具费用契约分别记录。"""
    if card_reward_selection(image) != -1:
        return None
    catalog = _card_catalog()
    if not _valid_card_catalog(catalog):
        return None
    cards, items = catalog.get("cards", []), catalog.get("items", [])
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    result = []
    for x in _CARD_SLOTS:
        card = _card_entry(gray, cards, (x + 45, 470, x + 330, 575))
        item = _card_entry(gray, items, (x + 100, 655, x + 300, 700))
        cost = _card_cost(image, x)
        if cost is None:
            return None
        if card is not None:
            if _visible_match(gray, card["art"], (x + 55, 300, x + 325, 465)) < 0.93:
                return None
        elif not _card_visible(gray, x):
            return None
        if item is None and int((gray[665:690, x + 125:x + 315] > 170).sum()) < 120:
            return None
        result.append(CardRewardCandidate(
            card=RewardCandidate(name=card["name"] if card else "",
                                 quality=card["quality"] if card else _card_badge_quality(image, x),
                                 cost=cost),
            item_name=item["name"] if item else "",
            cost_certain=item["cost_certain"] if item else False,
            preview_cost_verified=True,
        ))
    return result


def same_card_reward_choices(before: np.ndarray, after: np.ndarray, index: int) -> bool:
    """核对选择前后三槽插画与道具名；允许实拍选中卡的放大和上移。"""
    if (index not in range(len(_CARD_SLOTS)) or card_reward_selection(before) != -1
            or card_reward_selection(after) != index):
        return False
    old, new = (cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) for image in (before, after))
    # 选中动画会缩放整个候选，局部模板在同槽搜索，不跨槽匹配。
    for slot, x in enumerate(_CARD_SLOTS):
        for y1, y2, dx1, dx2, search in (
            (337, 425, 130, 250, (x + 55, 245, x + 325, 480)),
            (665, 690, 125, 315, (x + 90, 650, x + 330, 715)),
        ):
            reference = old[y1:y2, x + dx1:x + dx2]
            sx1, sy1, sx2, sy2 = search
            region = new[sy1:sy2, sx1:sx2]
            best = -1.0
            scales = np.arange(0.98, 1.181, 0.01) if slot == index else (1.0,)
            for scale in scales:
                template = cv2.resize(reference, None, fx=scale, fy=scale)
                scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
                _, score, _, (mx, my) = cv2.minMaxLoc(scores)
                h, w = template.shape
                actual = region[my:my + h, mx:mx + w]
                # 局部遮挡不能只靠整块相关系数通过。
                error = float((cv2.absdiff(actual, template) > 45).mean())
                if float(actual.mean()) >= float(template.mean()) * 0.78 and error < 0.08:
                    best = max(best, score)
            if best < 0.93:
                return False
    return True
