"""Detection primitives: process model, rule configuration, observations, alert lifecycle.

The detection engine is *blind* to the simulator: it receives only reported telemetry
(``TelemetrySample``) plus static engineering knowledge of the plant (``ProcessModel``:
tank geometry, valve and pump characteristics, instrument noise specs). It never receives
scenario identifiers, fault flags or physical ground truth.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.simulation.params import SimulationConfig, static_head_bar

Severity = Literal["low", "medium", "high", "critical"]
RuleCategory = Literal["physics", "data_quality"]


@dataclass(frozen=True)
class ProcessModel:
    """Engineering knowledge available to the detector (equivalent to P&ID + data sheets)."""

    tank_area_m2: float
    tank_height_m: float
    inlet_max_flow_lps: float
    outlet_kv: float
    back_pressure_bar: float
    pump_shutoff_bar: float
    pump_curve_k: float
    valve_travel_rate_pct_s: float
    sample_interval_s: float
    level_noise_m: float
    flow_noise_lps: float
    pressure_noise_bar: float
    max_outlet_flow_lps: float
    controller_pv_tag: str = "LT-101"

    @classmethod
    def from_config(cls, cfg: SimulationConfig) -> ProcessModel:
        return cls(
            tank_area_m2=cfg.tank.area_m2,
            tank_height_m=cfg.tank.height_m,
            inlet_max_flow_lps=cfg.inlet.max_flow_lps,
            outlet_kv=cfg.outlet.valve_kv_lps_per_sqrt_bar,
            back_pressure_bar=cfg.outlet.back_pressure_bar,
            pump_shutoff_bar=cfg.pump.shutoff_bar,
            pump_curve_k=cfg.pump.curve_k_bar_per_lps2,
            valve_travel_rate_pct_s=cfg.valve.travel_rate_pct_s,
            sample_interval_s=cfg.sample_interval_s,
            level_noise_m=cfg.noise.level_m,
            flow_noise_lps=cfg.noise.flow_lps,
            pressure_noise_bar=cfg.noise.pressure_bar,
            max_outlet_flow_lps=cfg.max_outlet_flow_lps(),
        )

    @property
    def max_fill_rate_m_s(self) -> float:
        return self.inlet_max_flow_lps / 1000.0 / self.tank_area_m2

    @property
    def max_drain_rate_m_s(self) -> float:
        return self.max_outlet_flow_lps / 1000.0 / self.tank_area_m2

    def static_bar(self, level_m: float) -> float:
        return static_head_bar(level_m)

    def pump_dp_expected(self, flow_lps: float) -> float:
        return self.pump_shutoff_bar - self.pump_curve_k * flow_lps * flow_lps

    def outlet_flow_from_pressure(self, pressure_bar: float, valve_pct: float) -> float:
        drive = pressure_bar - self.back_pressure_bar
        if drive <= 0 or valve_pct <= 0:
            return 0.0
        return self.outlet_kv * valve_pct / 100.0 * math.sqrt(drive)


class RuleConfig(BaseModel):
    """Tunable parameters of one rule. Editable at runtime through the API (audited)."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = True
    severity: Severity = "medium"
    threshold: float = Field(gt=0)
    debounce_s: float = Field(3.0, ge=0, le=600)
    clear_s: float = Field(8.0, ge=0, le=3600)
    clear_ratio: float = Field(0.6, gt=0, le=1.0, description="Hysteresis: clear below ratio*threshold")
    window_s: float = Field(10.0, gt=0, le=3600)
    units: str = ""


@dataclass
class Observation:
    """Result of evaluating one rule instance on one sample."""

    key: str  # rule instance, e.g. sensor tag
    asset_id: str
    signal: str
    statistic: float | None  # signed test statistic (None = indeterminate)
    threshold: float
    observed: float | None = None
    expected: float | None = None
    units: str = ""
    triggered: bool | None = None  # None = not evaluable (insufficient/invalid data)
    recovered: bool | None = None  # None -> derived from statistic and clear_ratio
    explanation: str = ""
    evidence: dict = field(default_factory=dict)

    @property
    def score(self) -> float:
        if self.statistic is None or self.threshold <= 0:
            return 0.0
        return abs(self.statistic) / self.threshold


