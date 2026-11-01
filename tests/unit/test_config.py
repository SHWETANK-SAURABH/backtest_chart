"""Configuration handling."""

from pydantic import SecretStr

from app.core.config import Settings
from app.data.providers.registry import is_configured


def test_credentials_are_not_exposed_when_serialised() -> None:
    settings = Settings(dhan_access_token=SecretStr("secret-value"))
    assert "secret-value" not in settings.model_dump_json()
    assert "secret-value" not in repr(settings)


def test_blank_token_from_the_env_template_counts_as_not_configured() -> None:
    settings = Settings(dhan_access_token="")  # type: ignore[arg-type]
    assert settings.dhan_access_token is None
    assert not is_configured("dhan", settings)
