"""Physics-based detection rules.

Every rule compares *reported* telemetry with what the documented process model says is
physically possible or expected. Each rule returns one ``Observation`` per instance
(e.g. per sensor). Debouncing, hysteresis, deduplication and alert lifecycle are handled
uniformly by ``DetectionEngine``. Methodology and threshold derivations: docs/DETECTION_ENGINE.md.
"""

from __future__ import annotations

import math
from typing import ClassVar

import numpy as np

from app.simulation.engine import TelemetrySample

from .base import History, Observation, ProcessModel, RuleCategory, RuleConfig, slope


class Rule:
    rule_id: ClassVar[str]
    title: ClassVar[str]
    category: ClassVar[RuleCategory] = "physics"
    description: ClassVar[str]
    methodology: ClassVar[str]
    EXPECTED_LABEL: ClassVar[str] = "Expected"
    OBSERVED_LABEL: ClassVar[str] = "Observed ({key})"

    def __init__(self, model: ProcessModel, config: RuleConfig | None = None) -> None:
        self.model = model
        self.config = config or self.default_config()
        self.dt = model.sample_interval_s

    @classmethod
    def default_config(cls) -> RuleConfig:  # pragma: no cover - overridden
        raise NotImplementedError

    def n(self, seconds: float) -> int:
        return round(seconds / self.dt) + 1

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        raise NotImplementedError

    def reset(self) -> None:
        """Clear any internal model state (called on simulation reset)."""

    def describe(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "methodology": self.methodology,
            "config": self.config.model_dump(),
        }


def _indeterminate(key: str, asset: str, signal: str, thr: float, units: str, why: str) -> Observation:
    return Observation(key, asset, signal, None, thr, units=units, triggered=None, explanation=why)


def _mean(a: np.ndarray) -> float:
    return float(np.mean(a)) if a.size else math.nan


# =============================================================================================
# DATA-001  Telemetry freshness & integrity
# =============================================================================================
class FreshnessRule(Rule):
    rule_id = "DATA-001"
    EXPECTED_LABEL = "Maximum source-timestamp age"
    OBSERVED_LABEL = "Source-timestamp age of {key}"
    title = "Telemetry Freshness / Integrity"
    category = "data_quality"
    description = (
        "Detects stale source timestamps, missing or bad-quality readings, out-of-order "
        "timestamps and gaps in the telemetry stream. Data-quality findings are kept separate "
        "from physical anomalies; physics rules treat affected signals as not evaluable."
    )
    methodology = (
        "age = sample_time - source_timestamp; stale if age > threshold. Out-of-order if a "
        "source timestamp moves backwards. Stream gap if the interval between samples exceeds "
        "3x the nominal scan interval or sequence numbers skip."
    )
    TAGS: ClassVar[dict[str, str]] = {
        "LT-101": "sensor.primary_level",
        "LT-102": "sensor.secondary_level",
        "FT-101": "flow.inlet_lps",
        "FT-102": "flow.outlet_lps",
        "PT-101": "pressure.line_bar",
        "ZT-101": "valve.inlet_position",
        "ZT-102": "valve.outlet_position",
        "JT-101": "pump.power_kw",
    }
    ASSET: ClassVar[dict[str, str]] = {
        "LT-101": "TANK-001",
        "LT-102": "TANK-001",
        "FT-101": "FT-101",
        "FT-102": "FT-102",
        "PT-101": "PT-101",
        "ZT-101": "XV-101",
        "ZT-102": "XV-102",
        "JT-101": "P-101",
    }

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="medium", threshold=2.5, debounce_s=1.0, clear_s=3.0, clear_ratio=1.0, units="s"
        )

    def __init__(self, model: ProcessModel, config: RuleConfig | None = None) -> None:
        super().__init__(model, config)
        self.reset()

    def reset(self) -> None:
        self._prev_src: dict[str, float] = {}
        self._prev_t: float | None = None
        self._prev_seq: int | None = None
        self.status: dict[str, str] = {}

    def check_signal(self, tag: str, sample: TelemetrySample) -> tuple[bool, str, float]:
        """Return (ok, reason, age_s) for one signal. Also used for row validity."""
        name = self.TAGS[tag]
        r = sample.signals.get(name)
        if r is None or r.value is None:
            return False, "missing", math.inf
        if not r.valid or r.quality == "bad":
            return False, "bad-quality", 0.0
        v = r.value
        if isinstance(v, (int, float)) and not isinstance(v, bool) and not math.isfinite(v):
            return False, "non-finite", 0.0
        age = sample.sim_time_s - r.source_time_s
        prev = self._prev_src.get(tag)
        if prev is not None and r.source_time_s < prev - 1e-9:
            return False, "out-of-order", age
        if age > self.config.threshold:
            return False, "stale", age
        return True, "ok", age

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        thr = self.config.threshold
        obs: list[Observation] = []
        for tag, name in self.TAGS.items():
            ok, reason, age = self.check_signal(tag, sample)
            r = sample.signals.get(name)
            if r is not None:
                self._prev_src[tag] = max(self._prev_src.get(tag, -math.inf), r.source_time_s)
            self.status[tag] = reason
            stat = age if math.isfinite(age) else thr * 10
            if reason in ("missing", "bad-quality", "non-finite", "out-of-order"):
                stat = max(stat, thr * 2)
            obs.append(
                Observation(
                    key=tag,
                    asset_id=self.ASSET[tag],
                    signal=name,
                    statistic=stat,
                    threshold=thr,
                    observed=age if math.isfinite(age) else None,
                    expected=0.0,
                    units="s",
                    triggered=not ok,
                    recovered=ok,
                    explanation=(
                        f"{tag} ({name}) is {reason}: source timestamp age {age:.1f} s (limit {thr:.1f} s)."
                        if reason == "stale"
                        else f"{tag} ({name}) reading is {reason}."
                    ),
                    evidence={"reason": reason, "age_s": round(age, 3) if math.isfinite(age) else None},
                )
            )
        # Stream-level integrity
        gap_limit = 3.0 * self.dt
        reason = "ok"
        gap = 0.0
        if self._prev_t is not None:
            gap = sample.sim_time_s - self._prev_t
            if gap <= 0:
                reason = "out-of-order"
            elif gap > gap_limit + 1e-9:
                reason = "gap"
            elif self._prev_seq is not None and sample.seq != self._prev_seq + 1:
                reason = "sequence-skip"
        if reason != "out-of-order":
            self._prev_t = sample.sim_time_s
            self._prev_seq = sample.seq
        bad = reason != "ok"
        obs.append(
            Observation(
                key="STREAM",
                asset_id="PLC-001",
                signal="telemetry.stream",
                # excess delay beyond the nominal scan interval (0 for a healthy stream)
                statistic=max(gap - self.dt, 0.0) if not bad else max(gap - self.dt, gap_limit * 2),
                threshold=gap_limit - self.dt,
                observed=gap,
                expected=self.dt,
                units="s",
                triggered=bad,
                recovered=not bad,
                explanation=f"Telemetry stream integrity: {reason} (interval {gap:.2f} s, "
                f"nominal {self.dt:.2f} s).",
                evidence={"reason": reason, "interval_s": round(gap, 3), "seq": sample.seq},
            )
        )
        return obs


