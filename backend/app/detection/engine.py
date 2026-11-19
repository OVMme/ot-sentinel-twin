"""Detection engine: runs all rules on each telemetry sample and manages alert lifecycle.

Lifecycle per rule instance (rule_id, key):

    idle --(condition true)--> pending --(true for debounce_s)--> ACTIVE (alert raised)
    pending --(condition false)--> idle
    ACTIVE --(recovered for clear_s)--> cleared (alert closed; a new episode needs a new debounce)
    indeterminate observations (invalid / insufficient data) freeze the state machine.

One alert exists per active episode of a rule instance, which deduplicates repeated
threshold crossings and prevents alert storms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from app.simulation.engine import TelemetrySample

from .base import BOOL_SIGNALS, NUMERIC_SIGNALS, Alert, History, Observation, ProcessModel, Row, RuleConfig
from .rules import ALL_RULES, FreshnessRule, Rule

ChangeType = Literal["raised", "updated", "cleared"]
MAX_EVIDENCE = 24
EVIDENCE_EVERY_S = 10.0

# signal key -> tag used by the freshness rule
_VALIDITY_TAG = {
    "lt101": "LT-101",
    "lt102": "LT-102",
    "ft101": "FT-101",
    "ft102": "FT-102",
    "pt101": "PT-101",
    "zt101": "ZT-101",
    "zt102": "ZT-102",
    "kw": "JT-101",
}


@dataclass
class _Tracker:
    state: Literal["idle", "pending", "active"] = "idle"
    pending_since: float | None = None
    pending_obs: Observation | None = None
    pending_ts: str | None = None
    recover_since: float | None = None
    alert: Alert | None = None
    last_obs: Observation | None = None
    last_evidence_t: float = -math.inf


@dataclass
class AlertChange:
    change: ChangeType
    alert: Alert


@dataclass
class DetectionResult:
    changes: list[AlertChange] = field(default_factory=list)
    analytics: dict = field(default_factory=dict)
    validity: dict[str, bool] = field(default_factory=dict)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class DetectionEngine:
    def __init__(
        self,
        model: ProcessModel,
        configs: dict[str, RuleConfig] | None = None,
        id_prefix: str = "DET",
        id_start: int = 0,
    ) -> None:
        self.model = model
        configs = configs or {}
        self.rules: list[Rule] = [cls(model, configs.get(cls.rule_id)) for cls in ALL_RULES]
        self.freshness: FreshnessRule = next(r for r in self.rules if isinstance(r, FreshnessRule))
        max_window = max(r.config.window_s for r in self.rules) + 15.0
        self.history = History(maxlen=round(max_window / model.sample_interval_s) + 10)
        self._trackers: dict[tuple[str, str], _Tracker] = {}
        self._id_prefix = id_prefix
        self._counter = id_start
        self.samples_processed = 0
        self.last_analytics: dict = {}
        # Monotonic evaluation clock: debounce/clear timers must advance even if a (faulty) stream
        # delivers timestamps that go backwards.
        self._clock = -math.inf

    # ------------------------------------------------------------------ public API
    def rule(self, rule_id: str) -> Rule:
        for r in self.rules:
            if r.rule_id == rule_id:
                return r
        raise KeyError(rule_id)

    def update_config(self, rule_id: str, **changes: object) -> RuleConfig:
        r = self.rule(rule_id)
        new = r.config.model_copy(update=changes)
        r.config = RuleConfig.model_validate(new.model_dump())
        return r.config

    def active_alerts(self) -> list[Alert]:
        return [t.alert for t in self._trackers.values() if t.state == "active" and t.alert is not None]

    def reset(self) -> None:
        for r in self.rules:
            r.reset()
        self.history = History(maxlen=self.history.rows.maxlen or 400)
        self._trackers.clear()
        self.samples_processed = 0
        self._clock = -math.inf

    def status(self) -> list[dict]:
        out = []
        for r in self.rules:
            instances = []
            for (rid, key), tr in sorted(self._trackers.items()):
                if rid != r.rule_id:
                    continue
                o = tr.last_obs
                instances.append(
                    {
                        "key": key,
                        "state": tr.state,
                        "statistic": None if o is None or o.statistic is None else round(o.statistic, 5),
                        "threshold": None if o is None else round(o.threshold, 5),
                        "score": None if o is None else round(o.score, 4),
                        "evaluable": o is not None and o.triggered is not None,
                        "alert_id": tr.alert.id if tr.alert and tr.state == "active" else None,
                    }
                )
            out.append({**r.describe(), "instances": instances})
        return out

    # ------------------------------------------------------------------ main loop
    def process(self, sample: TelemetrySample) -> DetectionResult:
        result = DetectionResult()
        row = self._to_row(sample)
        result.validity = dict(row.valid)
        self.history.append(row)
        self.samples_processed += 1
        analytics: dict = {}
        scores: dict[str, float] = {}
        ts = _iso(sample.timestamp)
        if sample.sim_time_s > self._clock:
            self._clock = sample.sim_time_s
        else:
            self._clock += self.model.sample_interval_s
        clock = self._clock
        for rule in self.rules:
            if not rule.config.enabled:
                continue
            for obs in rule.evaluate(self.history, sample, analytics):
                scores[rule.rule_id] = max(scores.get(rule.rule_id, 0.0), obs.score)
                change = self._advance(rule, obs, clock, ts)
                if change is not None:
                    result.changes.append(change)
        analytics["scores"] = {k: round(v, 4) for k, v in scores.items()}
        analytics["anomaly_score"] = round(max(scores.values(), default=0.0), 4)
        analytics["active_alerts"] = len(self.active_alerts())
        self.last_analytics = analytics
        result.analytics = analytics
        return result

    def _to_row(self, sample: TelemetrySample) -> Row:
        values: dict[str, float] = {"__t": sample.sim_time_s}
        valid: dict[str, bool] = {}
        for key, name in {**NUMERIC_SIGNALS, **BOOL_SIGNALS}.items():
            v = sample.value(name)
            if isinstance(v, bool):
                values[key] = 1.0 if v else 0.0
            elif isinstance(v, (int, float)) and math.isfinite(v):
                values[key] = float(v)
            else:
                values[key] = math.nan
            tag = _VALIDITY_TAG.get(key)
            if tag is not None:
                ok, _, _ = self.freshness.check_signal(tag, sample)
                valid[key] = ok
            else:
                valid[key] = math.isfinite(values[key])
        return Row(sample.sim_time_s, sample.timestamp, values, valid)

    def _new_id(self) -> str:
        self._counter += 1
        return f"{self._id_prefix}-{self._counter:06d}"

    def _advance(self, rule: Rule, obs: Observation, t: float, ts: str) -> AlertChange | None:
        tr = self._trackers.setdefault((rule.rule_id, obs.key), _Tracker())
        tr.last_obs = obs
        cfg = rule.config
        if obs.triggered is None:  # not evaluable: freeze, but abandon a pending episode
            if tr.state == "pending":
                tr.state, tr.pending_since, tr.pending_obs = "idle", None, None
            return None

        if tr.state == "idle":
            if obs.triggered:
                tr.state, tr.pending_since, tr.pending_obs, tr.pending_ts = "pending", t, obs, ts
                if cfg.debounce_s <= 0:
                    return self._raise(rule, tr, obs, t, ts)
            return None

        if tr.state == "pending":
            if not obs.triggered:
                tr.state, tr.pending_since, tr.pending_obs = "idle", None, None
                return None
            if t - (tr.pending_since or t) >= cfg.debounce_s - 1e-9:
                return self._raise(rule, tr, obs, t, ts)
            return None

        # active
        alert = tr.alert
        assert alert is not None
        recovered = obs.recovered
        if recovered is None:
            recovered = obs.statistic is not None and abs(obs.statistic) < cfg.clear_ratio * obs.threshold
        if obs.triggered:
            alert.last_seen_t, alert.last_seen = t, ts
        alert.observed_value, alert.expected_value, alert.statistic = (
            obs.observed,
            obs.expected,
            obs.statistic,
        )
        alert.explanation = obs.explanation if obs.triggered else alert.explanation
        self._merge_metrics(alert, obs)
        changed = False
        if obs.score > alert.peak_score and obs.triggered:
            alert.peak_score = obs.score
            alert.peak_observed, alert.peak_expected = obs.observed, obs.expected
            alert.peak_explanation = obs.explanation
            self._set_evidence(alert, "peak", obs, t, ts, replace=True)
        if t - tr.last_evidence_t >= EVIDENCE_EVERY_S:
            self._set_evidence(alert, "update", obs, t, ts)
            tr.last_evidence_t = t
            changed = True
        if recovered:
            if tr.recover_since is None:
                tr.recover_since = t
            if t - tr.recover_since >= cfg.clear_s - 1e-9:
                alert.status = "cleared"
                alert.cleared_t, alert.cleared_at = t, ts
                self._set_evidence(alert, "cleared", obs, t, ts)
                tr.state, tr.recover_since, tr.alert = "idle", None, None
                tr.pending_since = tr.pending_obs = None
                return AlertChange("cleared", alert)
        else:
            tr.recover_since = None
        return AlertChange("updated", alert) if changed else None

    def _raise(self, rule: Rule, tr: _Tracker, obs: Observation, t: float, ts: str) -> AlertChange:
        onset = tr.pending_obs or obs
        onset_t = tr.pending_since if tr.pending_since is not None else t
        alert = Alert(
            id=self._new_id(),
            rule_id=rule.rule_id,
            title=rule.title,
            category=rule.category,
            severity=rule.config.severity,
            asset_id=obs.asset_id,
            instance_key=obs.key,
            signal=obs.signal,
            units=obs.units,
            threshold=obs.threshold,
            first_seen_t=onset_t,
            raised_t=t,
            last_seen_t=t,
            first_seen=tr.pending_ts or ts,
            raised_at=ts,
            last_seen=ts,
            observed_value=obs.observed,
            expected_value=obs.expected,
            statistic=obs.statistic,
            peak_score=obs.score,
            peak_observed=obs.observed,
            peak_expected=obs.expected,
            peak_explanation=obs.explanation,
            expected_label=rule.EXPECTED_LABEL.format(key=obs.key),
            observed_label=rule.OBSERVED_LABEL.format(key=obs.key),
            explanation=obs.explanation,
        )
        self._set_evidence(alert, "onset", onset, onset_t, tr.pending_ts or ts)
        self._set_evidence(alert, "raised", obs, t, ts)
        self._merge_metrics(alert, onset)
        self._merge_metrics(alert, obs)
        tr.state, tr.alert, tr.recover_since, tr.last_evidence_t = "active", alert, None, t
        return AlertChange("raised", alert)

    @staticmethod
    def _merge_metrics(alert: Alert, obs: Observation) -> None:
        rate = obs.evidence.get("deviation_rate_m_s")
        if isinstance(rate, (int, float)):
            alert.metrics["max_abs_deviation_rate_m_s"] = round(
                max(abs(rate), alert.metrics.get("max_abs_deviation_rate_m_s", 0.0)), 6
            )

    @staticmethod
    def _set_evidence(
        alert: Alert, phase: str, obs: Observation, t: float, ts: str, replace: bool = False
    ) -> None:
        entry = {
            "phase": phase,
            "t": round(t, 3),
            "ts": ts,
            "statistic": None if obs.statistic is None else round(obs.statistic, 5),
            "threshold": round(obs.threshold, 5),
            "observed": None if obs.observed is None else round(obs.observed, 5),
            "expected": None if obs.expected is None else round(obs.expected, 5),
            "values": obs.evidence,
        }
        if replace:
            alert.evidence = [e for e in alert.evidence if e["phase"] != phase]
        alert.evidence.append(entry)
        if len(alert.evidence) > MAX_EVIDENCE:
            # keep onset/raised/peak, drop the oldest periodic update
            for i, e in enumerate(alert.evidence):
                if e["phase"] == "update":
                    del alert.evidence[i]
                    break
        alert.evidence.sort(key=lambda e: e["t"])
