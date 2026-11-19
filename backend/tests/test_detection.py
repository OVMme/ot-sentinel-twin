"""Detection engine: every rule, thresholds, debouncing, recovery, noise and data-quality handling."""

from __future__ import annotations

import dataclasses
import inspect
from datetime import timedelta

import pytest

from app.detection.base import ProcessModel
from app.detection.correlation import IncidentCorrelator
from app.detection.engine import DetectionEngine
from app.evaluation.harness import CaseSpec, run_case
from app.scenarios.catalog import SCENARIOS
from app.simulation.engine import SimulationEngine, TelemetrySample
from app.simulation.params import SimulationConfig
from app.simulation.sensors import Reading, SensorFault


def _run(engine: SimulationEngine, det: DetectionEngine, n: int) -> list:
    raised = []
    for _ in range(n):
        r = det.process(engine.step())
        raised += [c.alert for c in r.changes if c.change == "raised"]
    return raised


# ------------------------------------------------------------------------------ isolation from ground truth
def test_detector_input_contains_no_ground_truth() -> None:
    fields = {f.name for f in dataclasses.fields(TelemetrySample)}
    assert fields == {"seq", "sim_time_s", "timestamp", "signals"}
    sig = inspect.signature(DetectionEngine.process)
    assert list(sig.parameters) == ["self", "sample"]


# ------------------------------------------------------------------------------ scenario-driven rule tests
@pytest.mark.parametrize(
    ("scenario", "params", "rule"),
    [
        ("stuck-inlet-valve", {}, "PHYS-004"),
        ("sensor-manipulation", {}, "PHYS-002"),
        ("sensor-manipulation", {}, "PHYS-001"),
        ("pump-fault", {}, "PHYS-005"),
        ("blocked-outlet", {}, "PHYS-007"),
        ("frozen-telemetry", {"signal": "LT-102", "mode": "stuck"}, "PHYS-006"),
        ("frozen-telemetry", {"signal": "LT-102", "mode": "stale"}, "DATA-001"),
        ("sensor-drift", {}, "PHYS-001"),
        ("sensor-drift", {}, "PHYS-002"),
        ("conflicting-measurements", {}, "PHYS-002"),
        ("conflicting-measurements", {}, "PHYS-003"),
    ],
)
def test_rule_fires_for_its_scenario_within_expected_latency(scenario: str, params: dict, rule: str) -> None:
    res = run_case(CaseSpec(scenario, params, seed=11))
    fired = [a for a in res.alerts if a.rule_id == rule and a.verdict != "false_positive"]
    assert fired, f"{rule} did not fire for {scenario}: {res.rules_fired}"
    assert res.false_positive_alerts == 0, [a for a in res.alerts if a.verdict == "false_positive"]
    limit = SCENARIOS[scenario].expected_latency_s
    assert res.latency_s is not None and limit is not None and res.latency_s <= limit


def test_discriminating_rules_do_not_cross_fire() -> None:
    pump = run_case(CaseSpec("pump-fault", seed=5))
    blocked = run_case(CaseSpec("blocked-outlet", seed=5))
    valve = run_case(CaseSpec("stuck-inlet-valve", seed=5))
    assert pump.rules_fired == ["PHYS-005"]
    assert blocked.rules_fired == ["PHYS-007"]
    assert valve.rules_fired == ["PHYS-004"]


@pytest.mark.parametrize(
    ("scenario", "params", "classification"),
    [
        ("sensor-manipulation", {}, "suspected_manipulation"),
        ("sensor-drift", {}, "equipment_fault"),
        ("conflicting-measurements", {}, "equipment_fault"),
        ("blocked-outlet", {}, "physical_anomaly"),
        ("frozen-telemetry", {"signal": "LT-102", "mode": "stale"}, "data_quality"),
        ("frozen-telemetry", {"signal": "FT-102", "mode": "stuck"}, "equipment_fault"),
    ],
)
def test_incident_classification(scenario: str, params: dict, classification: str) -> None:
    res = run_case(CaseSpec(scenario, params, seed=3))
    assert res.classification == classification