# =============================================================================================
# PHYS-001  Mass balance
# =============================================================================================
class MassBalanceRule(Rule):
    rule_id = "PHYS-001"
    EXPECTED_LABEL = "Volume change implied by measured flows"
    OBSERVED_LABEL = "Volume change reported by {key}"
    title = "Mass Balance Violation"
    description = (
        "Compares the change of stored volume reported by each level transmitter with the "
        "integral of measured inflow minus measured outflow over a rolling window."
    )
    methodology = (
        "residual = A*(mean(L_end) - mean(L_start)) - (mean(C_end) - mean(C_start)), where C is the "
        "trapezoidal cumulative integral of (FT-101 - FT-102) and the means are taken over 3 s at "
        "each end of the window (aligns averaging of level and flow). Suspended near empty/overflow "
        "where unmeasured flows are expected, and when any input is not fresh."
    )
    END_AVG_S = 3.0

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="high",
            threshold=0.30,
            debounce_s=4.0,
            clear_s=10.0,
            clear_ratio=0.5,
            window_s=60.0,
            units="m3",
        )

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        cfg = self.config
        m = self.model
        n = self.n(cfg.window_s)
        k = max(2, round(self.END_AVG_S / self.dt))
        keys = (("LT-101", "lt101", "sensor.primary_level"), ("LT-102", "lt102", "sensor.secondary_level"))
        if len(h) < n:
            return [
                _indeterminate(tag, "TANK-001", sig, cfg.threshold, "m3", "warming up")
                for tag, _, sig in keys
            ]
        t = h.times(n)
        qin = h.series("ft101", n)
        qout = h.series("ft102", n)
        net = (qin - qout) / 1000.0
        cum = np.concatenate([[0.0], np.cumsum((net[1:] + net[:-1]) * 0.5 * np.diff(t))])
        expected = _mean(cum[-k:]) - _mean(cum[:k])
        flows_ok = h.all_valid(["ft101", "ft102"], n) and np.isfinite(cum).all()
        obs: list[Observation] = []
        residuals: dict[str, float | None] = {}
        for tag, key, sig in keys:
            lvl = h.series(key, n)
            if not flows_ok or not h.all_valid([key], n) or not np.isfinite(lvl).all():
                obs.append(_indeterminate(tag, "TANK-001", sig, cfg.threshold, "m3", "inputs not fresh"))
                residuals[tag] = None
                continue
            if lvl.max() > 0.98 * m.tank_height_m or lvl.min() < 0.02 * m.tank_height_m:
                obs.append(
                    _indeterminate(tag, "TANK-001", sig, cfg.threshold, "m3", "near overflow/empty boundary")
                )
                residuals[tag] = None
                continue
            observed = m.tank_area_m2 * (_mean(lvl[-k:]) - _mean(lvl[:k]))
            res = observed - expected
            residuals[tag] = res
            if tag == "LT-101":
                analytics["predicted_level_m"] = _mean(lvl[:k]) + (cum[-1] - _mean(cum[:k])) / m.tank_area_m2
            obs.append(
                Observation(
                    key=tag,
                    asset_id="TANK-001",
                    signal=sig,
                    statistic=res,
                    threshold=cfg.threshold,
                    observed=observed,
                    expected=expected,
                    units="m3",
                    triggered=abs(res) > cfg.threshold,
                    explanation=(
                        f"Volume change reported by {tag} over {cfg.window_s:.0f} s is {observed:+.2f} m3, "
                        f"but measured inflow minus outflow accounts for {expected:+.2f} m3 "
                        f"(residual {res:+.2f} m3, limit +/-{cfg.threshold:.2f} m3)."
                    ),
                    evidence={
                        "observed_dV_m3": round(observed, 4),
                        "expected_dV_m3": round(expected, 4),
                        "residual_m3": round(res, 4),
                        "window_s": cfg.window_s,
                        "level_start_m": round(_mean(lvl[:k]), 4),
                        "level_end_m": round(_mean(lvl[-k:]), 4),
                        "mean_inflow_lps": round(_mean(qin), 3),
                        "mean_outflow_lps": round(_mean(qout), 3),
                    },
                )
            )
        analytics["mass_residual_m3"] = {
            k_: (None if v is None else round(v, 4)) for k_, v in residuals.items()
        }
        return obs


