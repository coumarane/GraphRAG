"""Settings loading unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from graph_rag.config.settings import (
    EnvironmentName,
    ModelImplementation,
    RetrievalMode,
    Settings,
    clear_settings_cache,
    load_yaml_config,
)
from graph_rag.shared.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_load_yaml_merges_environment_overrides(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(
        yaml.safe_dump(
            {
                "app": {"environment": "development", "log_level": "INFO"},
                "retrieval": {"top_k": 12},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "development.yaml").write_text(
        yaml.safe_dump({"app": {"log_level": "DEBUG"}, "retrieval": {"top_k": 5}}),
        encoding="utf-8",
    )

    merged = load_yaml_config(tmp_path, "development")
    assert merged["app"]["log_level"] == "DEBUG"
    assert merged["retrieval"]["top_k"] == 5


def test_settings_from_repo_config() -> None:
    config_dir = Path(__file__).resolve().parents[2] / "config"
    settings = Settings.from_config_dir(
        config_dir,
        environment="development",
        env_file=None,
    )
    assert settings.app.environment == EnvironmentName.DEVELOPMENT
    assert settings.app.log_level == "DEBUG"
    assert settings.parsing.default_profile == "balanced"
    assert "scientific" in settings.parsing.profiles
    assert settings.models.implementation == ModelImplementation.LANGCHAIN
    assert settings.retrieval.default_mode == RetrievalMode.AUTO
    assert settings.multimodal.maximum_context_tokens == 1800
    assert settings.security.max_pages == 2000


def test_invalid_default_profile_raises(tmp_path: Path) -> None:
    (tmp_path / "default.yaml").write_text(
        yaml.safe_dump(
            {
                "parsing": {
                    "default_profile": "missing",
                    "profiles": {"balanced": {"primary": "docling", "fallbacks": []}},
                }
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigurationError, match="Default parser profile"):
        Settings.from_config_dir(tmp_path, environment="development", env_file=None)


def test_openai_env_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "default.yaml").write_text(
        yaml.safe_dump({"app": {"environment": "development"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")

    settings = Settings.from_config_dir(
        tmp_path,
        environment="development",
        env_file=None,
    )
    assert settings.models.api_key is not None
    assert settings.models.api_key.get_secret_value() == "sk-test"
    assert settings.models.embedding_model == "text-embedding-3-small"
