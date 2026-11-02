"""JEV 降级链路：正常 / 报错 / 超时 / 未配置，都不能让主循环崩。"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lorwright.decide.jev import JevClient


class _Handler(BaseHTTPRequestHandler):
    mode = "ok"

    def do_POST(self):  # noqa: N802
        if self.mode == "slow":
            time.sleep(1.5)
        if self.mode == "error":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"boom")
            return

        body = b'{"choice": "\\u6253\\u51fa A"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静音
        pass


@pytest.fixture()
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_unconfigured_returns_none() -> None:
    c = JevClient(None, None)
    assert not c.enabled
    assert c.choose("ctx", ["A", "B"]) is None


def test_single_option_short_circuits() -> None:
    c = JevClient("http://127.0.0.1:1", None)
    assert c.choose("ctx", ["only"]) == "only"


def test_ok_response(server) -> None:
    _, url = server
    _Handler.mode = "ok"
    c = JevClient(url, "k", timeout=2)
    assert c.choose("ctx", ["打出 A", "打出 B"]) == "打出 A"


def test_server_error_falls_back(server) -> None:
    _, url = server
    _Handler.mode = "error"
    c = JevClient(url, "k", timeout=2)
    assert c.choose("ctx", ["A", "B"]) is None


def test_timeout_falls_back(server) -> None:
    _, url = server
    _Handler.mode = "slow"
    c = JevClient(url, "k", timeout=0.3)
    assert c.choose("ctx", ["A", "B"]) is None