# =============================================================================================
# PHYS-002  Redundant sensor disagreement
# =============================================================================================
class SensorDisagreementRule(Rule):
    rule_id = "PHYS-002"
    EXPECTED_LABEL = "Redundant LT-102 level"
    OBSERVED_LABEL = "Primary LT-101 level"
    title = "Redundant Sensor Disagreement"
    description = (
        "Compares the two independent level transmitters LT-101 (radar) and LT-102 "
        "(differential pressure). Sustained disagreement beyond instrument tolerance is flagged."
    )
    methodology = (
        "d = mean_3s(LT-101) - mean_3s(LT-102). Raised when |d| exceeds the threshold for the "
        "debounce period; cleared below clear_ratio*threshold. The 10 s slope of d is recorded "
        "as evidence of onset abruptness (used for classification, not for detection)."
    )

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="high", threshold=0.10, debounce_s=5.0, clear_s=10.0, clear_ratio=0.6, units="m"
        )

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        cfg = self.config
        k = max(2, round(3.0 / self.dt))
        n_rate = self.n(10.0)
        key = "LT-101/LT-102"
        if len(h) < k or not h.all_valid(["lt101", "lt102"], k):
            analytics["disagreement_m"] = None
            return [_indeterminate(key, "TANK-001", "sensor.*_level", cfg.threshold, "m", "inputs not fresh")]
        a = _mean(h.series("lt101", k))
        b = _mean(h.series("lt102", k))
        d = a - b
        rate = 0.0
        if len(h) >= n_rate:
            dd = h.series("lt101", n_rate) - h.series("lt102", n_rate)
            if np.isfinite(dd).all():
                rate = slope(h.times(n_rate), dd)
        analytics["disagreement_m"] = round(d, 5)
        return [
            Observation(
                key=key,
                asset_id="TANK-001",
                signal="sensor.primary_level|sensor.secondary_level",
                statistic=d,
                threshold=cfg.threshold,
                observed=a,
                expected=b,
                units="m",
                triggered=abs(d) > cfg.threshold,
                explanation=(
                    f"LT-101 reports {a:.3f} m while redundant LT-102 reports {b:.3f} m "
                    f"(difference {d:+.3f} m, tolerance +/-{cfg.threshold:.3f} m)."
                ),
                evidence={
                    "lt101_m": round(a, 4),
                    "lt102_m": round(b, 4),
                    "difference_m": round(d, 4),
                    "deviation_rate_m_s": round(rate, 5),
                },
            )
        ]


