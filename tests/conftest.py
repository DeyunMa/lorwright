"""共享测试夹具：隔离设备锁目录，避免与本机实机会话或并行测试互相抢锁。"""

from __future__ import annotations

from pathlib import Path

import pytest

from lorwright.core.runtime import session as runtime_session


@pytest.fixture(autouse=True)
def _isolate_device_lock_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock_root = tmp_path / "device-locks"
    monkeypatch.setattr(runtime_session, "_device_lock_root", lambda: lock_root)
