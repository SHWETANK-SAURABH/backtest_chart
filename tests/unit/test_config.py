"""Configuration handling."""

from pydantic import SecretStr

from app.core.config import Settings


def test_credentials_are_not_exposed_when_serialised() -> None:
    settings = Settings(dhan_access_token=SecretStr("secret-value"))
    assert "secret-value" not in settings.model_dump_json()
    assert "secret-value" not in repr(settings)