# =============================================================================================
# PHYS-003  Physically impossible rate of change
# =============================================================================================
class RateOfChangeRule(Rule):
    rule_id = "PHYS-003"
    EXPECTED_LABEL = "Physically possible rate limit"
    OBSERVED_LABEL = "Rate of change reported by {key}"
    title = "Impossible Rate of Change"
    description = (
        "Flags level changes faster than the plant can physically produce, given the maximum "
        "inlet capacity, maximum pump/valve outflow and the tank cross-section."
    )
    methodology = (
        "rate = least-squares slope of the level over the window. Fill limit = Qin_max/A, drain "
        "limit = Qout_max/A. Threshold = 1.25 x limit + noise margin (threshold field, m/s) to "
        "keep the false-alarm probability negligible for the specified instrument noise."
    )

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="medium",
            threshold=0.005,
            debounce_s=1.0,
            clear_s=10.0,
            clear_ratio=0.8,
            window_s=5.0,
            units="m/s",
        )

    def limits(self) -> tuple[float, float]:
        margin = self.config.threshold
        return 1.25 * self.model.max_fill_rate_m_s + margin, 1.25 * self.model.max_drain_rate_m_s + margin

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        n = self.n(self.config.window_s)
        up, down = self.limits()
        obs: list[Observation] = []
        rates: dict[str, float | None] = {}
        for tag, key, sig in (
            ("LT-101", "lt101", "sensor.primary_level"),
            ("LT-102", "lt102", "sensor.secondary_level"),
        ):
            if len(h) < n or not h.all_valid([key], n):
                obs.append(_indeterminate(tag, "TANK-001", sig, up, "m/s", "inputs not fresh"))
                rates[tag] = None
                continue
            r = slope(h.times(n), h.series(key, n))
            rates[tag] = round(r, 6)
            lim = up if r >= 0 else down
            obs.append(
                Observation(
                    key=tag,
                    asset_id="TANK-001",
                    signal=sig,
                    statistic=r,
                    threshold=lim,
                    observed=r,
                    expected=(self.model.max_fill_rate_m_s if r >= 0 else -self.model.max_drain_rate_m_s),
                    units="m/s",
                    triggered=abs(r) > lim,
                    explanation=(
                        f"{tag} changes at {r * 1000:+.1f} mm/s; the plant can physically fill at most "
                        f"{self.model.max_fill_rate_m_s * 1000:.1f} mm/s and drain at most "
                        f"{self.model.max_drain_rate_m_s * 1000:.1f} mm/s (alarm limit {lim * 1000:.1f} mm/s)."
                    ),
                    evidence={
                        "rate_mm_s": round(r * 1000, 3),
                        "fill_limit_mm_s": round(self.model.max_fill_rate_m_s * 1000, 3),
                        "drain_limit_mm_s": round(self.model.max_drain_rate_m_s * 1000, 3),
                        "alarm_limit_mm_s": round(lim * 1000, 3),
                    },
                )
            )
        analytics["level_rate_m_s"] = rates
        return obs


