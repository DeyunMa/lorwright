"""只读多冒险截图语料体检与前后对比工具；不操作设备、不修改输入图片、不含本地私有路径。

默认扫描仓库内的 `tests/fixtures` 与 `research/archives`（可通过 `--dir` 指定任意
额外目录，如实机 `logs/`），对可还原到 1920×1080 设计画布的独立画面评估：
1. 场景识别覆盖（冒险入口、每周列表/详情、继续冒险、地图、节点面板、商店/治疗/宝箱/占星家、奖励、结算、对局 UI、登录/重连）；
2. 数字与数值提取完整度（法力、法术法力、双方血量、手牌费用、弃牌费用、单位攻防、卡牌奖励/援军/占星家/地图金币/每周星级）；
3. 英雄解耦对比（同一批冒险与对局画面在 `jinx`、`elise` 及零素材 `generic` 包下的定位与可执行动作覆盖）；
4. `--compare <before.json>` 输出修改前后的结构化指标增量与场景迁移明细。

结果未经真值标注：场景数是分类输出，actionable 是局部启发式信号，
均不代表准确率、运行时动作资格或成功率；裁图按尺寸放置，可能误配。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from lorwright.cli.app import _battle_layers
from lorwright.core.champions import load as load_champion
from lorwright.core.champions.base import Preference
from lorwright.core.config import load_settings
from lorwright.core.decide.adventure import pick_affordable_power, pick_map_node
from lorwright.core.decide.base import Policy
from lorwright.core.decide.card import CardDef
from lorwright.core.decide.rewards import pick_card_reward, pick_hero_item_reward, pick_reward
from lorwright.core.decide.router import Router
from lorwright.core.decide.support import pick_support_group
from lorwright.core.models import ActionType, UIState
from lorwright.core.perceive import adventure_scene as scene_perceive
from lorwright.core.perceive import mapnav as mapnav_perceive
from lorwright.core.perceive.adventure_scene import (
    find_home_adventure_entry,
    find_resume_adventure_button,
    find_weekly_entry,
    find_weekly_start,
    gold_chest_collect_button,
    is_battle_detail,
    is_completed_panel,
    is_map,
    is_weekly_list,
    item_chest_leave_button,
    recognize_weekly_adventures,
    reward_timeout_continue,
    shop_leave_button,
    weekly_detail_stars,
)
from lorwright.core.perceive.astrologer import (
    astrologer_gold,
    astrologer_map_gold,
    astrologer_offers,
    astrologer_selection,
    is_power_vendor,
)
from lorwright.core.perceive.buttons import find_continue_button
from lorwright.core.perceive.digits import DigitReader
from lorwright.core.perceive.discard import discard_candidates
from lorwright.core.perceive.healer import healer_heal_button, is_healer_screen
from lorwright.core.perceive.login import LoginDetector, LoginScreen
from lorwright.core.perceive.mapnav import (
    node_kind,
    occluded_route_zoom_button,
    panel_open,
    reachable_nodes,
)
from lorwright.core.perceive.normalize import Normalizer
from lorwright.core.perceive.reconnect import ReconnectDetector
from lorwright.core.perceive.result_screen import (
    adventure_settlement,
    is_result_transition,
    is_task_reward,
    result_screen,
)
from lorwright.core.perceive.revive_screen import find_revive_button
from lorwright.core.perceive.reward_screen import (
    card_reward_selection,
    hero_item_hero_selection,
    hero_item_item_selection,
    is_card_reward_screen,
    is_hero_item_reward_screen,
    is_power_screen,
    power_selection,
    recognize_card_rewards,
    recognize_hero_item_cards,
    recognize_hero_items,
    recognize_powers,
)
from lorwright.core.perceive.state import StateParser
from lorwright.core.perceive.support_screen import (
    is_support_screen,
    recognize_support_choices,
    support_selection,
)
from lorwright.core.perceive.ui_state import UIStateDetector
from lorwright.core.util.logger import logger

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}

#: `tests/fixtures/README.md` 记录的安全裁剪在 1920×1080 设计空间中的左上角坐标 (x, y)
CROP_PLACEMENTS: dict[tuple[int, int], tuple[int, int]] = {
    (1080, 1600): (320, 0),    # [:, 320:] 对局安全裁剪
    (1032, 1250): (330, 18),   # [18:1050, 330:1580] 卡牌奖励
    (1030, 1380): (280, 15),   # [15:1045, 280:1660] 辅助英雄选择
    (1045, 1390): (530, 0),    # [0:1045, 530:1920] 占星家
    (1025, 980): (530, 20),    # [20:1045, 530:1510] 治疗师
    (685, 445): (530, 340),    # [340:1025, 530:975] 宝箱侧栏
    (720, 445): (530, 340),    # [340:1060, 530:975] 商店侧栏
    (1080, 1150): (350, 0),    # [0:1080, 350:1500] 英雄道具奖励
    (670, 1150): (350, 350),   # [350:1020, 350:1500] 最终奖励汇总主体
    (370, 1850): (30, 30),     # [30:400, 30:1880] 任务结算顶栏
    (800, 1300): (300, 100),   # [100:900, 300:1600] 无字结算岩壁背景
    (840, 1850): (70, 140),    # [140:980, 70:1920] 弃牌候选
    (460, 230): (885, 35),     # [35:495, 885:1115] 短展示框连线
}


class _AbstainPolicy(Policy):
    name = "generic_abstain"

    def decide(self, _state):
        return None


class GenericPack:
    """不含任何专属图片模板的空白英雄包，用于验证冒险与默认对局的英雄无关性。"""

    name = "generic"
    display_name = "通用英雄"
    deck: tuple[CardDef, ...] = ()
    relic_preferences: tuple[Preference, ...] = ()
    item_preferences: tuple[Preference, ...] = ()
    card_preferences: tuple[Preference, ...] = ()
    spell_preferences: tuple[Preference, ...] = ()
    power_preferences: tuple[Preference, ...] = ()

    @staticmethod
    def lookup(_name: str):
        return None

    def make_policy(self) -> Policy:
        return _AbstainPolicy()


def prepare_canvas(image: np.ndarray, normalizer: Normalizer) -> tuple[np.ndarray | None, str]:
    """将输入图像还原或归一化到 1920×1080 设计画布；小尺寸单件素材返回 None。"""
    height, width = image.shape[:2]
    if (height, width) == (1080, 1920):
        return image, "native_1080p"
    if (height, width) in CROP_PLACEMENTS:
        x0, y0 = CROP_PLACEMENTS[(height, width)]
        canvas = np.zeros((1080, 1920, 3), dtype=np.uint8)
        canvas[y0 : y0 + height, x0 : x0 + width] = image
        return canvas, f"crop_{width}x{height}"
    if width >= 960 and height >= 540 and abs((width / height) - (16 / 9)) <= 0.03:
        fitted, _ = normalizer.fit(image)
        return fitted, f"scaled_{width}x{height}"
    return None, f"skipped_{width}x{height}"


def _make_parser(settings, pack) -> StateParser:
    lay = settings.layout.to_layout()
    ui = UIStateDetector(threshold=settings.perception.match_threshold, action_button=lay.end_turn)
    digits = DigitReader()
    parser = StateParser(
        layout=lay,
        ui=ui,
        digits=digits,
        threshold=settings.perception.match_threshold,
        card_recognizer=getattr(pack, "recognize_hand", None),
        mulligan_recognizer=getattr(pack, "recognize_mulligan", None),
        targeted_spell_recognizer=getattr(pack, "recognize_targeted_spell", None),
        my_unit_recognizer=getattr(pack, "recognize_my_units", None),
    )
    parser.load()
    return parser


def _reset_parser(parser: StateParser) -> None:
    parser._readings.clear()
    parser._my_hp = parser._enemy_hp = 20
    parser._mana = 0
    parser._previous_ui = UIState.UNKNOWN


def _resolve_map_hero(canvas: np.ndarray, pack) -> tuple[int, int] | None:
    recognize_hero = getattr(pack, "recognize_map_hero", None)
    hero = recognize_hero(canvas) if recognize_hero is not None else None
    if hero is not None:
        return hero
    fallback = getattr(mapnav_perceive, "recognize_map_token", None)
    return fallback(canvas) if fallback is not None else None


def evaluate_map_for_pack(canvas: np.ndarray, pack) -> dict:
    hero = _resolve_map_hero(canvas, pack)
    if hero is None:
        return {"hero_found": False, "reachable": 0, "zoom_needed": False, "actionable": False}
    nodes = reachable_nodes(canvas, hero=hero, rng=random.Random(0))
    kinds = [node_kind(canvas, node) for node in nodes]
    picked = pick_map_node(kinds, rng=random.Random(0)) if nodes else None
    zoom = occluded_route_zoom_button(canvas, hero) is not None if not nodes else False
    return {
        "hero_found": hero is not None,
        "reachable": len(nodes),
        "zoom_needed": zoom,
        "actionable": (picked is not None) or zoom,
    }


def evaluate_resume_for_pack(canvas: np.ndarray, pack) -> bool:
    generic_check = getattr(scene_perceive, "can_resume_adventure", None)
    if generic_check is not None:
        return bool(generic_check(canvas, pack))
    selected = getattr(pack, "recognize_selected_hero", None)
    return bool(selected is not None and selected(canvas))


def audit_corpus(directories: list[Path]) -> dict:
    """扫描给定目录列表，去重后返回 schema_version=1 的评估字典。"""
    logger.disable("lorwright")
    settings = load_settings()
    normalizer = Normalizer((1920, 1080))
    login_det = LoginDetector()
    login_det.load()
    reconnect_det = ReconnectDetector()
    reconnect_det.load()

    jinx_pack = load_champion("jinx")
    elise_pack = load_champion("elise")
    generic_pack = GenericPack()

    jinx_parser = _make_parser(settings, jinx_pack)
    elise_parser = _make_parser(settings, elise_pack)

    seen_hashes: set[str] = set()
    files: list[Path] = []
    for base in directories:
        if not base.exists():
            continue
        paths = [base] if base.is_file() else sorted(base.rglob("*"))
        for path in paths:
            if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if "annotated" in path.name:
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)
            files.append(path)

    scene_counts: Counter[str] = Counter()
    metrics: Counter[str] = Counter()
    records: list[dict] = []

    for path in files:
        image = cv2.imread(str(path))
        if image is None:
            metrics["unreadable_images"] += 1
            continue
        canvas, mode = prepare_canvas(image, normalizer)
        if canvas is None:
            metrics["skipped_small_or_aspect"] += 1
            continue
        metrics["evaluated_frames"] += 1
        if mode == "native_1080p":
            metrics["native_1080p_frames"] += 1

        _reset_parser(jinx_parser)
        _reset_parser(elise_parser)

        scene = "unknown"
        actionable = False
        details: dict = {"mode": mode}

        login_state = login_det.detect(canvas)
        if login_state is not LoginScreen.NONE:
            scene = f"login_{login_state.value}"
            actionable = True
        elif reconnect_det.detect(canvas):
            scene = "reconnect"
            actionable = True
        elif reward_timeout_continue(canvas) is not None:
            scene = "reward_timeout"
            actionable = True
        elif find_revive_button(canvas) is not None:
            scene = "revive"
            actionable = True
        elif (stage := adventure_settlement(canvas)) is not None:
            scene = f"adventure_{stage}"
            actionable = find_continue_button(canvas) is not None or stage in {"relic_chest", "relic_reward"}
        elif is_task_reward(canvas):
            scene = "task_reward"
            actionable = find_continue_button(canvas) is not None
        elif (res_kind := result_screen(canvas)) is not None:
            scene = f"result_{res_kind}"
            actionable = find_continue_button(canvas) is not None
        elif is_result_transition(canvas):
            scene = "result_transition"
            actionable = False
        elif is_card_reward_screen(canvas):
            scene = "card_reward"
            sel = card_reward_selection(canvas)
            cands = recognize_card_rewards(canvas) if sel == -1 else None
            details["selection"] = sel
            if cands is not None:
                metrics["card_reward_full_recognized"] += 1
                metrics["card_reward_costs_read"] += sum(1 for c in cands if c.card.cost is not None)
                j_hook = getattr(jinx_pack, "pick_card_reward", None)
                pick_j = j_hook(cands) if j_hook else pick_card_reward(
                    cands, jinx_pack.card_preferences, jinx_pack.item_preferences
                )
                e_hook = getattr(elise_pack, "pick_card_reward", None)
                pick_e = e_hook(cands) if e_hook else pick_card_reward(
                    cands, elise_pack.card_preferences, elise_pack.item_preferences
                )
                pick_g = pick_card_reward(cands)
                if pick_j is not None:
                    metrics["card_reward_jinx_actionable"] += 1
                if pick_e is not None:
                    metrics["card_reward_elise_actionable"] += 1
                if pick_g is not None:
                    metrics["card_reward_generic_actionable"] += 1
                actionable = pick_j is not None or pick_e is not None
            elif sel in (0, 1, 2):
                actionable = True
        elif is_hero_item_reward_screen(canvas):
            scene = "hero_item_reward"
            items = recognize_hero_items(canvas)
            heroes = recognize_hero_item_cards(canvas)
            h_sel = hero_item_hero_selection(canvas)
            i_sel = hero_item_item_selection(canvas)
            if items is not None:
                metrics["hero_item_items_recognized"] += 1
                if pick_hero_item_reward(items, elise_pack.item_preferences, random.Random(0)) is not None:
                    metrics["hero_item_elise_pickable"] += 1
            if heroes is not None:
                metrics["hero_item_heroes_recognized"] += 1
            actionable = items is not None and (h_sel is not None or i_sel is not None)
        elif is_power_screen(canvas):
            scene = "power_reward"
            powers = recognize_powers(canvas)
            p_sel = power_selection(canvas)
            if powers is not None:
                metrics["power_reward_recognized"] += 1
                actionable = pick_reward(powers, jinx_pack.power_preferences) is not None
            elif p_sel in (0, 1, 2):
                actionable = True
        elif is_support_screen(canvas):
            scene = "support_reward"
            s_sel = support_selection(canvas)
            choices = recognize_support_choices(canvas) if s_sel == -1 else None
            if choices is not None:
                metrics["support_choices_recognized"] += 1
                metrics["support_costs_read"] += sum(
                    (1 if ch.group.hero_cost is not None else 0)
                    + sum(1 for c in ch.group.card_costs if c is not None)
                    for ch in choices
                )
                actionable = pick_support_group([ch.group for ch in choices]) is not None
            elif s_sel in (0, 1, 2):
                actionable = True
        elif is_power_vendor(canvas):
            scene = "astrologer"
            gold = astrologer_gold(canvas)
            offers = astrologer_offers(canvas)
            a_sel = astrologer_selection(canvas)
            if gold is not None:
                metrics["astrologer_gold_read"] += 1
            if offers is not None:
                metrics["astrologer_offers_recognized"] += 1
                metrics["astrologer_offer_costs_read"] += sum(1 for o in offers if o.cost is not None)
            actionable = (
                gold is not None and offers is not None and pick_affordable_power(offers, gold) is not None
            ) or (gold is not None and offers is not None) or a_sel in (0, 1, 2)
        elif is_healer_screen(canvas):
            scene = "healer"
            actionable = healer_heal_button(canvas) is not None
            if actionable:
                metrics["healer_actionable"] += 1
        elif shop_leave_button(canvas) is not None:
            scene = "shop"
            actionable = True
        elif item_chest_leave_button(canvas) is not None:
            scene = "item_chest"
            actionable = True
        elif gold_chest_collect_button(canvas) is not None:
            scene = "gold_chest"
            actionable = True
        elif find_resume_adventure_button(canvas) is not None:
            scene = "resume_adventure"
            j_ok = evaluate_resume_for_pack(canvas, jinx_pack)
            e_ok = evaluate_resume_for_pack(canvas, elise_pack)
            g_ok = evaluate_resume_for_pack(canvas, generic_pack)
            if j_ok:
                metrics["resume_jinx_ok"] += 1
            if e_ok:
                metrics["resume_elise_ok"] += 1
            if g_ok:
                metrics["resume_generic_ok"] += 1
            actionable = j_ok or e_ok or g_ok
        elif is_weekly_list(canvas):
            scene = "weekly_list"
            advs = recognize_weekly_adventures(canvas)
            if advs is not None:
                stars_known = sum(1 for a in advs if a.stars is not None)
                metrics["weekly_stars_read"] += stars_known
                actionable = stars_known == len(advs)
            else:
                actionable = True
        elif weekly_detail_stars(canvas) is not None:
            scene = "weekly_detail"
            metrics["weekly_detail_stars_read"] += 1
            actionable = find_weekly_start(canvas) is not None
        elif find_weekly_entry(canvas) is not None:
            scene = "world_map_weekly"
            actionable = True
        elif find_home_adventure_entry(canvas) is not None:
            scene = "home"
            actionable = True
        elif is_battle_detail(canvas):
            scene = "battle_detail"
            actionable = True
        elif is_completed_panel(canvas):
            scene = "map_completed_panel"
            actionable = True
        elif is_map(canvas) and panel_open(canvas):
            scene = "map_node_panel"
            actionable = True
        elif is_map(canvas):
            scene = "map"
            if astrologer_map_gold(canvas) is not None:
                metrics["map_gold_read"] += 1
            j_map = evaluate_map_for_pack(canvas, jinx_pack)
            e_map = evaluate_map_for_pack(canvas, elise_pack)
            g_map = evaluate_map_for_pack(canvas, generic_pack)
            if j_map["hero_found"]:
                metrics["map_hero_jinx_found"] += 1
            if e_map["hero_found"]:
                metrics["map_hero_elise_found"] += 1
            if g_map["hero_found"]:
                metrics["map_hero_generic_found"] += 1
            if j_map["actionable"]:
                metrics["map_jinx_actionable"] += 1
            if e_map["actionable"]:
                metrics["map_elise_actionable"] += 1
            if g_map["actionable"]:
                metrics["map_generic_actionable"] += 1
            actionable = j_map["actionable"] or e_map["actionable"]
            details["jinx_map"] = j_map
            details["elise_map"] = e_map
        else:
            st_j = jinx_parser.parse(canvas)
            st_e = elise_parser.parse(canvas)
            if st_j.ui_state is not UIState.UNKNOWN:
                scene = f"battle_{st_j.ui_state.value}"
                metrics["battle_frames"] += 1
                if st_j.readings.get("mana") and st_j.readings["mana"].fresh:
                    metrics["battle_mana_fresh"] += 1
                if st_j.spell_mana is not None:
                    metrics["battle_spell_mana_fresh"] += 1
                if st_j.readings.get("nexus_hp") and st_j.readings["nexus_hp"].fresh:
                    metrics["battle_my_hp_fresh"] += 1
                if st_j.readings.get("enemy_nexus_hp") and st_j.readings["enemy_nexus_hp"].fresh:
                    metrics["battle_enemy_hp_fresh"] += 1

                metrics["battle_hand_cards_total"] += len(st_j.hand)
                metrics["battle_hand_costs_read"] += sum(1 for c in st_j.hand if c.cost >= 0)
                if st_j.hand_expanded:
                    metrics["battle_expanded_drag_valid"] += sum(
                        1 for c in st_j.hand if c.drag_point_valid
                    )

                metrics["battle_my_units_total"] += len(st_j.my_units)
                metrics["battle_my_units_stats_both"] += sum(
                    1 for u in st_j.my_units if u.attack >= 0 and u.health >= 0
                )
                metrics["battle_enemy_units_total"] += len(st_j.enemy_units)
                metrics["battle_enemy_units_stats_both"] += sum(
                    1 for u in st_j.enemy_units if u.attack >= 0 and u.health >= 0
                )

                if st_j.ui_state is UIState.DISCARD:
                    dc = discard_candidates(canvas, jinx_parser.digits)
                    if dc is not None:
                        metrics["discard_screens_recognized"] += 1
                        metrics["discard_costs_read"] += sum(1 for c in dc.costs if c is not None)
                        st_j.discard_candidates = dc
                        st_e.discard_candidates = dc

                act_j = Router(_battle_layers(jinx_pack)).decide(st_j)
                act_e = Router(_battle_layers(elise_pack)).decide(st_e)
                if st_j.ui_state in (UIState.ENEMY_TURN, UIState.BATTLE_END):
                    actionable = True
                else:
                    if act_j.action.type is not ActionType.NO_OP:
                        metrics["battle_jinx_actionable"] += 1
                        actionable = True
                    if act_e.action.type is not ActionType.NO_OP:
                        metrics["battle_elise_actionable"] += 1
                details["jinx_action"] = act_j.action.type.value
                details["elise_action"] = act_e.action.type.value
                details["mana"] = st_j.readings["mana"].value if st_j.readings.get("mana") else None
                details["hand_costs"] = [c.cost for c in st_j.hand]

        scene_counts[scene] += 1
        if scene != "unknown":
            metrics["recognized_scenes"] += 1
        else:
            metrics["unknown_scenes"] += 1
        if actionable:
            metrics["actionable_frames"] += 1

        records.append({
            "key": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": f"{path.parent.name}/{path.name}",
            "scene": scene,
            "actionable": actionable,
            "details": details,
        })

    return {
        "schema_version": 1,
        "unique_images": len(files),
        "key_scheme": "sha256",
        "metrics": dict(sorted(metrics.items())),
        "scene_counts": dict(sorted(scene_counts.items())),
        "records": records,
    }


def compare_reports(before: dict, after: dict) -> dict:
    """比较两次体检报告，返回指标增量与逐图场景迁移摘要。"""
    if before.get("key_scheme") != "sha256" or after.get("key_scheme") != "sha256":
        raise ValueError("reports must use sha256 keys; regenerate both with the same audit tool")
    all_metrics = sorted(set(before.get("metrics", {})) | set(after.get("metrics", {})))
    metric_deltas = {}
    for key in all_metrics:
        old_val = before.get("metrics", {}).get(key, 0)
        new_val = after.get("metrics", {}).get(key, 0)
        if old_val != new_val:
            metric_deltas[key] = {"before": old_val, "after": new_val, "delta": new_val - old_val}

    before_by_key = {r.get("key") or f"{r.get('parent', '')}/{r.get('file', '')}": r
                     for r in before.get("records", [])}
    after_by_key = {r.get("key") or f"{r.get('parent', '')}/{r.get('file', '')}": r
                    for r in after.get("records", [])}
    transitions: list[dict] = []
    for key in sorted(set(before_by_key) & set(after_by_key)):
        b_rec, a_rec = before_by_key[key], after_by_key[key]
        if b_rec["scene"] != a_rec["scene"] or b_rec["actionable"] != a_rec["actionable"]:
            transitions.append({
                "key": key,
                "scene_before": b_rec["scene"],
                "scene_after": a_rec["scene"],
                "actionable_before": b_rec["actionable"],
                "actionable_after": a_rec["actionable"],
            })
    return {
        "schema_version": 1,
        "metric_deltas": metric_deltas,
        "only_before": sorted(set(before_by_key) - set(after_by_key)),
        "only_after": sorted(set(after_by_key) - set(before_by_key)),
        "scene_transitions": transitions,
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dir",
        action="append",
        dest="dirs",
        help="要扫描的图片目录（可多次指定；默认扫描 tests/fixtures 与 research/archives）",
    )
    ap.add_argument("--out", help="将完整 JSON 报告写入文件")
    ap.add_argument("--compare", help="与指定的修改前 JSON 报告做增量对比")
    ap.add_argument("--json", action="store_true", help="向标准输出打印 JSON")
    args = ap.parse_args()

    target_dirs = (
        [Path(d) for d in args.dirs]
        if args.dirs
        else [root / "tests" / "fixtures", root / "research" / "archives"]
    )
    result = audit_corpus(target_dirs)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text(encoding="utf-8"))
        diff = compare_reports(baseline, result)
        if args.json:
            print(json.dumps(diff, ensure_ascii=False, indent=2))
            return
        print("=== 指标变化 (Before -> After) ===")
        for key, item in diff["metric_deltas"].items():
            sign = "+" if item["delta"] > 0 else ""
            print(f"  {key}: {item['before']} -> {item['after']} ({sign}{item['delta']})")
        print(f"仅基线存在：{len(diff['only_before'])} 张；仅本次存在：{len(diff['only_after'])} 张")
        print(f"=== 画面状态变化 ({len(diff['scene_transitions'])} 张) ===")
        for tr in diff["scene_transitions"]:
            print(
                f"  {tr['key']}: {tr['scene_before']}(act={tr['actionable_before']}) "
                f"-> {tr['scene_after']}(act={tr['actionable_after']})"
            )
        return

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    print(f"独立图片总数：{result['unique_images']}")
    print("核心指标：")
    for key, val in result["metrics"].items():
        print(f"  {key}: {val}")
    print("场景分布：")
    for key, val in result["scene_counts"].items():
        print(f"  {key}: {val}")


if __name__ == "__main__":
    main()
