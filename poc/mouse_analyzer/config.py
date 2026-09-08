"""Configuration loading: CLI defaults and credential handling."""
from __future__ import annotations

import os
from pathlib import Path


def load_credentials(cred_path: str | Path = ".cred") -> None:
    """Load KEY=VALUE lines from a .cred file into os.environ.

    Existing environment variables take precedence and are not overwritten.
    Never logs or prints the secret values.
    """
    path = Path(cred_path)
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_api_key() -> str | None:
    """Return the Anthropic API key from the environment, if present."""
    return os.environ.get("ANTHROPIC_API_KEY")
