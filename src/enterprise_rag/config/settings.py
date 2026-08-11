"""Application settings loaded from YAML files and environment variables.

Precedence (highest first), matching ``specs/16-deployment.md``:

1. Explicit constructor / CLI overrides
2. Environment variables
3. Environment-specific YAML (``config/{environment}.yaml``)
4. Default YAML (``config/default.yaml``)
5. Code defaults
"""

from __future__ import annotations

import os
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Self, cast

import yaml
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from enterprise_rag.domain.retrieval import RetrievalMode
from enterprise_rag.shared.exceptions import ConfigurationError


class EnvironmentName(StrEnum):
    """Deployed application environments."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ModelImplementation(StrEnum):
    """Selectable model adapter implementation."""

    LANGCHAIN = "langchain"
    OPENAI_DIRECT = "openai_direct"


class OcrMode(StrEnum):
    """OCR execution policy."""

    AUTO = "auto"
    ALWAYS = "always"
    NEVER = "never"


class ParserFailureMode(StrEnum):
    """Parser failure handling policy."""

    FAIL_FAST = "fail_fast"
    FALLBACK = "fallback"
    BEST_EFFORT = "best_effort"


class AppSettings(BaseModel):
    """Core application identity and logging."""

    environment: EnvironmentName = EnvironmentName.DEVELOPMENT
    log_level: str = "INFO"
    service_name: str = "enterprise-rag"
    json_logs: bool = False
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )


class PostgresSettings(BaseModel):
    """PostgreSQL connection settings."""

    host: str = "localhost"
    port: int = 5432
    db: str = "enterprise_rag"
    user: str = "enterprise_rag"
    password: SecretStr = SecretStr("")
    ssl_mode: str = "prefer"
    pool_size: int = 10
    max_overflow: int = 20

    @property
    def async_dsn(self) -> str:
        """Return an asyncpg SQLAlchemy DSN without embedding secrets in repr."""
        password = self.password.get_secret_value()
        auth = self.user if not password else f"{self.user}:{password}"
        return f"postgresql+asyncpg://{auth}@{self.host}:{self.port}/{self.db}?ssl={self.ssl_mode}"


class RedisSettings(BaseModel):
    """Redis connection settings."""

    url: SecretStr = SecretStr("redis://localhost:6379/0")


class MinioSettings(BaseModel):
    """MinIO object-store settings."""

    endpoint: str = "localhost:9000"
    access_key: SecretStr = SecretStr("minioadmin")
    secret_key: SecretStr = SecretStr("minioadmin")
    secure: bool = False
    bucket: str = "enterprise-rag"


class QdrantSettings(BaseModel):
    """Qdrant vector-store settings."""

    url: str = "http://localhost:6333"
    api_key: SecretStr | None = None
    collection_chunks: str = "rag_chunks"
    collection_entities: str = "rag_entities"
    collection_communities: str = "rag_communities"


class Neo4jSettings(BaseModel):
    """Neo4j graph-store settings."""

    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: SecretStr = SecretStr("")


class ModelSettings(BaseModel):
    """Model provider and role configuration."""

    implementation: ModelImplementation = ModelImplementation.LANGCHAIN
    provider: str = "openai"
    text_model: str = "gpt-4.1"
    vision_model: str = "gpt-4.1"
    extraction_model: str = "gpt-4.1"
    summarization_model: str = "gpt-4.1"
    query_model: str = "gpt-4.1"
    answer_model: str = "gpt-4.1"
    embedding_model: str = "text-embedding-3-large"
    api_key: SecretStr | None = None
    request_timeout_seconds: float = 60.0
    max_retries: int = 3


class ParserProfileSettings(BaseModel):
    """Named parser primary/fallback chain."""

    primary: str
    fallbacks: list[str] = Field(default_factory=list)


class ParsingSettings(BaseModel):
    """Parser routing and failure policy."""

    default_profile: str = "balanced"
    failure_mode: ParserFailureMode = ParserFailureMode.FALLBACK
    profiles: dict[str, ParserProfileSettings] = Field(
        default_factory=lambda: {
            "balanced": ParserProfileSettings(
                primary="docling",
                fallbacks=["mineru", "marker", "paddleocr"],
            ),
            "scientific": ParserProfileSettings(
                primary="mineru",
                fallbacks=["docling", "marker"],
            ),
            "scanned": ParserProfileSettings(
                primary="paddleocr",
                fallbacks=["mineru"],
            ),
            "fast": ParserProfileSettings(
                primary="docling",
                fallbacks=["marker"],
            ),
            "accurate": ParserProfileSettings(
                primary="mineru",
                fallbacks=["docling", "marker", "paddleocr"],
            ),
        }
    )


class OcrSettings(BaseModel):
    """OCR engine settings."""

    mode: OcrMode = OcrMode.AUTO
    engine: str = "paddleocr"
    language: str = "en"
    minimum_confidence: float = 0.70


class MultimodalSettings(BaseModel):
    """Context-aware multimodal enrichment toggles."""

    enabled: bool = True
    process_images: bool = True
    process_charts: bool = True
    process_tables: bool = True
    process_equations: bool = True
    context_before_elements: int = 3
    context_after_elements: int = 3
    maximum_context_tokens: int = 1800


class ChunkingSettings(BaseModel):
    """Hierarchical multimodal chunking defaults."""

    strategy: str = "multimodal_hierarchical"
    parent_target_tokens: int = 2500
    child_target_tokens: int = 600
    overlap_tokens: int = 80
    preserve_tables: bool = True
    preserve_equations: bool = True
    preserve_figure_context: bool = True
    generate_table_row_chunks: bool = True
    generate_image_chunks: bool = True
    generate_composite_chunks: bool = True


class RetrievalSettings(BaseModel):
    """Default retrieval behaviour."""

    default_mode: RetrievalMode = RetrievalMode.AUTO
    top_k: int = 12
    graph_depth: int = 2
    rerank: bool = True


class SecuritySettings(BaseModel):
    """Upload limits and authentication controls."""

    max_upload_bytes: int = 104_857_600
    max_pages: int = 2_000
    max_zip_entries: int = 10_000
    max_zip_uncompressed_bytes: int = 512 * 1024 * 1024
    max_zip_compression_ratio: float = 100.0
    parser_timeout_seconds: float = 120.0
    malware_scan_enabled: bool = False
    audit_retention_days: int = 30
    allowed_mime_types: list[str] = Field(
        default_factory=lambda: [
            "application/pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "image/png",
            "image/jpeg",
            "image/tiff",
            "image/webp",
            "text/html",
            "text/markdown",
            "text/plain",
        ]
    )
    url_allowed_schemes: list[str] = Field(default_factory=lambda: ["https"])
    url_max_redirects: int = 3
    url_timeout_seconds: float = 30.0
    # Authentication (production: AUTH_ENABLED=true + AUTH_JWT_SECRET >= 32 chars)
    auth_enabled: bool = False
    auth_jwt_secret: str = ""
    auth_jwt_ttl_seconds: int = 43_200
    auth_cookie_name: str = "erag_session"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    api_service_key: str = ""


class ConcurrencySettings(BaseModel):
    """Bounded concurrency limits."""

    global_jobs: int = 8
    parser_jobs: int = 2
    ocr_pages: int = 4
    vision_calls: int = 4
    text_llm_calls: int = 8
    embeddings: int = 8
    storage_writes: int = 16


class WorkerSettings(BaseModel):
    """Ingestion worker retry and dead-letter defaults."""

    max_stage_attempts: int = 3
    retry_base_delay_seconds: float = 0.05
    retry_max_delay_seconds: float = 2.0
    retry_jitter: bool = False
    poll_interval_seconds: float = 0.01
    lease_seconds: float = 60.0


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigurationError(
            f"Invalid YAML configuration file: {path}",
            details={"path": str(path)},
            cause=exc,
        ) from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"Configuration root must be a mapping: {path}",
            details={"path": str(path), "type": type(raw).__name__},
        )
    return raw


def load_yaml_config(config_dir: Path, environment: str) -> dict[str, Any]:
    """Load and merge default + environment YAML configuration files."""
    default_data = _load_yaml_file(config_dir / "default.yaml")
    env_data = _load_yaml_file(config_dir / f"{environment}.yaml")
    return _deep_merge(default_data, env_data)


class Settings(BaseSettings):
    """Root settings object for the platform."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    app: AppSettings = Field(default_factory=AppSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    minio: MinioSettings = Field(default_factory=MinioSettings)
    qdrant: QdrantSettings = Field(default_factory=QdrantSettings)
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    models: ModelSettings = Field(default_factory=ModelSettings)
    parsing: ParsingSettings = Field(default_factory=ParsingSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    multimodal: MultimodalSettings = Field(default_factory=MultimodalSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    retrieval: RetrievalSettings = Field(default_factory=RetrievalSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
    worker: WorkerSettings = Field(default_factory=WorkerSettings)

    config_dir: Path = Path("config")

    @field_validator("config_dir", mode="before")
    @classmethod
    def _coerce_config_dir(cls, value: Any) -> Path:
        return Path(value) if not isinstance(value, Path) else value

    @model_validator(mode="after")
    def _validate_parser_profile(self) -> Self:
        if self.parsing.default_profile not in self.parsing.profiles:
            raise ConfigurationError(
                "Default parser profile is not defined in profiles",
                details={
                    "default_profile": self.parsing.default_profile,
                    "available": sorted(self.parsing.profiles),
                },
            )
        return self

    @classmethod
    def from_config_dir(
        cls,
        config_dir: Path | str | None = None,
        *,
        environment: str | None = None,
        env_file: Path | str | None = ".env",
    ) -> Settings:
        """Build settings from YAML files, then apply environment overrides."""
        resolved_dir = Path(
            config_dir
            or os.environ.get("APP_CONFIG_DIR")
            or os.environ.get("CONFIG_DIR")
            or "config"
        )
        env_name = (
            environment
            or os.environ.get("APP_ENVIRONMENT")
            or os.environ.get("ENVIRONMENT")
            or "development"
        )
        yaml_data = load_yaml_config(resolved_dir, env_name)

        # Flatten nested YAML into env-style nested fields for BaseSettings.
        init_data: dict[str, Any] = dict(yaml_data)
        init_data["config_dir"] = resolved_dir
        if "app" not in init_data:
            init_data["app"] = {}
        if isinstance(init_data["app"], dict):
            init_data["app"].setdefault("environment", env_name)

        # Ensure flat .env keys are visible even when the shell did not export them.
        # pydantic-settings loads `_env_file` later; OpenAI mapping needs os.environ now.
        if env_file:
            env_path = Path(env_file)
            if env_path.is_file():
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip("'").strip('"')
                    os.environ.setdefault(key, value)

        # Map conventional OpenAI env vars into models.* when present.
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            models = dict(init_data.get("models") or {})
            models.setdefault("api_key", openai_key)
            for role, env_var in (
                ("text_model", "OPENAI_TEXT_MODEL"),
                ("vision_model", "OPENAI_VISION_MODEL"),
                ("extraction_model", "OPENAI_EXTRACTION_MODEL"),
                ("summarization_model", "OPENAI_SUMMARIZATION_MODEL"),
                ("query_model", "OPENAI_QUERY_MODEL"),
                ("answer_model", "OPENAI_ANSWER_MODEL"),
                ("embedding_model", "OPENAI_EMBEDDING_MODEL"),
            ):
                if os.environ.get(env_var):
                    models[role] = os.environ[env_var]
            init_data["models"] = models

        # Accept both nested (POSTGRES__HOST) and flat (POSTGRES_HOST) env keys.
        _apply_flat_store_env(init_data)

        try:
            # `_env_file` is supported by pydantic-settings at runtime; cast keeps mypy strict.
            builder = cast(Any, cls)
            return cast(Settings, builder(_env_file=env_file, **init_data))
        except ConfigurationError:
            raise
        except Exception as exc:
            raise ConfigurationError(
                "Failed to load application settings",
                details={"config_dir": str(resolved_dir), "environment": env_name},
                cause=exc,
            ) from exc


def _apply_flat_store_env(init_data: dict[str, Any]) -> None:
    """Merge conventional flat env vars into nested settings sections."""
    postgres = dict(init_data.get("postgres") or {})
    for field, env_name in (
        ("host", "POSTGRES_HOST"),
        ("port", "POSTGRES_PORT"),
        ("db", "POSTGRES_DB"),
        ("user", "POSTGRES_USER"),
        ("password", "POSTGRES_PASSWORD"),
        ("ssl_mode", "POSTGRES_SSL_MODE"),
    ):
        if os.environ.get(env_name):
            postgres[field] = os.environ[env_name]
    if postgres:
        init_data["postgres"] = postgres

    if os.environ.get("REDIS_URL"):
        init_data["redis"] = {**(init_data.get("redis") or {}), "url": os.environ["REDIS_URL"]}

    minio = dict(init_data.get("minio") or {})
    for field, env_name in (
        ("endpoint", "MINIO_ENDPOINT"),
        ("access_key", "MINIO_ACCESS_KEY"),
        ("secret_key", "MINIO_SECRET_KEY"),
        ("secure", "MINIO_SECURE"),
        ("bucket", "MINIO_BUCKET"),
    ):
        if os.environ.get(env_name) is not None and os.environ.get(env_name) != "":
            value: Any = os.environ[env_name]
            if field == "secure":
                value = str(value).lower() in {"1", "true", "yes"}
            minio[field] = value
    if minio:
        init_data["minio"] = minio

    qdrant = dict(init_data.get("qdrant") or {})
    if os.environ.get("QDRANT_URL"):
        qdrant["url"] = os.environ["QDRANT_URL"]
    if os.environ.get("QDRANT_API_KEY"):
        qdrant["api_key"] = os.environ["QDRANT_API_KEY"]
    if qdrant:
        init_data["qdrant"] = qdrant

    neo4j = dict(init_data.get("neo4j") or {})
    for field, env_name in (
        ("uri", "NEO4J_URI"),
        ("user", "NEO4J_USER"),
        ("password", "NEO4J_PASSWORD"),
    ):
        if os.environ.get(env_name):
            neo4j[field] = os.environ[env_name]
    if neo4j:
        init_data["neo4j"] = neo4j

    security = dict(init_data.get("security") or {})
    if os.environ.get("MAX_UPLOAD_BYTES"):
        security["max_upload_bytes"] = int(os.environ["MAX_UPLOAD_BYTES"])
    if os.environ.get("MAX_PAGES"):
        security["max_pages"] = int(os.environ["MAX_PAGES"])
    auth_enabled = os.environ.get("AUTH_ENABLED")
    if auth_enabled is not None:
        security["auth_enabled"] = auth_enabled.strip().lower() in {"1", "true", "yes", "on"}
    if os.environ.get("AUTH_JWT_SECRET"):
        security["auth_jwt_secret"] = os.environ["AUTH_JWT_SECRET"]
    if os.environ.get("AUTH_JWT_TTL_SECONDS"):
        security["auth_jwt_ttl_seconds"] = int(os.environ["AUTH_JWT_TTL_SECONDS"])
    if os.environ.get("AUTH_COOKIE_NAME"):
        security["auth_cookie_name"] = os.environ["AUTH_COOKIE_NAME"]
    if os.environ.get("AUTH_COOKIE_SECURE"):
        security["auth_cookie_secure"] = os.environ["AUTH_COOKIE_SECURE"].strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    if os.environ.get("AUTH_COOKIE_SAMESITE"):
        security["auth_cookie_samesite"] = os.environ["AUTH_COOKIE_SAMESITE"].strip().lower()
    if os.environ.get("API_SERVICE_KEY"):
        security["api_service_key"] = os.environ["API_SERVICE_KEY"]
    if security:
        init_data["security"] = security


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached settings instance."""
    return Settings.from_config_dir()


def clear_settings_cache() -> None:
    """Clear the settings LRU cache. Intended for tests."""
    get_settings.cache_clear()
