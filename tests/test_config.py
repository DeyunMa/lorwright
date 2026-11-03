"""配置加载：环境变量与 .env 的优先级。"""

from pathlib import Path

from lorwright.config import load_settings


def test_credentials_come_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    """账号密码只从环境变量读，不写进 settings.yaml。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOR_USERNAME", raising=False)
    monkeypatch.delenv("LOR_PASSWORD", raising=False)
    (tmp_path / ".env").write_text(
        "LOR_USERNAME=someone\nLOR_PASSWORD=secret\n", encoding="utf-8"
    )

    settings = load_settings(tmp_path / "missing.yaml")

    assert settings.lor_username == "someone"
    assert settings.lor_password == "secret"


def test_missing_credentials_are_none(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOR_USERNAME", raising=False)
    monkeypatch.delenv("LOR_PASSWORD", raising=False)

    settings = load_settings(tmp_path / "missing.yaml")

    assert settings.lor_username is None
    assert settings.lor_password is None
