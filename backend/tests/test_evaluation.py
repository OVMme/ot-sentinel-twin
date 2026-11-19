"""Evaluation harness scoring."""

from __future__ import annotations

from app.evaluation.harness import AlertOutcome, CaseResult, CaseSpec, run_case, summarise


def _fake(
    name: str, anomalous: bool, detected: bool, attributed: int, fp: int, latency: float | None
) -> CaseResult:
    return CaseResult(
        name=name,
        scenario_id=name,
        code="X",
        seed=1,
        params={},
        anomalous=anomalous,
        onset_t=0.0,
        stop_t=3600.0,
        expected_rules=["PHYS-001"],
        allowed_rules=[],
        detected=detected,
        latency_s=latency,
        first_rule="PHYS-001" if detected else None,
        rules_fired=[],
        attributed_alerts=attributed,
        false_positive_alerts=fp,
        expected_classification=None,
        classification=None,
        classification_ok=None,
        alerts=[AlertOutcome("a", "PHYS-001", "k", 1.0, 1.0, None, "expected")],
        simulated_s=3600.0,
        passed=detected and fp == 0,
    )


def test_metric_definitions() -> None:
    results = [
        _fake("normal", False, False, 0, 1, None),
        _fake("s1", True, True, 2, 0, 10.0),
        _fake("s2", True, False, 0, 1, None),
    ]
    s = summarise(results)
    assert s["true_positives"] == 1 and s["false_negatives"] == 1
    assert s["recall"] == 0.5
    assert s["precision"] == round(2 / 4, 4)
    assert s["f1"] == round(2 * 0.5 * 0.5 / 1.0, 4)
    assert s["normal_operation_false_positives"] == 1
    assert s["false_positives_per_hour_normal"] == 1.0


def test_multiple_alerts_do_not_inflate_detection_count() -> None:
    res = run_case(CaseSpec("sensor-manipulation", seed=2))
    assert res.attributed_alerts >= 2  # several rules fire ...
    s = summarise([res])
    assert s["true_positives"] == 1  # ... but the scenario counts once


def test_normal_case_has_no_false_positives() -> None:
    res = run_case(CaseSpec("normal-operation", seed=77, duration_s=900.0))
    assert res.false_positive_alerts == 0 and res.passed