@dataclass
class Alert:
    """A detection event (one raise..clear episode of one rule instance)."""

    id: str
    rule_id: str
    title: str
    category: RuleCategory
    severity: Severity
    asset_id: str
    instance_key: str
    signal: str
    units: str
    threshold: float
    first_seen_t: float  # condition onset (first anomalous sample)
    raised_t: float  # after debounce
    last_seen_t: float
    first_seen: str
    raised_at: str
    last_seen: str
    observed_value: float | None = None
    expected_value: float | None = None
    statistic: float | None = None
    peak_score: float = 0.0
    peak_observed: float | None = None
    peak_expected: float | None = None
    peak_explanation: str = ""
    expected_label: str = "Expected"
    observed_label: str = "Observed"
    status: Literal["active", "cleared"] = "active"
    cleared_t: float | None = None
    cleared_at: str | None = None
    explanation: str = ""
    evidence: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    incident_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "rule_id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "severity": self.severity,
            "asset_id": self.asset_id,
            "instance_key": self.instance_key,
            "signal": self.signal,
            "units": self.units,
            "threshold": _r(self.threshold),
            "observed_value": _r(self.observed_value),
            "expected_value": _r(self.expected_value),
            "statistic": _r(self.statistic),
            "peak_score": _r(self.peak_score),
            "peak_observed": _r(self.peak_observed),
            "peak_expected": _r(self.peak_expected),
            "peak_explanation": self.peak_explanation,
            "expected_label": self.expected_label,
            "observed_label": self.observed_label,
            "first_seen": self.first_seen,
            "raised_at": self.raised_at,
            "last_seen": self.last_seen,
            "cleared_at": self.cleared_at,
            "first_seen_t": self.first_seen_t,
            "raised_t": self.raised_t,
            "last_seen_t": self.last_seen_t,
            "cleared_t": self.cleared_t,
            "status": self.status,
            "explanation": self.explanation,
            "evidence": self.evidence,
            "metrics": self.metrics,
            "incident_id": self.incident_id,
        }


def _r(v: float | None, nd: int = 5) -> float | None:
    if v is None or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return round(float(v), nd)


# ---------------------------------------------------------------------------------------------
# Telemetry history available to rules
# ---------------------------------------------------------------------------------------------

NUMERIC_SIGNALS = {
    "lt101": "sensor.primary_level",
    "lt102": "sensor.secondary_level",
    "ft101": "flow.inlet_lps",
    "ft102": "flow.outlet_lps",
    "pt101": "pressure.line_bar",
    "zt101": "valve.inlet_position",
    "zt102": "valve.outlet_position",
    "cmd_in": "valve.inlet_command",
    "cmd_out": "valve.outlet_command",
    "kw": "pump.power_kw",
    "sp": "controller.setpoint_percent",
}
BOOL_SIGNALS = {"running": "pump.running", "pump_cmd": "pump.command"}
SENSOR_TAG_TO_KEY = {
    "LT-101": "lt101",
    "LT-102": "lt102",
    "FT-101": "ft101",
    "FT-102": "ft102",
    "PT-101": "pt101",
    "ZT-101": "zt101",
    "ZT-102": "zt102",
    "JT-101": "kw",
}
KEY_TO_SIGNAL = {**NUMERIC_SIGNALS, **BOOL_SIGNALS}


@dataclass
class Row:
    t: float
    ts: datetime
    values: dict[str, float]  # NaN when missing
    valid: dict[str, bool]  # False when stale / bad / missing (set by the freshness rule)


class History:
    """Bounded ring buffer of recent telemetry, converted to float arrays on demand."""

    def __init__(self, maxlen: int) -> None:
        self.rows: deque[Row] = deque(maxlen=maxlen)
        self._cache: dict[tuple[str, int], np.ndarray] = {}

    def append(self, row: Row) -> None:
        self.rows.append(row)
        self._cache.clear()

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def last(self) -> Row:
        return self.rows[-1]

    def series(self, key: str, n: int) -> np.ndarray:
        ck = (key, n)
        if ck not in self._cache:
            rows = list(self.rows)[-n:]
            self._cache[ck] = np.fromiter((r.values.get(key, math.nan) for r in rows), float, len(rows))
        return self._cache[ck]

    def times(self, n: int) -> np.ndarray:
        return self.series("__t", n)

    def all_valid(self, keys: list[str], n: int) -> bool:
        rows = list(self.rows)[-n:]
        return all(r.valid.get(k, False) for r in rows for k in keys)

    def n_for(self, seconds: float, interval: float) -> int:
        return round(seconds / interval) + 1


def slope(t: np.ndarray, y: np.ndarray) -> float:
    """Least-squares slope dy/dt."""
    tc = t - t.mean()
    den = float((tc * tc).sum())
    if den <= 0:
        return 0.0
    return float((tc * (y - y.mean())).sum() / den)
