# LinkedIn launch materials

> Drafts only — nothing has been posted. Replace `<REPOSITORY URL>` after the repository is published.

## A. Technical post

**A signal can look normal on its own while the process as a whole is impossible.**

That's the idea behind OT Sentinel Twin, an open-source project I've just released.

In OT/ICS security, a lot of monitoring focuses on the network: signatures, allow-lists, anomalous connections. All
valuable — but a falsified sensor value travelling over a perfectly normal-looking connection can still slip through.
Physics can't be fooled as easily: water doesn't appear from nowhere, a pump that is "running" has to develop
pressure, and a transmitter that hasn't changed by a single millimetre while the tank fills is not telling the truth.

OT Sentinel Twin is a fully synthetic digital twin of a water storage process (tank, pump, valves, instruments, a PI
controller with interlocks) plus a detection engine that asks one question: *is this telemetry physically consistent?*

What's implemented:
🔹 A deterministic, mass-conserving plant model (verified by tests to ~1e-12 m³)
🔹 8 explainable rules: mass balance, redundant-sensor disagreement, impossible rate of change, command/actuator
mismatch, pump-curve consistency, frozen sensors, pressure/flow consistency, telemetry freshness
🔹 Evidence-based incident classification — physical anomaly, equipment fault, data-quality issue or *suspected*
manipulation — always with non-malicious alternatives
🔹 A scenario lab (stuck valve, pump fault, blocked line, drift, frozen telemetry, false-data injection…)
🔹 An animated SVG twin, incident workspace, deterministic replay and Markdown/JSON reports

Measured on 30 labelled runs: every scenario detected, zero false positives in 1.5 h of normal operation, mean latency
11.8 s. Because perfect scores on a model-matched simulator prove little, I also ran a plant/model-mismatch sweep: clean
up to 2× mismatch, and it degrades (F1 0.69) at 3× — documented, along with how a coordinated attacker could evade it.

Everything is synthetic and local: no PLCs, no protocols, no real networks. FastAPI + NumPy on the backend, React +
TypeScript + ECharts on the front, Docker Compose to run it.

Repository: <REPOSITORY URL>

Feedback from OT engineers and detection engineers is very welcome.

#OTSecurity #ICS #CyberSecurity #DigitalTwin #DetectionEngineering #IndustrialControlSystems #BlueTeam

## B. Short post

I built **OT Sentinel Twin** — an open-source lab that detects industrial anomalies by checking the *physics*, not just
the network. A synthetic digital twin, 8 explainable rules (mass balance, pump curves, redundant sensors, frozen
telemetry…), incident investigation and deterministic replay. Every scenario detected, 0 false positives in 1.5 h of
normal operation — and an honest robustness study showing where it breaks. 100 % synthetic, runs locally with Docker.

<REPOSITORY URL>

#OTSecurity #ICS #DetectionEngineering #DigitalTwin
