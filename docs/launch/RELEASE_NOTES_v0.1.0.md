# OT Sentinel Twin v0.1.0

**See the Process. Detect the Impossible.** First public release of an open-source OT/ICS security lab that checks
whether industrial telemetry is physically possible. Everything runs locally on synthetic data.

## Highlights

- **Digital twin** of a water storage tank with pump, valves, instruments and a PI controller — deterministic,
  seeded, and mass-conserving (verified to ~1e-12 m³).
- **Eight explainable detection rules**: mass balance, redundant-sensor disagreement, impossible rate of change,
  command/actuator mismatch, pump/process inconsistency, frozen sensor, pressure/flow inconsistency, telemetry
  freshness — each with documented statistics, thresholds, debounce and hysteresis.
- **Evidence-based incident classification** (data quality, equipment fault, physical anomaly, suspected manipulation)
  with confidence, rationale and non-malicious alternatives.
- **Scenario lab (A–H)** including a synthetic false-data injection on the controller's level input.
- **Incident workspace**, **deterministic replay**, **Markdown/JSON reports**.
- **Measured evaluation**: 30 labelled runs over 3 seeds — recall 1.000, precision 1.000, 0 false positives in 1.5 h of
  normal operation, mean latency 11.8 s (max 27.5 s). Robustness sweep: unchanged up to 2× plant/model mismatch,
  F1 0.694 at 3× (documented limit).
- **Hardened Docker Compose** stack, read-only demo overlay, CI with tests, audits, CodeQL and SHA-pinned actions.

## Verified in this release

- Backend: 65 tests, ruff, mypy. Frontend: 23 tests, ESLint, TypeScript strict, production build.
- 4 Playwright end-to-end journeys against the real backend.
- `docker compose up --build`: both containers healthy; UI, API, WebSocket (same-origin accepted, cross-origin refused).

## Known limitations

- Synthetic, single-tank plant; thresholds calibrated to its noise model.
- No user authentication/RBAC (use read-only mode or the API token for shared deployments).
- Not included: AI assistant, server-side PDF, static GitHub Pages demo. PostgreSQL untested.

## Safety

Not a safety system; no connectivity to real industrial equipment.