# =============================================================================================
# PHYS-004  Command / actuator mismatch
# =============================================================================================
class ActuatorMismatchRule(Rule):
    rule_id = "PHYS-004"
    EXPECTED_LABEL = "Position of a healthy actuator"
    OBSERVED_LABEL = "Feedback reported for {key}"
    title = "Command / Actuator Mismatch"
    description = (
        "Compares valve position feedback with the position a healthy, rate-limited actuator would "
        "have reached given the commands issued, and pump run feedback with the pump command."
    )
    methodology = (
        "An envelope of healthy actuator positions is propagated from the last trusted feedback "
        "through two rate limiters (rated stroking speed -/+ 30 %), so legitimate travel time - "
        "including a somewhat slower or faster actuator - is never flagged. deviation = distance of "
        "the feedback from the envelope; raised above the threshold (%) for the debounce period. "
        "Pump: command and run feedback disagree for longer than the start/stop allowance (10 s)."
    )
    VALVES: ClassVar[tuple[tuple[str, str, str, str], ...]] = (
        ("XV-101", "cmd_in", "zt101", "valve.inlet_position"),
        ("XV-102", "cmd_out", "zt102", "valve.outlet_position"),
    )
    PUMP_ALLOWANCE_S = 10.0
    SPEED_TOLERANCE = 0.30  # accepted actuator speed uncertainty (fraction of rated speed)
    IN_BAND_MARGIN_PCT = 1.5  # feedback noise margin when testing envelope membership

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="high", threshold=5.0, debounce_s=3.0, clear_s=5.0, clear_ratio=0.5, units="%"
        )

    def __init__(self, model: ProcessModel, config: RuleConfig | None = None) -> None:
        super().__init__(model, config)
        self.reset()

    def reset(self) -> None:
        self._envelope: dict[str, tuple[float, float]] = {}  # asset -> (slow, fast) expected positions
        self._pump_mismatch_since: float | None = None

    @staticmethod
    def _approach(cur: float, target: float, step: float) -> float:
        d = target - cur
        return target if abs(d) <= step else cur + math.copysign(step, d)

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        cfg = self.config
        row = h.last
        obs: list[Observation] = []
        step = self.model.valve_travel_rate_pct_s * self.dt
        slow_step, fast_step = step * (1 - self.SPEED_TOLERANCE), step * (1 + self.SPEED_TOLERANCE)
        expected_out: dict[str, float] = {}
        for asset, cmd_key, fb_key, sig in self.VALVES:
            cmd = row.values.get(cmd_key, math.nan)
            fb = row.values.get(fb_key, math.nan)
            if not row.valid.get(fb_key, False) or not math.isfinite(cmd) or not math.isfinite(fb):
                obs.append(_indeterminate(asset, asset, sig, cfg.threshold, "%", "feedback not fresh"))
                self._envelope.pop(asset, None)
                continue
            slow, fast = self._envelope.get(asset, (fb, fb))
            slow = self._approach(slow, cmd, slow_step)
            fast = self._approach(fast, cmd, fast_step)
            lo, hi = min(slow, fast), max(slow, fast)
            m = self.IN_BAND_MARGIN_PCT
            if lo - m <= fb <= hi + m:
                dev = 0.0
                exp = fb
                slow = fast = fb  # healthy: re-anchor the envelope on trusted feedback
            else:
                exp = hi if fb > hi else lo  # nearest healthy position
                dev = fb - exp
            self._envelope[asset] = (slow, fast)
            expected_out[asset] = round(exp, 3)
            obs.append(
                Observation(
                    key=asset,
                    asset_id=asset,
                    signal=sig,
                    statistic=dev,
                    threshold=cfg.threshold,
                    observed=fb,
                    expected=exp,
                    units="%",
                    triggered=abs(dev) > cfg.threshold,
                    explanation=(
                        f"{asset} is commanded to {cmd:.1f} %; a healthy actuator stroking at "
                        f"{self.model.valve_travel_rate_pct_s:.0f} %/s would be at {exp:.1f} %, but position "
                        f"feedback reports {fb:.1f} % (deviation {dev:+.1f} %, limit +/-{cfg.threshold:.1f} %)."
                    ),
                    evidence={
                        "command_pct": round(cmd, 2),
                        "expected_position_pct": round(exp, 2),
                        "feedback_pct": round(fb, 2),
                        "deviation_pct": round(dev, 2),
                    },
                )
            )
        analytics["valve_expected_pct"] = expected_out

        # Pump motor: command vs. run feedback
        cmd_on = row.values.get("pump_cmd", math.nan)
        running = row.values.get("running", math.nan)
        if math.isfinite(cmd_on) and math.isfinite(running):
            mismatch = bool(cmd_on) != bool(running)
            if mismatch and self._pump_mismatch_since is None:
                self._pump_mismatch_since = row.t
            if not mismatch:
                self._pump_mismatch_since = None
            dur = 0.0 if self._pump_mismatch_since is None else row.t - self._pump_mismatch_since
            stat = dur / self.PUMP_ALLOWANCE_S * cfg.threshold
            obs.append(
                Observation(
                    key="P-101",
                    asset_id="P-101",
                    signal="pump.command|pump.running",
                    statistic=stat,
                    threshold=cfg.threshold,
                    observed=float(running),
                    expected=float(cmd_on),
                    units="state",
                    triggered=dur > self.PUMP_ALLOWANCE_S,
                    recovered=not mismatch,
                    explanation=(
                        f"Pump P-101 is commanded {'ON' if cmd_on else 'OFF'} but run feedback has reported "
                        f"{'RUNNING' if running else 'STOPPED'} for {dur:.0f} s "
                        f"(allowance {self.PUMP_ALLOWANCE_S:.0f} s)."
                    ),
                    evidence={
                        "command_on": bool(cmd_on),
                        "running": bool(running),
                        "mismatch_s": round(dur, 1),
                    },
                )
            )
        return obs


