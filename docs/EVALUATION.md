# Detection Evaluation Methodology

The harness ([`backend/app/evaluation/harness.py`](../backend/app/evaluation/harness.py)) runs labelled scenarios
headless and deterministically, feeds the resulting telemetry to a fresh `DetectionEngine` that knows nothing about the
scenario, and scores its alerts against ground truth. Results are written by
[`scripts/run_evaluation.py`](../scripts/run_evaluation.py) to
[`datasets/synthetic/evaluation_results.json`](../datasets/synthetic/evaluation_results.json) and
[`EVALUATION_RESULTS.md`](EVALUATION_RESULTS.md). **No metric in this repository is written by hand.**

## Protocol

For each seed (default 1337, 2024, 4242) and each case:

1. 120 s warm-up of normal operation (detector windows fill up; any alert here is a false positive).
2. Start the scenario; run for its evaluation duration (240 s; normal operation: 1800 s).
3. Stop the scenario and run a 90 s cool-down.

Cases: A (30 min normal), B, C, D, E, F × 3 variants (LT-102 stuck, LT-102 stale, FT-102 stuck), G, H → 10 cases per
seed, 30 runs, 27 anomalous, 1.5 h of labelled normal operation.

## Definitions

| Term | Definition |
|---|---|
| Ground-truth window | `[fault onset, scenario stop + 30 s]` |
| Attributed alert | raised inside the window by an *expected* or *allowed* rule of that scenario |
| False-positive alert | any other alert — every alert during normal operation, warm-up, cool-down, or by an unexpected rule |
| Deduplication | one alert per raise→clear episode of a rule instance (engine-level); a scenario that triggers several rules still counts as **one** detected scenario |
| True positive | anomalous run in which ≥ 1 expected rule raised inside the window |
| False negative | anomalous run without any expected-rule alert inside the window |
| Precision | attributed alerts / all alerts (alert level) |
| Recall | detected anomalous runs / anomalous runs (scenario level) |
| F1 | harmonic mean of precision and recall |
| Latency | first expected-rule raise time − fault onset (includes debounce) |
| Classification accuracy | fraction of detected anomalous runs whose incident class equals the scenario's expected class |

*Allowed* rules exist because some faults legitimately trip more than one check (e.g. a frozen level transmitter also
breaks mass balance). They are neither rewarded nor penalised.

## Robustness study: plant / model mismatch

With identical models on both sides, perfect scores mostly verify internal consistency. To test robustness, the harness
re-runs every case with a simulated plant that **deviates** from the detector's nominal model while the detector keeps
the nominal model. Severity 1.0 means:

| Parameter | Deviation at 1.0× |
|---|---|
| Tank area | +3 % |
| Inlet capacity | +4 % |
| Outlet valve Kv | −5 % |
| Pump shut-off head | −4 % |
| Valve stroke speed | 15 % slower |
| Instrument noise (level, flow, pressure, position) | × 1.5 |

Deviations scale linearly with severity (noise factor `1 + 0.5 × severity`). The sweep covers 1×, 2× and 3×.

### What the sweep found (and what was changed)

* The first version of PHYS-004 used a single nominal actuator trajectory. At 1× mismatch the slower actuator produced
  false PHYS-004 alerts on long strokes (precision 0.88). The rule now uses a ±30 % speed envelope; precision at 1× and
  2× returned to 1.0 while the stuck-valve scenario is still detected in ~9 s.
* At 3× (Kv −15 %, pump head −12 %, actuators 45 % slower, noise × 2.5) PHYS-007's 15 % tolerance is exceeded by the
  model error and PHYS-004's envelope by the actuator error: false positives appear in normal operation and the
  blocked-outlet scenario is masked. This is the expected limit of fixed-model detection and motivates model
  calibration (roadmap).

## Reproducing

```bash
python scripts/run_evaluation.py --seeds 1337 2024 4242
python scripts/generate_dataset.py --seed 1337     # labelled CSVs for offline analysis
```

From the UI, **Detection Analytics → Re-run (1 seed)** executes the same harness in a background thread (disabled in
read-only deployments). CI runs a single-seed evaluation and fails if any scenario is missed or any false positive
occurs during normal operation.

## Limitations

* Synthetic plant and synthetic faults: results say nothing about real equipment.
* Scenario parameters are fixed per case; the parameter space (e.g. very slow drifts, tiny offsets) is not swept.
* Detectability limits exist by design: an offset smaller than the disagreement tolerance (0.10 m) that also stays
  within the mass-balance threshold is not detected.
