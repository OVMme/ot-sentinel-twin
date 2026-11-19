# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] — initial release

### Added
- Deterministic, seeded digital twin: tank mass balance with overflow/dry-run bookkeeping, pump curve, rate-limited
  valves, closed-form hydraulics, instruments with noise/bias/quantisation/quality, PI controller with feed-forward and
  independent interlocks.
- Detection engine with eight rules (PHYS-001…007, DATA-001), uniform debounce/hysteresis/deduplication, evidence
  capture and peak tracking.
- Incident correlation and evidence-based classification (data quality, equipment fault, physical anomaly, suspected
  manipulation) with confidence, rationale, alternatives and recommended steps.
- Scenario lab with scenarios A–H, parameters, ground-truth events and live expected-vs-actual comparison.
- FastAPI REST + WebSocket API, SQLite persistence, retention limits, audit trail.
- React frontend: overview, animated SVG twin (truth vs. HMI view), live telemetry (8 charts), detection analytics,
  incident workspace, scenario lab, deterministic replay, reports, settings, architecture page.
- Markdown/JSON incident reports; telemetry CSV/JSON export; evidence packages.
- Evaluation harness with coverage matrix and plant/model-mismatch robustness sweep; labelled synthetic datasets.
- Docker Compose (hardened, localhost-only), read-only demo overlay, GitHub Actions CI, CodeQL, Dependabot.
- 65 backend tests, 23 frontend tests, 4 Playwright end-to-end tests.
