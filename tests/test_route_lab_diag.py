"""Offline checks for the route diagnostic's runtime perception inputs."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from tools.test_data import fixtures_root

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def diag():
    spec = spec_from_file_location("route_diag", ROOT / "tools/route_lab/diag.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_describe_preserves_runtime_token_and_radius(diag, monkeypatch, capsys):
    image = cv2.imread(str(fixtures_root() / "mapnav/f1-after-gold-zoomed-map-20261117.png"))
    assert image is not None
    token = diag.mapnav.locate_map_hero(image)
    assert token is not None and token.radius > 44
    locate = Mock(return_value=token)
    reachable = Mock(wraps=diag.mapnav.reachable_nodes)
    monkeypatch.setattr(diag.mapnav, "locate_map_hero", locate)
    monkeypatch.setattr(diag.mapnav, "reachable_nodes", reachable)

    diag.describe("zoomed", image)

    locate.assert_called_once_with(image)
    assert reachable.call_args_list
    assert all(call.kwargs["hero"] is token for call in reachable.call_args_list)
    output = capsys.readouterr().out
    assert f"radius={token.radius}" in output
    assert "'x': 1062, 'y': 331" in output


def test_describe_rejects_non_1080p_before_perception(diag, monkeypatch, capsys):
    locate = Mock()
    monkeypatch.setattr(diag.mapnav, "locate_map_hero", locate)
    diag.describe("720p", np.zeros((720, 1280, 3), dtype=np.uint8))
    locate.assert_not_called()
    assert "UNSUPPORTED (expected 1920×1080 BGR)" in capsys.readouterr().out
