"""Labelled-scenario evaluation harness.

Runs every scenario headless (as fast as the CPU allows, fully deterministic per seed), feeds the
telemetry to a fresh DetectionEngine that knows nothing about the scenario, and scores the alerts
against the scenario's ground truth.

Scoring definitions (also in docs/EVALUATION.md):

* Ground-truth window  = [fault onset, scenario stop + GRACE_S].
* An alert is *attributed* if it is raised inside the window by a rule listed as expected or
  allowed for that scenario. Every other alert (including any alert in normal operation, during
  warm-up or after the window) is a *false positive*.
* Alerts are already deduplicated by the engine: one alert per raise..clear episode of a rule
  instance. A rule instance that re-raises within the same window is counted once.
* A scenario run is a *true positive* if at least one expected rule raises inside the window,
  otherwise a *false negative*. Latency = first expected-rule raise time - fault onset.
* Precision = attributed alerts / all alerts. Recall = detected anomalous runs / anomalous runs.
  F1 = harmonic mean of the two.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.detection.base import ProcessModel
from app.detection.correlation import IncidentCorrelator
from app.detection.engine import DetectionEngine
from app.scenarios.catalog import SCENARIOS, get_scenario
from app.scenarios.manager import ScenarioManager
from app.simulation.engine import SimulationEngine
from app.simulation.params import SimulationConfig

GRACE_S = 30.0
WARMUP_S = 120.0
COOLDOWN_S = 90.0


@dataclass
class CaseSpec:
    scenario_id: str
    params: dict[str, Any] = field(default_factory=dict)
    seed: int = 1337
    duration_s: float | None = None
    label: str | None = None

    @property
    def name(self) -> str:
        if self.label:
            return self.label
        d = get_scenario(self.scenario_id)
        suffix = ",".join(f"{k}={v}" for k, v in self.params.items())
        return f"{d.code} {d.title}" + (f" [{suffix}]" if suffix else "")


@dataclass
class AlertOutcome:
    alert_id: str
    rule_id: str
    instance_key: str
    raised_t: float
    first_seen_t: float
    cleared_t: float | None
    verdict: str  # expected | allowed | false_positive


@dataclass
class CaseResult:
    name: str
    scenario_id: str
    code: str
    seed: int
    params: dict[str, Any]
    anomalous: bool
    onset_t: float
    stop_t: float
    expected_rules: list[str]
    allowed_rules: list[str]
    detected: bool
    latency_s: float | None
    first_rule: str | None
    rules_fired: list[str]
    attributed_alerts: int
    false_positive_alerts: int
    expected_classification: str | None
    classification: str | None
    classification_ok: bool | None
    alerts: list[AlertOutcome]
    simulated_s: float
    passed: bool


def mismatched_plant(cfg: SimulationConfig, severity: float = 1.0) -> SimulationConfig:
    """A 'real' plant that deviates from the detector's nominal model (robustness study).

    At severity 1.0: tank area +3 %, inlet capacity +4 %, outlet valve Kv -5 %, pump shut-off head -4 %,
    valve stroke 15 % slower, instrument noise x1.5. Deviations scale linearly with ``severity``.
    The detector keeps using the nominal model.
    """
    k = severity
    n = cfg.noise
    noise = 1.0 + 0.5 * k
    return cfg.model_copy(
        update={
            "tank": cfg.tank.model_copy(update={"area_m2": cfg.tank.area_m2 * (1 + 0.03 * k)}),
            "inlet": cfg.inlet.model_copy(update={"max_flow_lps": cfg.inlet.max_flow_lps * (1 + 0.04 * k)}),
            "outlet": cfg.outlet.model_copy(
                update={"valve_kv_lps_per_sqrt_bar": cfg.outlet.valve_kv_lps_per_sqrt_bar * (1 - 0.05 * k)}
            ),
            "pump": cfg.pump.model_copy(update={"shutoff_bar": cfg.pump.shutoff_bar * (1 - 0.04 * k)}),
            "valve": cfg.valve.model_copy(
                update={"travel_rate_pct_s": cfg.valve.travel_rate_pct_s * max(1 - 0.15 * k, 0.2)}
            ),
            "noise": n.model_copy(
                update={
                    "level_m": n.level_m * noise,
                    "flow_lps": n.flow_lps * noise,
                    "pressure_bar": n.pressure_bar * noise,
                    "position_pct": n.position_pct * noise,
                }
            ),
        }
    )


def run_case(
    spec: CaseSpec, base_config: SimulationConfig | None = None, model_mismatch: float = 0.0
) -> CaseResult:
    cfg = (base_config or SimulationConfig()).model_copy(update={"seed": spec.seed})
    plant_cfg = mismatched_plant(cfg, model_mismatch) if model_mismatch > 0 else cfg
    engine = SimulationEngine(plant_cfg, epoch=datetime(2026, 1, 1, tzinfo=UTC))
    manager = ScenarioManager(engine)
    model = ProcessModel.from_config(cfg)  # detector always uses the nominal (documented) model
    detector = DetectionEngine(model)
    correlator = IncidentCorrelator(model)
    definition = get_scenario(spec.scenario_id)
    duration = spec.duration_s or definition.eval_duration_s
    alerts = {}

    def step() -> None:
        sample = engine.step()
        result = detector.process(sample)
        for ch in result.changes:
            alerts[ch.alert.id] = ch.alert
        correlator.process(result.changes, sample)

    while engine.sim_time_s < WARMUP_S - 1e-9:
        step()
    active = manager.start(definition.id, spec.params)
    onset_t = active.onset_t
    stop_at = engine.sim_time_s + definition.onset_delay_s + duration
    while engine.sim_time_s < stop_at - 1e-9:
        step()
    manager.stop("evaluation window complete")
    stop_t = engine.sim_time_s
    end_at = stop_t + COOLDOWN_S
    while engine.sim_time_s < end_at - 1e-9:
        step()

    params = active.params
    expected = set(definition.expected_rules_fn(params))
    allowed = set(definition.allowed_rules_fn(params))
    anomalous = definition.category != "normal"
    win_lo, win_hi = onset_t, stop_t + GRACE_S
    outcomes: list[AlertOutcome] = []
    latency: float | None = None
    first_rule: str | None = None
    first_alert = None
    for a in sorted(alerts.values(), key=lambda x: x.raised_t):
        in_window = anomalous and win_lo <= a.raised_t <= win_hi
        if in_window and a.rule_id in expected:
            verdict = "expected"
            lat = a.raised_t - onset_t
            if latency is None or lat < latency:
                latency, first_rule, first_alert = lat, a.rule_id, a
        elif in_window and a.rule_id in allowed:
            verdict = "allowed"
        else:
            verdict = "false_positive"
        outcomes.append(
            AlertOutcome(a.id, a.rule_id, a.instance_key, a.raised_t, a.first_seen_t, a.cleared_t, verdict)
        )

    detected = latency is not None
    exp_cls = definition.expected_classification_fn(params)
    cls = None
    if first_alert is not None and first_alert.incident_id in correlator.incidents:
        cls = correlator.incidents[first_alert.incident_id].classification
    cls_ok = None if exp_cls is None else (cls == exp_cls)
    fp = sum(1 for o in outcomes if o.verdict == "false_positive")
    attributed = sum(1 for o in outcomes if o.verdict != "false_positive")
    passed = (detected and fp == 0) if anomalous else fp == 0
    return CaseResult(
        name=spec.name,
        scenario_id=definition.id,
        code=definition.code,
        seed=spec.seed,
        params=params,
        anomalous=anomalous,
        onset_t=onset_t,
        stop_t=stop_t,
        expected_rules=sorted(expected),
        allowed_rules=sorted(allowed),
        detected=detected,
        latency_s=None if latency is None else round(latency, 2),
        first_rule=first_rule,
        rules_fired=sorted({o.rule_id for o in outcomes}),
        attributed_alerts=attributed,
        false_positive_alerts=fp,
        expected_classification=exp_cls,
        classification=cls,
        classification_ok=cls_ok,
        alerts=outcomes,
        simulated_s=engine.sim_time_s,
        passed=passed,
    )


def default_cases(seeds: tuple[int, ...] = (1337, 2024, 4242)) -> list[CaseSpec]:
    cases: list[CaseSpec] = []
    for seed in seeds:
        cases.append(
            CaseSpec("normal-operation", seed=seed, duration_s=1800.0, label="A Normal Operation (30 min)")
        )
        for sid in SCENARIOS:
            if sid == "normal-operation":
                continue
            if sid == "frozen-telemetry":
                cases.append(
                    CaseSpec(
                        sid,
                        {"signal": "LT-102", "mode": "stuck"},
                        seed=seed,
                        label="F Frozen Telemetry [LT-102 stuck]",
                    )
                )
                cases.append(
                    CaseSpec(
                        sid,
                        {"signal": "LT-102", "mode": "stale"},
                        seed=seed,
                        label="F Frozen Telemetry [LT-102 stale]",
                    )
                )
                cases.append(
                    CaseSpec(
                        sid,
                        {"signal": "FT-102", "mode": "stuck"},
                        seed=seed,
                        label="F Frozen Telemetry [FT-102 stuck]",
                    )
                )
            else:
                cases.append(CaseSpec(sid, seed=seed))
    return cases


def summarise(results: list[CaseResult]) -> dict[str, Any]:
    anomalous = [r for r in results if r.anomalous]
    tp = sum(1 for r in anomalous if r.detected)
    fn = len(anomalous) - tp
    attributed = sum(r.attributed_alerts for r in results)
    fp = sum(r.false_positive_alerts for r in results)
    precision = attributed / (attributed + fp) if attributed + fp else 1.0
    recall = tp / len(anomalous) if anomalous else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    normal = [r for r in results if not r.anomalous]
    normal_hours = sum((r.stop_t - r.onset_t) for r in normal) / 3600.0
    normal_fp = sum(r.false_positive_alerts for r in normal)
    lat = [r.latency_s for r in anomalous if r.latency_s is not None]
    cls = [r for r in anomalous if r.classification_ok is not None]

    matrix: dict[str, dict[str, Any]] = {}
    for r in results:
        m = matrix.setdefault(
            r.name,
            {
                "scenario": r.name,
                "code": r.code,
                "expected_rules": r.expected_rules,
                "allowed_rules": r.allowed_rules,
                "runs": 0,
                "detected": 0,
                "latencies": [],
                "false_positives": 0,
                "rules_fired": set(),
                "classification_expected": r.expected_classification,
                "classification_ok": 0,
                "classifications": set(),
                "anomalous": r.anomalous,
            },
        )
        m["runs"] += 1
        m["detected"] += int(r.detected)
        if r.latency_s is not None:
            m["latencies"].append(r.latency_s)
        m["false_positives"] += r.false_positive_alerts
        m["rules_fired"].update(r.rules_fired)
        if r.classification:
            m["classifications"].add(r.classification)
        m["classification_ok"] += int(bool(r.classification_ok))
    rows = []
    for m in matrix.values():
        lats = m.pop("latencies")
        m["rules_fired"] = sorted(m["rules_fired"])
        m["classifications"] = sorted(m["classifications"])
        m["latency_mean_s"] = round(sum(lats) / len(lats), 2) if lats else None
        m["latency_max_s"] = round(max(lats), 2) if lats else None
        m["result"] = (
            "PASS"
            if (m["false_positives"] == 0 and (m["detected"] == m["runs"] or not m["anomalous"]))
            else "FAIL"
        )
        rows.append(m)
    return {
        "runs": len(results),
        "anomalous_runs": len(anomalous),
        "true_positives": tp,
        "false_negatives": fn,
        "attributed_alerts": attributed,
        "false_positive_alerts": fp,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "latency_mean_s": round(sum(lat) / len(lat), 2) if lat else None,
        "latency_max_s": round(max(lat), 2) if lat else None,
        "normal_operation_hours": round(normal_hours, 3),
        "normal_operation_false_positives": normal_fp,
        "false_positives_per_hour_normal": round(normal_fp / normal_hours, 4) if normal_hours else None,
        "classification_accuracy": round(sum(1 for r in cls if r.classification_ok) / len(cls), 4)
        if cls
        else None,
        "coverage_matrix": rows,
    }


def run_evaluation(
    seeds: tuple[int, ...] = (1337, 2024, 4242),
    base_config: SimulationConfig | None = None,
    robustness_severities: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> dict[str, Any]:
    """Nominal evaluation plus a plant/model-mismatch sensitivity sweep (see ``mismatched_plant``)."""
    started = time.perf_counter()
    results = [run_case(c, base_config) for c in default_cases(seeds)]
    summary = summarise(results)
    robustness: list[dict[str, Any]] = []
    for sev in robustness_severities:
        mm = [run_case(c, base_config, model_mismatch=sev) for c in default_cases(seeds)]
        s = summarise(mm)
        robustness.append(
            {
                "severity": sev,
                "precision": s["precision"],
                "recall": s["recall"],
                "f1": s["f1"],
                "latency_mean_s": s["latency_mean_s"],
                "false_positive_alerts": s["false_positive_alerts"],
                "normal_operation_false_positives": s["normal_operation_false_positives"],
                "classification_accuracy": s["classification_accuracy"],
                "false_positive_rules": sorted(
                    {a.rule_id for r in mm for a in r.alerts if a.verdict == "false_positive"}
                ),
                "missed": sorted({r.name for r in mm if r.anomalous and not r.detected}),
            }
        )
    return {
        "robustness": {
            "description": (mismatched_plant.__doc__ or "").strip(),
            "sweep": robustness,
        },
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "data_notice": "All data is synthetic. Results describe the detector's behaviour on this simulated plant only.",
        "seeds": list(seeds),
        "definitions": {
            "ground_truth_window": f"[fault onset, scenario stop + {GRACE_S:.0f} s]",
            "warmup_s": WARMUP_S,
            "cooldown_s": COOLDOWN_S,
            "true_positive": "Scenario run in which >=1 expected rule raises an alert inside the ground-truth window.",
            "false_positive": "Any alert not raised by an expected/allowed rule inside the window (incl. all alerts "
            "during normal operation, warm-up and cool-down).",
            "precision": "attributed alerts / all alerts",
            "recall": "detected anomalous runs / anomalous runs",
            "latency": "first expected-rule alert raise time - fault onset time",
        },
        "summary": summary,
        "cases": [asdict(r) for r in results],
        "wall_time_s": round(time.perf_counter() - started, 2),
    }