def test_slow_drift_on_controller_sensor_is_not_called_manipulation() -> None:
    res = run_case(CaseSpec("sensor-drift", {"signal": "LT-101", "drift_mm_s": 2.0}, seed=9))
    assert res.detected
    assert res.classification == "equipment_fault"


# ------------------------------------------------------------------------------ false positives
@pytest.mark.parametrize("seed", [101, 202])
def test_no_false_positives_in_one_hour_of_normal_operation(seed: int) -> None:
    cfg = SimulationConfig(seed=seed)
    eng = SimulationEngine(cfg)
    det = DetectionEngine(ProcessModel.from_config(cfg))
    assert _run(eng, det, 7200) == []


def test_no_false_positives_during_legitimate_operator_transitions(cfg: SimulationConfig) -> None:
    eng = SimulationEngine(cfg)
    det = DetectionEngine(ProcessModel.from_config(cfg))
    raised = _run(eng, det, 240)
    eng.set_mode("manual")
    for change in (
        {"outlet_pct": 0.0},
        {"pump_on": False},
        {"outlet_pct": 80.0},
        {"pump_on": True},
        {"inlet_pct": 100.0, "outlet_pct": 10.0},
        {"inlet_pct": 0.0, "outlet_pct": 100.0},
    ):
        eng.set_manual_commands(**change)
        raised += _run(eng, det, 240)
    eng.set_mode("auto")
    raised += _run(eng, det, 600)
    assert raised == []


def test_normal_noise_stays_well_below_thresholds(
    engine: SimulationEngine, detector: DetectionEngine
) -> None:
    peak: dict[str, float] = {}
    for _ in range(2400):
        r = detector.process(engine.step())
        for rid, score in r.analytics["scores"].items():
            peak[rid] = max(peak.get(rid, 0.0), score)
    # normalised score 1.0 == threshold; physics rules should keep a healthy margin under noise
    for rid in ("PHYS-001", "PHYS-002", "PHYS-003", "PHYS-004", "PHYS-005", "PHYS-007"):
        assert peak[rid] < 0.6, (rid, peak[rid])


# ------------------------------------------------------------------------------ debounce / recovery
def test_short_disturbance_is_debounced(engine: SimulationEngine, detector: DetectionEngine) -> None:
    _run(engine, detector, 240)
    engine.sensors.lt102.fault = SensorFault(offset_target=0.3, onset_time_s=engine.sim_time_s)
    raised = _run(engine, detector, 4)  # 2 s, shorter than the 5 s debounce of PHYS-002
    engine.sensors.lt102.clear_fault()
    raised += _run(engine, detector, 60)
    assert not [a for a in raised if a.rule_id == "PHYS-002"]


def test_alert_raises_once_and_clears_after_recovery(
    engine: SimulationEngine, detector: DetectionEngine
) -> None:
    _run(engine, detector, 240)
    engine.sensors.lt102.fault = SensorFault(offset_target=0.5, onset_time_s=engine.sim_time_s)
    changes = []
    for _ in range(120):
        changes += detector.process(engine.step()).changes
    raised = [c for c in changes if c.change == "raised" and c.alert.rule_id == "PHYS-002"]
    assert len(raised) == 1  # deduplicated: one alert per episode
    alert = raised[0].alert
    assert alert.first_seen_t <= alert.raised_t
    assert alert.raised_t - alert.first_seen_t >= detector.rule("PHYS-002").config.debounce_s - 1e-6
    engine.sensors.lt102.clear_fault()
    cleared = []
    for _ in range(120):
        cleared += [c for c in detector.process(engine.step()).changes if c.change == "cleared"]
    assert any(c.alert.id == alert.id for c in cleared)
    assert alert.status == "cleared" and alert.cleared_t is not None
    assert alert.evidence[0]["phase"] == "onset"


def test_threshold_is_configurable(engine: SimulationEngine, detector: DetectionEngine) -> None:
    _run(engine, detector, 240)
    detector.update_config("PHYS-002", threshold=1.0)
    engine.sensors.lt102.fault = SensorFault(offset_target=0.5, onset_time_s=engine.sim_time_s)
    assert not [a for a in _run(engine, detector, 60) if a.rule_id == "PHYS-002"]
    detector.update_config("PHYS-002", threshold=0.1)
    assert [a for a in _run(engine, detector, 60) if a.rule_id == "PHYS-002"]