# =============================================================================================
# PHYS-005  Pump / process inconsistency
# =============================================================================================
class PumpConsistencyRule(Rule):
    rule_id = "PHYS-005"
    EXPECTED_LABEL = "Pump-curve differential pressure"
    OBSERVED_LABEL = "Measured differential pressure"
    title = "Pump / Process Inconsistency"
    description = (
        "Checks that the hydraulic response matches the pump's reported state: a running pump must "
        "develop the differential pressure given by its characteristic curve at the measured flow; a "
        "stopped pump cannot produce a pressure rise or powered outflow."
    )
    methodology = (
        "dP_meas = PT-101 - rho*g*h (h = mean of fresh level transmitters). Running: statistic = "
        "(P0 - k*Q^2) - dP_meas. Stopped: statistic = max(dP_meas, Q_out / 2 L/s * threshold). "
        "Evaluated only after a start/stop settling allowance and above the dry-running level."
    )
    GRACE_S = 8.0

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="high", threshold=0.40, debounce_s=4.0, clear_s=8.0, clear_ratio=0.5, units="bar"
        )

    def __init__(self, model: ProcessModel, config: RuleConfig | None = None) -> None:
        super().__init__(model, config)
        self.reset()

    def reset(self) -> None:
        self._state: bool | None = None
        self._since: float = 0.0

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        cfg = self.config
        m = self.model
        row = h.last
        key, asset, sig = "P-101", "P-101", "pump.running|pressure.line_bar|flow.outlet_lps"
        running_v = row.values.get("running", math.nan)
        if not math.isfinite(running_v):
            return [_indeterminate(key, asset, sig, cfg.threshold, "bar", "pump state unavailable")]
        running = bool(running_v)
        if self._state is None or running != self._state:
            self._state = running
            self._since = row.t
        k = max(2, round(3.0 / self.dt))
        if len(h) < k or not h.all_valid(["pt101", "ft102"], k):
            return [_indeterminate(key, asset, sig, cfg.threshold, "bar", "inputs not fresh")]
        levels = [_mean(h.series(x, k)) for x in ("lt101", "lt102") if h.all_valid([x], k)]
        if not levels:
            return [_indeterminate(key, asset, sig, cfg.threshold, "bar", "no fresh level")]
        level = float(np.mean(levels))
        if level < 0.02 * m.tank_height_m or row.t - self._since < self.GRACE_S:
            return [_indeterminate(key, asset, sig, cfg.threshold, "bar", "settling / dry-run boundary")]
        p = _mean(h.series("pt101", k))
        q = _mean(h.series("ft102", k))
        dp_meas = p - m.static_bar(level)
        if running:
            dp_exp = m.pump_dp_expected(q)
            stat = dp_exp - dp_meas
            analytics["pump_dp_deficit_bar"] = round(stat, 4)
            text = (
                f"Pump P-101 reports RUNNING at {q:.1f} L/s; its characteristic curve requires a "
                f"differential pressure of {dp_exp:.2f} bar but only {dp_meas:.2f} bar is measured "
                f"(deficit {stat:+.2f} bar, limit {cfg.threshold:.2f} bar)."
            )
            observed, expected = dp_meas, dp_exp
        else:
            flow_equiv = q / 2.0 * cfg.threshold
            stat = max(dp_meas, flow_equiv)
            analytics["pump_dp_deficit_bar"] = None
            text = (
                f"Pump P-101 reports STOPPED, yet {dp_meas:.2f} bar pressure rise above static head and "
                f"{q:.1f} L/s outflow are measured; with the pump stopped the outlet cannot flow "
                f"(back pressure {m.back_pressure_bar:.2f} bar exceeds static head)."
            )
            observed, expected = dp_meas, 0.0
        return [
            Observation(
                key=key,
                asset_id=asset,
                signal=sig,
                statistic=stat,
                threshold=cfg.threshold,
                observed=observed,
                expected=expected,
                units="bar",
                triggered=abs(stat) > cfg.threshold,
                explanation=text,
                evidence={
                    "running": running,
                    "line_pressure_bar": round(p, 4),
                    "static_head_bar": round(m.static_bar(level), 4),
                    "dp_measured_bar": round(dp_meas, 4),
                    "dp_expected_bar": round(expected, 4),
                    "outlet_flow_lps": round(q, 3),
                    "power_kw": round(row.values.get("kw", math.nan), 3),
                },
            )
        ]


