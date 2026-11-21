"""共享测试夹具：隔离设备锁目录，按 session 缓存只读 fixtures 图像解码结果。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import cv2
import pytest

from lorwright.core.runtime import session as runtime_session
from tools.test_data import fixtures_root

_HEAVY_VISION_SMOKE_KEEP: dict[str, frozenset[str]] = {
    "test_mapnav.py": frozenset({
        "test_weekly_home_follows_lit_route_to_first_power_diamond",
        "test_completed_node_follows_cyan_route_to_visible_bottom_gold_target",
        "test_map_panels_are_not_navigable",
        "test_generic_elise_token_and_current_battle",
        "test_interrupted_event_node_is_reentry_target_while_routes_stay_locked",
        "test_full_boss_crest_requires_the_lit_route",
        "test_next_node_samples_all_reachable_branches_with_rng",
    }),
    "test_adventure.py": frozenset({
        "test_bottom_map_target_is_revealed_once_before_click",
        "test_adventure_never_clicks_an_expired_input_frame",
        "test_node_panel_travel_then_fight",
        "test_node_transition_timeout_stops_without_repeating_battle",
        "test_home_world_weekly_lowest_detail_start_and_map",
        "test_healer_continues_to_the_next_node_after_completion",
        "test_shop_with_different_merchant_leaves_and_verifies_map",
        "test_astrologer_is_a_recognized_adventure_successor",
        "test_final_settlement_handles_optional_task_before_outer_screen",
        "test_service_error_that_stays_stops_without_repeating",
        "test_resume_adventure_clicks_once_and_accepts_map",
        "test_task_reward_without_button_does_not_tap",
    }),
    "test_audit_corpus.py": frozenset({
        "test_prepare_canvas_restores_documented_crop_and_skips_tiny_icons",
        "test_map_audit_requires_recognized_hero",
        "test_map_audit_uses_runtime_token_detector_when_available",
    }),
    "test_perception.py": frozenset({
        "test_assets_exist",
        "test_battle_turn2",
        "test_mulligan_is_not_my_turn",
        "test_blocking_reads_enemy_attackers_from_enemy_combat",
        "test_read_numbers",
        "test_targeting_button_is_detected",
    }),
    "test_units.py": frozenset({
        "test_finds_my_units",
        "test_finds_enemy_units",
        "test_empty_board_yields_no_units",
        "test_attack_token_detected",
        "test_no_attack_token",
    }),
    "test_optional_choice.py": frozenset({
        "test_real_choice_routes_to_one_skip_with_existing_champion_layers",
        "test_skip_requires_choice_and_only_succeeds_on_known_battle_successor",
        "test_play_releases_pending_for_choice_without_claiming_play_success",
    }),
}


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "slow: heavy real-image vision regression or corpus sweep; skip with -m 'not slow' for quick smoke checks",
    )
    config.addinivalue_line(
        "markers",
        "smoke: pin a test inside the quick -m 'not slow' smoke layer even in heavy vision modules",
    )
    if os.environ.get("PYTEST_XDIST_WORKER"):
        cv2.setNumThreads(2)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-mark heavy 1080p vision/corpus modules slow except core smoke anchors."""
    slow_marker = pytest.mark.slow
    for item in items:
        keep = _HEAVY_VISION_SMOKE_KEEP.get(item.path.name)
        if keep is None:
            continue
        if (
            item.get_closest_marker("smoke") is not None
            or item.get_closest_marker("slow") is not None
        ):
            continue
        base_name = getattr(item, "originalname", item.name)
        if base_name not in keep:
            item.add_marker(slow_marker)


@pytest.fixture(autouse=True)
def _isolate_device_lock_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock_root = tmp_path / "device-locks"
    monkeypatch.setattr(runtime_session, "_device_lock_root", lambda: lock_root)


@pytest.fixture(scope="session", autouse=True)
def _cache_fixture_imread():
    """缓存库外 fixtures 图片解码结果，每次返回独立可写副本以避免测试间污染。"""
    try:
        fixtures_dir = fixtures_root().resolve()
    except FileNotFoundError:
        yield
        return

    real_imread = cv2.imread

    @lru_cache(maxsize=64)
    def _decode(resolved_path: str, flags: int):
        return real_imread(resolved_path, flags)

    def _cached_imread(filename, flags: int = cv2.IMREAD_COLOR):
        if isinstance(filename, (str, Path)):
            try:
                resolved = Path(filename).resolve()
                if resolved.is_relative_to(fixtures_dir):
                    cached = _decode(str(resolved), int(flags))
                    return None if cached is None else cached.copy()
            except OSError:
                pass
        return real_imread(filename, flags)

    cv2.imread = _cached_imread
    try:
        yield
    finally:
        cv2.imread = real_imread
        _decode.cache_clear()
