# Scenario Laboratory

Source: [`backend/app/scenarios/catalog.py`](../backend/app/scenarios/catalog.py). Scenarios modify **only the
simulated plant or simulated instruments**. They are ground truth for the lab and the evaluation harness and are never
visible to the detection engine. All events are recorded as `scenario_events` and labelled synthetic in reports.

Common behaviour:

* **Start**: recorded as `started`; the fault begins after the *onset delay* (`fault_onset` event). Timed actions are
  relative to onset.
* **End**: the scenario's revert restores the plant (faults removed, setpoint restored); recorded as `stopped`.
* **Reset** (simulation): stops any scenario and starts a new recorded run from the documented initial state
  (level 3.0 m = 60 %, AUTO, balanced flows, seeded instrument biases).
* **Scoring window** for evaluation: `[fault onset, stop + 30 s]` (the grace period covers steps when a fault is removed).
* Initial conditions for all anomaly scenarios: AUTO mode, level at setpoint, detector warmed up (≥ 120 s of
  normal operation in the evaluation harness).

| | Scenario | Onset | Exact changes | Expected rules | Allowed rules | Expected class | Target latency |
|---|---|---|---|---|---|---|---|
| A | Normal operation | 0 s | none | none | none | — | — |
| B | Stuck inlet valve | 5 s | XV-101 physical position frozen; +5 s operator raises setpoint +10 % | PHYS-004 | — | equipment fault | ≤ 15 s |
| C | Sensor value manipulation | 5 s | LT-101 reported = truth + offset; offset ramps to −1.4 m over 50 s | PHYS-002, PHYS-001 | PHYS-003 | suspected manipulation | ≤ 20 s |
| D | Pump fault | 5 s | pump head factor 0.15 (motor and run feedback unaffected) | PHYS-005 | — | equipment fault | ≤ 15 s |
| E | Blocked outlet | 5 s | outlet restriction ramps to 0.75 over 10 s (downstream of PT-101) | PHYS-007 | — | physical anomaly | ≤ 20 s |
| F | Frozen telemetry | 5 s | selected transmitter holds its value (`stuck`: timestamps fresh / `stale`: timestamp held); +10 s setpoint +15 % | `stuck`: PHYS-006 · `stale`: DATA-001 | `stuck`: mass balance / disagreement / rate (level) or PHYS-001/005/007 (flow, pressure) | equipment fault / data quality | ≤ 45 s |
| G | Gradual sensor drift | 5 s | LT-102 (or LT-101) drifts +2 mm/s | PHYS-001, PHYS-002 | PHYS-003 | equipment fault | ≤ 60 s |
| H | Conflicting measurements | 5 s | LT-102 step offset +0.8 m | PHYS-002 | PHYS-001, PHYS-003 | equipment fault | ≤ 10 s |

## Details and required evidence

**A — Normal operation.** Marks a labelled normal window; any alert inside it is a false positive.
Evidence: absence of alerts; residuals within thresholds.

**B — Stuck inlet valve.** The actuator stops responding while ZT-101 truthfully reports the frozen position. The
setpoint step forces the controller to demand travel. Mass balance stays consistent because flows are measured
correctly. Evidence: command vs. healthy-envelope position vs. feedback; duration beyond stroke time.

**C — Sensor value manipulation (synthetic false-data injection).** LT-101 is the controller's process variable. The
falsified low reading makes the controller open XV-101; the real level rises while LT-101 looks like a plausible
trend. Evidence: LT-101 vs LT-102 difference, mass-balance residual isolated to LT-101, abrupt onset rate, controller
acting on an error the redundant transmitter does not confirm. Parameters: `offset_m` (−2 … 2 m), `ramp_s` (0 … 600 s).
With −2.0 m the real level reaches the LT-102 high interlock (95 %), which closes the inlet — the independent
protection layer works.

**D — Pump fault.** Models impeller damage / coupling slip: P-101 runs and draws idle power but develops 15 % of its
head. Flow and pressure drop together, remaining consistent with the valve equation (so PHYS-007 stays quiet) but not
with the pump curve. Parameter: `head_factor`.

**E — Blocked outlet.** A restriction downstream of PT-101 (e.g. fouled strainer) cuts flow at unchanged valve
opening; pressure rises towards dead-head. The pump curve stays consistent (PHYS-005 quiet), the valve equation does
not. Parameter: `restriction`.

**F — Frozen telemetry.** Parameters: `signal` (LT-102, LT-101, FT-101, FT-102, PT-101) and `mode`
(`stuck` = gateway re-publishing a cached value with fresh timestamps; `stale` = transmitter silent). The setpoint step
ensures the process changes, so a frozen value is observable. When the fault is removed the transmitter jumps to the
true value — a physically impossible step that PHYS-003 may legitimately flag (allowed).

**G — Gradual sensor drift.** Progressive detection: the mass-balance residual accumulates first (~16–19 s at
2 mm/s), the redundant disagreement follows. The slow onset (< 5 mm/s) leads to *equipment fault (drift)*, not
manipulation — even when LT-101 (the PV) is the drifting sensor (tested). Parameters: `signal`, `drift_mm_s`.

**H — Conflicting measurements.** A sudden span/range error on LT-102. Abrupt, isolated to LT-102, but LT-102 is not
the controller PV and no control impact occurs → equipment fault; manipulation is listed as an alternative.

## Measured detection

See [EVALUATION_RESULTS.md](EVALUATION_RESULTS.md) for the executed coverage matrix (latency per scenario across seeds).
