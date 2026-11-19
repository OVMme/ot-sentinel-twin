"""Shared dependencies: runtime access, write protection, rate limiting, analyst identity."""

from __future__ import annotations

import hmac
import re
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from app.core.config import Settings
from app.repositories.sql import Repository
from app.services.runtime import SimulationRuntime

_ANALYST_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")


class ApiError(HTTPException):
    def __init__(self, status: int, code: str, message: str, details: object | None = None) -> None:
        super().__init__(status_code=status, detail={"code": code, "message": message, "details": details})


def get_runtime(request: Request) -> SimulationRuntime:
    return request.app.state.runtime


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


class RateLimiter:
    """Sliding-window limiter for state-changing requests (per client address)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        now = time.monotonic()
        q = self._hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        if len(self._hits) > 10_000:  # bound memory
            self._hits.clear()
        return True


rate_limiter = RateLimiter()


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def require_write(request: Request, settings: Settings = Depends(get_app_settings)) -> None:
    if settings.read_only:
        raise ApiError(
            403, "read_only", "This deployment is read-only; state-changing operations are disabled."
        )
    if settings.api_token:
        supplied = request.headers.get("x-api-key", "")
        if not hmac.compare_digest(supplied.encode(), settings.api_token.encode()):
            raise ApiError(401, "unauthorized", "A valid X-API-Key header is required for this operation.")
    client = request.client.host if request.client else "unknown"
    if not rate_limiter.check(client, settings.rate_limit_per_minute):
        raise ApiError(429, "rate_limited", "Too many state-changing requests; try again shortly.")


def analyst(request: Request) -> str:
    name = request.headers.get("x-analyst", "").strip()
    return name if name and _ANALYST_RE.match(name) else "local-analyst"
