"""共享测试夹具：隔离设备锁目录，按 session 缓存只读 fixtures 图像解码结果。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import pytest

from lorwright.core.runtime import session as runtime_session
from tools.test_data import fixtures_root


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
