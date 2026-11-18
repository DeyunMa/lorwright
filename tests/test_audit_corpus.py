"""离线截图语料体检与增量对比工具测试。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

from lorwright.core.perceive.normalize import Normalizer


def _load_audit_corpus():
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_corpus.py"
    spec = importlib.util.spec_from_file_location("audit_corpus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["audit_corpus"] = module
    spec.loader.exec_module(module)
    return module


def test_prepare_canvas_restores_documented_crop_and_skips_tiny_icons() -> None:
    mod = _load_audit_corpus()
    normalizer = Normalizer((1920, 1080))
    crop = np.full((685, 445, 3), 123, dtype=np.uint8)
    canvas, mode = mod.prepare_canvas(crop, normalizer)
    assert canvas is not None
    assert mode == "crop_445x685"
    x0, y0 = mod.CROP_PLACEMENTS[(685, 445)]
    assert canvas.shape == (1080, 1920, 3)
    assert int(canvas[y0, x0, 0]) == 123
    assert int(canvas[0, 0, 0]) == 0

    tiny = np.zeros((24, 16, 3), dtype=np.uint8)
    skipped, skip_mode = mod.prepare_canvas(tiny, normalizer)
    assert skipped is None
    assert skip_mode == "skipped_16x24"


def test_map_audit_requires_recognized_hero(monkeypatch) -> None:
    mod = _load_audit_corpus()
    monkeypatch.delattr(mod.mapnav_perceive, "locate_map_hero", raising=False)

    def unexpected(*args, **kwargs):
        raise AssertionError("must not infer a hero from the screen center")

    monkeypatch.setattr(mod, "reachable_nodes", unexpected)
    result = mod.evaluate_map_for_pack(np.zeros((1080, 1920, 3), dtype=np.uint8), mod.GenericPack())
    assert result == {"hero_found": False, "reachable": 0, "zoom_needed": False, "actionable": False}


def test_map_audit_uses_runtime_token_detector_when_available(monkeypatch) -> None:
    mod = _load_audit_corpus()
    monkeypatch.setattr(mod.mapnav_perceive, "locate_map_hero", lambda image: None, raising=False)

    class Pack:
        recognize_map_hero = staticmethod(lambda image: (960, 540))

    image = np.zeros((1, 1, 3), dtype=np.uint8)
    assert mod._resolve_map_hero(image, Pack()) is None
    token = (960, 540, 56)
    monkeypatch.setattr(mod.mapnav_perceive, "locate_map_hero", lambda image: token)
    assert mod._resolve_map_hero(image, Pack()) == token


def test_audit_corpus_evaluates_real_fixtures_and_compares_deltas() -> None:
    mod = _load_audit_corpus()
    sample_files = [
        Path("tests/fixtures/healer/f1-remaining-panel-20261118.png"),
        Path("tests/fixtures/screens/1080p_hand_expanded.png"),
    ]
    report = mod.audit_corpus(sample_files)
    assert report["schema_version"] == 1
    assert report["unique_images"] == 2
    assert report["metrics"]["evaluated_frames"] == 2
    assert report["scene_counts"]["healer"] == 1
    assert report["scene_counts"]["battle_my_turn_idle"] == 1
    assert report["metrics"]["battle_hand_costs_read"] == 6

    synthetic_before = {
        "schema_version": 1,
        "key_scheme": "sha256",
        "metrics": {**report["metrics"], "healer_actionable": 0},
        "records": [
            {**rec, "actionable": False} if rec["scene"] == "healer" else rec
            for rec in report["records"]
        ],
    }
    diff = mod.compare_reports(synthetic_before, report)
    assert diff["schema_version"] == 1
    assert diff["metric_deltas"]["healer_actionable"] == {
        "before": 0,
        "after": 1,
        "delta": 1,
    }
    assert len(diff["scene_transitions"]) == 1
    assert diff["only_before"] == [] and diff["only_after"] == []
    missing = {**report, "records": report["records"][:-1]}
    assert diff["scene_transitions"][0]["actionable_after"] is True
    assert mod.compare_reports(report, missing)["only_before"] == [report["records"][-1]["key"]]
    assert mod.GenericPack().name == "generic"


def test_labeled_adventure_frames_preserve_scene_and_numeric_evidence():
    mod = _load_audit_corpus()
    fixture_root = Path(__file__).parent / "fixtures"
    expectations = {
        "screens/weekly-list-20261115.png": ("weekly_list", {"stars": [1.5, 2, 2]}),
        "screens/weekly-two-detail-20261116.png": ("weekly_detail", {"stars": 2}),
        "screens/weekly-one-remaining.png": ("weekly_list", {"stars": [2]}),
        "screens/f1-astrologer-purchased-map-20261116.png": ("map", {"gold": 550}),
        "screens/f1-discard-candidates-20261117.png": ("battle_discard", {"discard_costs": [1, 1, 1, 6]}),
        "screens/f1-scholar-nine-mana-10cards-20261118.png": (
            "battle_my_turn_idle", {"mana": 9, "spell_mana": 3, "jinx_action": "play_card"},
        ),
        "continue/f1-silver-vault-20261118.png": ("adventure_silver_vault", {}),
        "continue/f1-silver-vault-reward-20261118.png": ("adventure_silver_vault_reward", {}),
    }
    report = mod.audit_corpus([fixture_root / source for source in expectations])
    assert len(report["records"]) == len(expectations)
    for record in report["records"]:
        expected_scene, expected_details = expectations[record["source"]]
        assert record["scene"] == expected_scene, record["source"]
        for field, expected in expected_details.items():
            value = record["details"][field]
            if field == "stars" and isinstance(value, list):
                value = sorted(value)
            assert value == expected, (record["source"], field)