# =============================================================================================
# PHYS-006  Frozen sensor
# =============================================================================================
class FrozenSensorRule(Rule):
    rule_id = "PHYS-006"
    EXPECTED_LABEL = "Independently predicted change"
    OBSERVED_LABEL = "Spread of {key} reported value"
    title = "Frozen Sensor"
    description = (
        "Detects a transmitter whose value does not change at all while an independent prediction "
        "says the measured quantity should have changed. A flat value in a genuinely steady process "
        "is not flagged."
    )
    methodology = (
        "flat = (max - min) of the reported value over the window <= half a resolution step. "
        "Independent change = largest of: redundant-sensor change, flow-integrated level change, "
        "valve/hydraulic-model predicted flow change, or pump-curve predicted pressure change, "
        "expressed in multiples of the instrument noise sigma. Raised when flat AND change >= threshold."
    )
    RESOLUTION: ClassVar[dict[str, float]] = {
        "lt101": 0.001,
        "lt102": 0.001,
        "ft101": 0.01,
        "ft102": 0.01,
        "pt101": 0.001,
    }

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="medium",
            threshold=5.0,
            debounce_s=2.0,
            clear_s=4.0,
            clear_ratio=1.0,
            window_s=20.0,
            units="sigma",
        )

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        cfg = self.config
        m = self.model
        n = self.n(cfg.window_s)
        specs = (
            ("LT-101", "lt101", "sensor.primary_level", "TANK-001", m.level_noise_m, "m"),
            ("LT-102", "lt102", "sensor.secondary_level", "TANK-001", m.level_noise_m, "m"),
            ("FT-101", "ft101", "flow.inlet_lps", "FT-101", m.flow_noise_lps, "L/s"),
            ("FT-102", "ft102", "flow.outlet_lps", "FT-102", m.flow_noise_lps, "L/s"),
            ("PT-101", "pt101", "pressure.line_bar", "PT-101", m.pressure_noise_bar, "bar"),
        )
        if len(h) < n:
            return [_indeterminate(s[0], s[3], s[2], cfg.threshold, "sigma", "warming up") for s in specs]
        t = h.times(n)
        obs: list[Observation] = []
        for tag, key, sig, asset, sigma, unit in specs:
            if not h.all_valid([key], n):
                obs.append(
                    _indeterminate(tag, asset, sig, cfg.threshold, "sigma", "not fresh (see DATA-001)")
                )
                continue
            y = h.series(key, n)
            spread = float(np.nanmax(y) - np.nanmin(y))
            flat = spread <= self.RESOLUTION[key] / 2
            predicted, basis = self._predicted_change(h, key, n, t, y)
            if predicted is None:
                obs.append(
                    _indeterminate(tag, asset, sig, cfg.threshold, "sigma", "no independent reference")
                )
                continue
            z = predicted / max(sigma, 1e-9)
            obs.append(
                Observation(
                    key=tag,
                    asset_id=asset,
                    signal=sig,
                    statistic=z if flat else 0.0,
                    threshold=cfg.threshold,
                    observed=spread,
                    expected=predicted,
                    units="sigma",
                    triggered=flat and z >= cfg.threshold,
                    recovered=not flat,
                    explanation=(
                        f"{tag} has reported exactly {y[-1]:.3f} {unit} for {cfg.window_s:.0f} s, while "
                        f"{basis} predicts a change of {predicted:.3f} {unit} "
                        f"({z:.1f} sigma; limit {cfg.threshold:.1f} sigma)."
                    ),
                    evidence={
                        "flat_value": round(float(y[-1]), 4),
                        "spread": round(spread, 5),
                        "predicted_change": round(predicted, 4),
                        "basis": basis,
                        "noise_sigma": sigma,
                    },
                )
            )
        return obs

    def _predicted_change(
        self, h: History, key: str, n: int, t: np.ndarray, y: np.ndarray
    ) -> tuple[float | None, str]:
        m = self.model
        k = max(2, round(3.0 / self.dt))
        if key in ("lt101", "lt102"):
            other = "lt102" if key == "lt101" else "lt101"
            cands: list[tuple[float, str]] = []
            if h.all_valid([other], n):
                o = h.series(other, n)
                cands.append(
                    (abs(_mean(o[-k:]) - _mean(o[:k])), f"redundant {other.upper()[:2]}-{other[2:]}")
                )
            if h.all_valid(["ft101", "ft102"], n):
                net = (h.series("ft101", n) - h.series("ft102", n)) / 1000.0
                integ = float(np.sum((net[1:] + net[:-1]) * 0.5 * np.diff(t))) / m.tank_area_m2
                cands.append((abs(integ), "flow-integrated mass balance"))
            if not cands:
                return None, ""
            return max(cands)
        if key == "ft101":
            if not h.all_valid(["zt101"], n):
                return None, ""
            q_exp = m.inlet_max_flow_lps * h.series("zt101", n) / 100.0
            pred = max(float(q_exp.max() - q_exp.min()), abs(float(y[-1]) - _mean(q_exp)))
            return pred, "inlet valve position (ZT-101) x valve capacity"
        if key == "ft102":
            if not h.all_valid(["zt102", "pt101"], n):
                return None, ""
            p = h.series("pt101", n)
            x = h.series("zt102", n)
            q_exp = np.array([m.outlet_flow_from_pressure(pi, xi) for pi, xi in zip(p, x, strict=True)])
            pred = max(float(q_exp.max() - q_exp.min()), abs(float(y[-1]) - _mean(q_exp)))
            return pred, "outlet hydraulic model (PT-101, ZT-102)"
        if key == "pt101":
            if not h.all_valid(["ft102", "lt102"], n):
                return None, ""
            run = h.series("running", n)
            q = h.series("ft102", n)
            lvl = h.series("lt102", n)
            p_exp = np.array(
                [
                    m.static_bar(li) + (m.pump_dp_expected(qi) if ri > 0.5 else 0.0)
                    for li, qi, ri in zip(lvl, q, run, strict=True)
                ]
            )
            pred = max(float(p_exp.max() - p_exp.min()), abs(float(y[-1]) - _mean(p_exp)))
            return pred, "pump curve and static head (FT-102, LT-102)"
        return None, ""