# ------------------------------------------------------------------------------ data quality
def _with(sample: TelemetrySample, name: str, **changes) -> TelemetrySample:
    sig = dict(sample.signals)
    sig[name] = dataclasses.replace(sig[name], **changes)
    return dataclasses.replace(sample, signals=sig)


def test_missing_reading_is_a_data_quality_finding_not_physics(
    engine: SimulationEngine, detector: DetectionEngine
) -> None:
    _run(engine, detector, 240)
    raised = []
    for _ in range(20):
        s = _with(engine.step(), "flow.inlet_lps", value=None, quality="bad", valid=False)
        raised += [c.alert for c in detector.process(s).changes if c.change == "raised"]
    rules = {a.rule_id for a in raised}
    assert rules == {"DATA-001"}
    assert raised[0].instance_key == "FT-101"
    status = {r["rule_id"]: r for r in detector.status()}
    mb = {i["key"]: i for i in status["PHYS-001"]["instances"]}
    assert mb["LT-101"]["evaluable"] is False


def test_stream_gap_and_out_of_order_detected(cfg: SimulationConfig) -> None:
    eng = SimulationEngine(cfg)
    det = DetectionEngine(ProcessModel.from_config(cfg))
    _run(eng, det, 20)
    s = eng.step()
    gap = dataclasses.replace(
        s, seq=s.seq + 10, sim_time_s=s.sim_time_s + 5.0, timestamp=s.timestamp + timedelta(seconds=5)
    )
    changes = det.process(gap).changes
    for _ in range(4):
        changes += det.process(eng.step()).changes
    keys = {(c.alert.rule_id, c.alert.instance_key) for c in changes if c.change == "raised"}
    assert ("DATA-001", "STREAM") in keys

    det2 = DetectionEngine(ProcessModel.from_config(cfg))
    eng2 = SimulationEngine(cfg)
    _run(eng2, det2, 20)
    s2 = eng2.step()
    back = _with(s2, "pressure.line_bar", source_time_s=s2.sim_time_s - 3.0)
    det2.process(back)
    status = {r["rule_id"]: r for r in det2.status()}
    pt = {i["key"]: i for i in status["DATA-001"]["instances"]}["PT-101"]
    assert pt["state"] in ("pending", "active")


def test_reported_stopped_pump_with_flow_is_flagged(
    engine: SimulationEngine, detector: DetectionEngine
) -> None:
    _run(engine, detector, 240)
    raised = []
    for _ in range(60):
        s = engine.step()
        sig = dict(s.signals)
        sig["pump.running"] = Reading(False, "bool", s.sim_time_s, tag="YS-101")
        sig["pump.command"] = Reading(False, "bool", s.sim_time_s, tag="HS-101")
        raised += [
            c.alert
            for c in detector.process(dataclasses.replace(s, signals=sig)).changes
            if c.change == "raised"
        ]
    assert "PHYS-005" in {a.rule_id for a in raised}


def test_correlated_alerts_form_one_incident() -> None:
    cfg = SimulationConfig(seed=21)
    eng = SimulationEngine(cfg)
    from app.scenarios.manager import ScenarioManager

    mgr = ScenarioManager(eng)
    model = ProcessModel.from_config(cfg)
    det, corr = DetectionEngine(model), IncidentCorrelator(model)
    for _ in range(240):
        s = eng.step()
        corr.process(det.process(s).changes, s)
    mgr.start("sensor-manipulation")
    alerts = 0
    for _ in range(300):
        s = eng.step()
        r = det.process(s)
        alerts += sum(1 for c in r.changes if c.change == "raised")
        corr.process(r.changes, s)
    assert alerts >= 2
    assert len(corr.incidents) == 1
    inc = next(iter(corr.incidents.values()))
    assert len(inc.alert_ids) == alerts
    assert inc.classification == "suspected_manipulation"
    assert inc.alternatives and inc.classification_basis
