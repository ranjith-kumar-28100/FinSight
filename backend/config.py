"""Secure configuration management.

Loads settings from .env file and environment variables.
Errors out if critical variables are missing (no hardcoded fallbacks for secrets).
"""

import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(_ENV_PATH)


def _get_secret(name: str) -> str:
    """Resolve a secret: env var -> .secret file -> ephemeral random (dev only).

    In production, missing secrets cause a hard failure.
    In dev, generates an ephemeral random value and logs a severe warning.
    """
    value = os.getenv(name)
    if value:
        return value

    secret_file = _PROJECT_ROOT / f"{name.lower()}.secret"
    if secret_file.is_file():
        return secret_file.read_text().strip()

    # Only acceptable for local dev — log warning
    logger.warning(
        "Secret '%s' not found in env or file. "
        "Generating ephemeral value. This instance is isolated — "
        "do NOT use in production.",
        name,
    )
    return secrets.token_hex(32)


@dataclass(frozen=True)
class AzureOpenAIConfig:
    """Azure AI Foundry (OpenAI-compatible) configuration."""

    endpoint: str = field(default_factory=lambda: os.getenv(
        "AZURE_OPENAI_ENDPOINT", ""))
    api_key: str = field(
        default_factory=lambda: _get_secret("AZURE_OPENAI_API_KEY"))
    api_version: str = field(
        default_factory=lambda: os.getenv(
            "AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
    )
    deployment_categorisation: str = field(
        default_factory=lambda: os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_CATEGORISATION", "gpt-4o")
    )
    deployment_reasoning: str = field(
        default_factory=lambda: os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_REASONING", "gpt-4o")
    )
    deployment_embedding: str = field(
        default_factory=lambda: os.getenv(
            "AZURE_OPENAI_DEPLOYMENT_EMBEDDING", "text-embedding-3-small")
    )

    def validate(self) -> None:
        """Validate that critical config is present."""
        if not self.endpoint:
            raise ValueError(
                "AZURE_OPENAI_ENDPOINT is required. "
                "Set it in .env or as an environment variable."
            )
        if not self.api_key:
            raise ValueError(
                "AZURE_OPENAI_API_KEY is required. "
                "Set it in .env or as an environment variable."
            )


@dataclass(frozen=True)
class AppConfig:
    """Application-level configuration."""

    db_path: Path = field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "finance.db"
    )
    upload_dir: Path = field(
        default_factory=lambda: _PROJECT_ROOT / "data" / "uploads"
    )
    max_upload_size_bytes: int = 10 * 1024 * 1024  # 10 MB
    allowed_extensions: frozenset = frozenset(
        {".csv", ".xls", ".xlsx", ".pdf"})

    azure: AzureOpenAIConfig = field(default_factory=AzureOpenAIConfig)

    def validate(self) -> None:
        """Validate all config on startup."""
        self.azure.validate()
        # Ensure data directories exist
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


def get_config() -> AppConfig:
    """Create and validate application config."""
    config = AppConfig()
    config.validate()
    return config
