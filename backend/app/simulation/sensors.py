"""Synthetic instrumentation: converts physical truth into *reported* measurements.

Physical truth and reported values are deliberately separate objects. Sensor faults
(bias, drift, spoofed offsets, frozen values, stale timestamps) are applied here and only
here, so the plant physics stays truthful while the telemetry may lie.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

Quality = Literal["good", "uncertain", "bad"]


@dataclass
class SensorFault:
    """Ground-truth description of a sensor fault. Applied by the scenario manager."""

    offset_target: float = 0.0  # final additive offset (engineering units)
    offset_ramp_s: float = 0.0  # seconds to ramp from 0 to offset_target (0 = step)
    drift_per_s: float = 0.0  # additive drift rate (units per second)
    freeze: Literal["none", "stuck", "stale"] = "none"  # stuck: value held, timestamps fresh
    onset_time_s: float = 0.0

    def offset_at(self, t: float) -> float:
        elapsed = max(t - self.onset_time_s, 0.0)
        frac = min(elapsed / self.offset_ramp_s, 1.0) if self.offset_ramp_s > 0 else 1.0
        return self.offset_target * frac + self.drift_per_s * elapsed


@dataclass
class Reading:
    value: float | bool | str | None
    unit: str
    source_time_s: float  # simulation time at which the source produced this value
    quality: Quality = "good"
    valid: bool = True
    tag: str = ""


@dataclass
class AnalogSensor:
    tag: str
    unit: str
    noise_sigma: float
    resolution: float
    range_lo: float
    range_hi: float
    calibration_bias: float = 0.0  # small, fixed, seeded per sensor (realistic imperfection)
    cutoff: float = 0.0  # values with |v| < cutoff report exactly 0 (flow meters)
    fault: SensorFault | None = None
    _held_value: float | None = field(default=None, repr=False)
    _held_time: float | None = field(default=None, repr=False)
    _last_value: float = field(default=0.0, repr=False)
    _last_time: float = field(default=0.0, repr=False)

    def read(self, true_value: float, t: float, rng: np.random.Generator) -> Reading:
        fault = self.fault
        if fault is not None and fault.freeze != "none" and t >= fault.onset_time_s:
            if self._held_value is None:
                self._held_value = self._last_value
                self._held_time = self._last_time
            src_time = self._held_time if fault.freeze == "stale" else t
            return Reading(self._held_value, self.unit, float(src_time or 0.0), "good", True, self.tag)
        self._held_value = None
        self._held_time = None

        value = true_value + self.calibration_bias + float(rng.normal(0.0, self.noise_sigma))
        if fault is not None and t >= fault.onset_time_s:
            value += fault.offset_at(t)
        if self.cutoff > 0 and abs(value) < self.cutoff:
            value = 0.0
        quality: Quality = "good"
        margin = 3.0 * self.noise_sigma + self.resolution
        if value < self.range_lo - margin or value > self.range_hi + margin:
            quality = "uncertain"  # transmitter saturated well beyond its calibrated range
        value = min(max(value, self.range_lo), self.range_hi)
        if self.resolution > 0:
            value = round(value / self.resolution) * self.resolution
        value = round(value, 6)
        self._last_value = value
        self._last_time = t
        return Reading(value, self.unit, t, quality, True, self.tag)

    def clear_fault(self) -> None:
        self.fault = None
        self._held_value = None
        self._held_time = None


@dataclass
class SensorSuite:
    """All field instruments of the plant. Tags follow ISA-5.1 style naming."""

    lt101: AnalogSensor  # primary level, radar (controller PV)
    lt102: AnalogSensor  # secondary level, differential pressure (interlock)
    ft101: AnalogSensor  # inlet flow, magnetic flow meter
    ft102: AnalogSensor  # outlet flow, magnetic flow meter
    pt101: AnalogSensor  # pump discharge / line pressure
    zt101: AnalogSensor  # inlet valve position feedback
    zt102: AnalogSensor  # outlet valve position feedback
    jt101: AnalogSensor  # pump motor power

    def by_tag(self) -> dict[str, AnalogSensor]:
        return {s.tag: s for s in self.all()}

    def all(self) -> list[AnalogSensor]:
        return [
            self.lt101,
            self.lt102,
            self.ft101,
            self.ft102,
            self.pt101,
            self.zt101,
            self.zt102,
            self.jt101,
        ]


def build_sensors(cfg, rng: np.random.Generator) -> SensorSuite:
    """Create the instrument set with small seeded calibration biases."""
    n = cfg.noise
    h = cfg.tank.height_m
    max_flow = max(cfg.inlet.max_flow_lps, cfg.max_outlet_flow_lps()) * 1.25

    def bias(scale: float) -> float:
        # Calibration error within +-0.5 sigma of the noise: realistic, non-zero, deterministic.
        return float(rng.uniform(-0.5, 0.5)) * scale

    return SensorSuite(
        lt101=AnalogSensor("LT-101", "m", n.level_m, 0.001, 0.0, h, bias(n.level_m)),
        lt102=AnalogSensor("LT-102", "m", n.level_m * 1.25, 0.001, 0.0, h, bias(n.level_m)),
        ft101=AnalogSensor(
            "FT-101", "L/s", n.flow_lps, 0.01, 0.0, max_flow, bias(n.flow_lps), n.flow_cutoff_lps
        ),
        ft102=AnalogSensor(
            "FT-102", "L/s", n.flow_lps, 0.01, 0.0, max_flow, bias(n.flow_lps), n.flow_cutoff_lps
        ),
        pt101=AnalogSensor("PT-101", "bar", n.pressure_bar, 0.001, 0.0, 10.0, bias(n.pressure_bar)),
        zt101=AnalogSensor("ZT-101", "%", n.position_pct, 0.1, 0.0, 100.0, 0.0),
        zt102=AnalogSensor("ZT-102", "%", n.position_pct, 0.1, 0.0, 100.0, 0.0),
        jt101=AnalogSensor("JT-101", "kW", n.power_kw, 0.01, 0.0, 500.0, 0.0),
    )


def finite(v: float | None) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)
