"""tools/test_data.py 的 --check 核对逻辑与 conftest 设备锁隔离测试。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lorwright.core.runtime import session as runtime_session
from tools import test_data


def test_conftest_isolates_device_lock_root(tmp_path: Path) -> None:
    lock_root = runtime_session._device_lock_root()
    assert lock_root.is_relative_to(tmp_path)


def test_check_fixtures_reports_missing_and_undocumented(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    fixtures_dir = data_dir / "fixtures"
    (fixtures_dir / "screens").mkdir(parents=True)
    (fixtures_dir / "healer").mkdir(parents=True)
    (fixtures_dir / "screens" / "a.png").write_bytes(b"a")
    (fixtures_dir / "healer" / "new_doc.png").write_bytes(b"b")
    (fixtures_dir / "healer" / "new_undoc.png").write_bytes(b"c")

    meta_dir = tmp_path / "meta"
    (meta_dir / "healer").mkdir(parents=True)
    (meta_dir / "README.md").write_text("记录 `healer/new_doc.png`。\n", encoding="utf-8")

    report = test_data.check_fixtures(
        data_dir,
        baseline={"screens/a.png", "screens/missing.png"},
        meta_root=meta_dir,
    )
    assert report["ok"] is False
    assert report["missing_from_baseline"] == ["screens/missing.png"]
    assert report["local_only"] == ["healer/new_doc.png", "healer/new_undoc.png"]
    assert report["undocumented_local_only"] == ["healer/new_undoc.png"]


def test_check_fixtures_passes_when_baseline_complete_and_local_only_documented(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    fixtures_dir = data_dir / "fixtures"
    (fixtures_dir / "mapnav").mkdir(parents=True)
    (fixtures_dir / "mapnav" / "base.png").write_bytes(b"a")
    (fixtures_dir / "mapnav" / "extra.png").write_bytes(b"b")

    meta_dir = tmp_path / "meta"
    (meta_dir / "mapnav").mkdir(parents=True)
    (meta_dir / "mapnav" / "README.md").write_text("新增 `extra.png`。\n", encoding="utf-8")

    report = test_data.check_fixtures(
        data_dir,
        baseline={"mapnav/base.png"},
        meta_root=meta_dir,
    )
    assert report["ok"] is True
    assert report["missing_from_baseline"] == []
    assert report["local_only"] == ["mapnav/extra.png"]
    assert report["undocumented_local_only"] == []


def test_main_check_json_exit_code(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        test_data,
        "check_fixtures",
        lambda root: {
            "ok": True,
            "fixtures_dir": str(root / "fixtures"),
            "baseline_count": 1,
            "local_count": 1,
            "missing_from_baseline": [],
            "local_only": [],
            "undocumented_local_only": [],
        },
    )
    test_data.main(["--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
