"""Centralized environment-driven settings for database access.

This module reads connection details from a project-level `.env` file and
exposes helpers that return dictionaries compatible with psycopg2.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Dict
import os

# The repository root is one level above the `historic_optionChain` package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ENV_PATH = _REPO_ROOT / ".env"

_REQUIRED_DB_KEYS = {
    "DB": ("database", "Name of the PostgreSQL database"),
    "USER": ("user", "Database user"),
    "PASSWORD": ("password", "Database user password"),
}

_OPTIONAL_DEFAULTS = {
    "HOST": ("host", "localhost"),
    "PORT": ("port", "5432"),
}


def _parse_line(line: str) -> tuple[str, str] | None:
    """Parse a single line from an .env file.

    Supports comments, whitespace trimming, and quoted values.
    Returns ``None`` for blank or comment lines.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    return key, value


@lru_cache(maxsize=1)
def load_env(env_path: Path | None = None) -> None:
    """Load key/value pairs from the repo-level .env into ``os.environ``.

    Existing environment variables take precedence over anything declared in
    the file so that operators may override values at runtime.
    """
    path = env_path or _DEFAULT_ENV_PATH
    if not path.exists():
        return

    try:
        for line in path.read_text().splitlines():
            parsed = _parse_line(line)
            if not parsed:
                continue
            key, value = parsed
            os.environ.setdefault(key, value)
    except OSError as exc:
        raise RuntimeError(f"Unable to read environment file at {path}: {exc}") from exc


def _compose_env_key(prefix: str, key: str) -> str:
    return f"{prefix}_{key}"


def _get_env_value(key: str, description: str, default: str | None = None) -> str:
    load_env()
    value = os.environ.get(key, default)
    if value is None:
        raise RuntimeError(
            f"Missing required environment variable '{key}' ({description}). "
            "Add it to your .env file or export it before running the scripts."
        )
    return value


def get_db_config(prefix: str = "POSTGRES") -> Dict[str, str]:
    """Return psycopg2-ready keyword arguments for the given database prefix."""
    config: Dict[str, str] = {}
    for key, (config_key, description) in _REQUIRED_DB_KEYS.items():
        env_key = _compose_env_key(prefix, key)
        config[config_key] = _get_env_value(env_key, description)

    for key, (config_key, default) in _OPTIONAL_DEFAULTS.items():
        env_key = _compose_env_key(prefix, key)
        config[config_key] = _get_env_value(env_key, description=f"Optional default for {config_key}", default=default)

    return config


def get_database_url(prefix: str = "POSTGRES") -> str:
    """Return a PostgreSQL URL string (useful for SQLAlchemy or diagnostics)."""
    cfg = get_db_config(prefix=prefix)
    user = cfg["user"]
    password = cfg["password"]
    host = cfg["host"]
    port = cfg["port"]
    database = cfg["database"]
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"
