"""Runtime settings, read from environment variables (prefix OTST_). See .env.example."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(os.environ.get(name, default))
    except ValueError:
        v = default
    return min(max(v, lo), hi)


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [x.strip() for x in raw.split(",") if x.strip()]


DEFAULT_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]


@dataclass(frozen=True)
class Settings:
    app_name: str = "OT Sentinel Twin"
    version: str = "0.1.0"
    database_url: str = field(
        default_factory=lambda: os.environ.get("OTST_DATABASE_URL", "sqlite:///./data/ot_sentinel.db")
    )
    cors_origins: list[str] = field(default_factory=lambda: _list("OTST_CORS_ORIGINS", DEFAULT_ORIGINS))
    # State-changing API calls are refused when read_only is true (public demo deployments).
    read_only: bool = field(default_factory=lambda: _bool("OTST_READ_ONLY", False))
    # Optional shared secret for state-changing calls (header X-API-Key). Never commit a value.
    api_token: str | None = field(default_factory=lambda: os.environ.get("OTST_API_TOKEN") or None)
    max_body_bytes: int = field(default_factory=lambda: _int("OTST_MAX_BODY_BYTES", 65536, 1024, 1_048_576))
    rate_limit_per_minute: int = field(
        default_factory=lambda: _int("OTST_RATE_LIMIT_PER_MINUTE", 240, 1, 100_000)
    )
    retention_runs: int = field(default_factory=lambda: _int("OTST_RETENTION_RUNS", 12, 1, 1000))
    max_samples_per_run: int = field(
        default_factory=lambda: _int("OTST_MAX_SAMPLES_PER_RUN", 60_000, 1000, 2_000_000)
    )
    autostart: bool = field(default_factory=lambda: _bool("OTST_AUTOSTART", True))
    demo_mode: bool = field(default_factory=lambda: _bool("OTST_DEMO_MODE", False))
    max_speed: int = field(default_factory=lambda: _int("OTST_MAX_SPEED", 10, 1, 50))
    ws_max_clients: int = field(default_factory=lambda: _int("OTST_WS_MAX_CLIENTS", 25, 1, 1000))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
