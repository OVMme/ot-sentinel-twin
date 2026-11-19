"""Typed request/response schemas for the public API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RUN_ID_PATTERN = r"^run-\d{8}-\d{6}-[0-9a-f]{4}$"
INCIDENT_ID_PATTERN = r"^INC-\d{4,8}$"
SCENARIO_ID_PATTERN = r"^[a-z0-9-]{1,40}$"
RULE_ID_PATTERN = r"^(PHYS|DATA)-\d{3}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    simulation: str
    run_id: str
    database: Literal["ok", "error"]
    synthetic_data_only: bool = True


class Page(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


class SpeedRequest(_Strict):
    speed: float = Field(ge=0.25, le=50)


class ModeRequest(_Strict):
    mode: Literal["auto", "manual"]


class OperatorRequest(_Strict):
    inlet_valve_pct: float | None = Field(None, ge=0, le=100)
    outlet_valve_pct: float | None = Field(None, ge=0, le=100)
    pump_on: bool | None = None
    setpoint_pct: float | None = Field(None, ge=5, le=95)


class ResetRequest(_Strict):
    seed: int | None = Field(None, ge=0, le=2**31 - 1)


class ScenarioStartRequest(_Strict):
    params: dict[str, float | str] = Field(default_factory=dict, max_length=10)


class RuleUpdateRequest(_Strict):
    enabled: bool | None = None
    severity: Literal["low", "medium", "high", "critical"] | None = None
    threshold: float | None = Field(None, gt=0, le=1e6)
    debounce_s: float | None = Field(None, ge=0, le=600)
    clear_s: float | None = Field(None, ge=0, le=3600)
    clear_ratio: float | None = Field(None, gt=0, le=1)
    window_s: float | None = Field(None, gt=0, le=3600)


class IncidentStatusRequest(_Strict):
    status: Literal["open", "acknowledged", "investigating", "reviewed", "closed"]


class NoteRequest(_Strict):
    text: str = Field(min_length=1, max_length=2000)


class EvaluationRequest(_Strict):
    seeds: list[int] = Field(default_factory=lambda: [1337], min_length=1, max_length=3)