# =============================================================================================
# PHYS-007  Pressure / flow inconsistency
# =============================================================================================
class PressureFlowRule(Rule):
    rule_id = "PHYS-007"
    EXPECTED_LABEL = "Flow required by the valve equation"
    OBSERVED_LABEL = "Flow measured by FT-102"
    title = "Pressure / Flow Inconsistency"
    description = (
        "Checks the outlet flow measured by FT-102 against the flow the outlet valve must pass at "
        "the measured line pressure and valve opening (simplified valve equation of the twin)."
    )
    methodology = (
        "Q_pred = Kv * x_ZT-102 * sqrt(PT-101 - P_back). statistic = Q_meas - Q_pred over 3 s means; "
        "raised when |statistic| > max(threshold, 15 % of Q_pred). Evaluated only with the pump "
        "running and settled, the valve > 5 % open and a meaningful pressure drop."
    )

    @classmethod
    def default_config(cls) -> RuleConfig:
        return RuleConfig(
            severity="medium", threshold=3.0, debounce_s=5.0, clear_s=8.0, clear_ratio=0.6, units="L/s"
        )

    def __init__(self, model: ProcessModel, config: RuleConfig | None = None) -> None:
        super().__init__(model, config)
        self.reset()

    def reset(self) -> None:
        self._run_since: float | None = None

    def evaluate(self, h: History, sample: TelemetrySample, analytics: dict) -> list[Observation]:
        cfg = self.config
        m = self.model
        key, asset, sig = "FT-102/PT-101", "OUTLET-LINE", "flow.outlet_lps|pressure.line_bar"
        row = h.last
        running = row.values.get("running", 0.0) > 0.5
        if running and self._run_since is None:
            self._run_since = row.t
        if not running:
            self._run_since = None
        k = max(2, round(3.0 / self.dt))
        if len(h) < k or not h.all_valid(["pt101", "ft102", "zt102"], k):
            analytics["outlet_flow_expected_lps"] = None
            return [_indeterminate(key, asset, sig, cfg.threshold, "L/s", "inputs not fresh")]
        p = _mean(h.series("pt101", k))
        q = _mean(h.series("ft102", k))
        x = _mean(h.series("zt102", k))
        q_pred = m.outlet_flow_from_pressure(p, x)
        analytics["outlet_flow_expected_lps"] = round(q_pred, 3)
        settled = self._run_since is not None and row.t - self._run_since >= 8.0
        if not settled or x < 5.0 or p - m.back_pressure_bar < 0.05:
            return [
                _indeterminate(key, asset, sig, cfg.threshold, "L/s", "not in evaluable operating region")
            ]
        limit = max(cfg.threshold, 0.15 * q_pred)
        dev = q - q_pred
        return [
            Observation(
                key=key,
                asset_id=asset,
                signal=sig,
                statistic=dev * cfg.threshold / limit,  # normalised so |stat| > threshold <=> |dev| > limit
                threshold=cfg.threshold,
                observed=q,
                expected=q_pred,
                units="L/s",
                triggered=abs(dev) > limit,
                explanation=(
                    f"At {p:.2f} bar line pressure and {x:.1f} % outlet valve opening the outlet must pass "
                    f"about {q_pred:.1f} L/s, but FT-102 measures {q:.1f} L/s (deviation {dev:+.1f} L/s, "
                    f"limit +/-{limit:.1f} L/s)."
                ),
                evidence={
                    "line_pressure_bar": round(p, 4),
                    "valve_position_pct": round(x, 2),
                    "flow_measured_lps": round(q, 3),
                    "flow_expected_lps": round(q_pred, 3),
                    "deviation_lps": round(dev, 3),
                    "limit_lps": round(limit, 3),
                },
            )
        ]


ALL_RULES: tuple[type[Rule], ...] = (
    MassBalanceRule,
    SensorDisagreementRule,
    RateOfChangeRule,
    ActuatorMismatchRule,
    PumpConsistencyRule,
    FrozenSensorRule,
    PressureFlowRule,
    FreshnessRule,
)
