"""配置加载：环境变量与 .env 的优先级。"""

from pathlib import Path

import pytest

from lorwright.core.config import load_settings


def test_credentials_come_from_dotenv(tmp_path: Path, monkeypatch) -> None:
    """账号密码只从环境变量读，不写进 settings.yaml。"""
    monkeypatch.delenv("LORWRIGHT_ENV_FILE", raising=False)
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
    monkeypatch.delenv("LORWRIGHT_ENV_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOR_USERNAME", raising=False)
    monkeypatch.delenv("LOR_PASSWORD", raising=False)

    settings = load_settings(tmp_path / "missing.yaml")

    assert settings.lor_username is None
    assert settings.lor_password is None


def test_explicit_env_file_and_environment_precedence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOR_USERNAME", "environment-user")
    monkeypatch.delenv("LOR_PASSWORD", raising=False)
    (tmp_path / ".env").write_text("LOR_PASSWORD=default-password\n", encoding="utf-8")
    custom = tmp_path / "custom.env"
    custom.write_text("LOR_USERNAME=file-user\nLOR_PASSWORD=file-password\n", encoding="utf-8")
    monkeypatch.setenv("LORWRIGHT_ENV_FILE", str(custom))

    settings = load_settings(tmp_path / "missing.yaml")

    assert settings.lor_username == "environment-user"
    assert settings.lor_password == "file-password"


def test_missing_explicit_env_file_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LORWRIGHT_ENV_FILE", str(tmp_path / "missing.env"))
    with pytest.raises(FileNotFoundError, match="LORWRIGHT_ENV_FILE"):
        load_settings(tmp_path / "missing.yaml")
