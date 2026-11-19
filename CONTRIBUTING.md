# Contributing

Thanks for your interest in OT Sentinel Twin! Contributions that improve physical fidelity, detection quality,
explainability, tests and documentation are especially welcome.

## Ground rules

1. **Synthetic only.** No code that connects to, scans or commands real industrial equipment or networks. Protocol
   emulation, if ever added, must be isolated and disabled by default.
2. **The detector stays blind.** Detection code may use reported telemetry and static engineering data only — never
   scenario labels, fault flags or physical truth.
3. **Measured, not claimed.** Detection metrics come from `scripts/run_evaluation.py`; update
   `docs/EVALUATION_RESULTS.md` by running it, never by hand.
4. **Explainable.** Every new rule documents its statistic, threshold derivation, window, debounce and evidence in
   `docs/DETECTION_ENGINE.md`.

## Development setup

```bash
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
cd frontend && npm ci
```

## Before opening a pull request

```bash
cd backend  && ruff check . && ruff format --check . && mypy app && pytest -q
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
cd frontend && npx playwright test        # needs the backend dependencies installed
python scripts/run_evaluation.py --seeds 1337   # if detection or simulation changed
```

* Add tests for new behaviour (physics invariants, rule thresholds, debounce/recovery, false-positive checks).
* Keep the UI honest: no hard-coded demo values; every chart labels data as simulated.
* Use clear commit messages; one logical change per pull request.

## Adding a scenario

Define it in `backend/app/scenarios/catalog.py` with initial conditions, trigger, exact changes, expected and allowed
rules, expected classification, target latency, required evidence and revert behaviour; add it to
`default_cases()` in the evaluation harness if it should be scored, and document it in `docs/SCENARIOS.md`.

## Code of conduct

Be respectful and constructive. Harassment or discrimination is not tolerated.
