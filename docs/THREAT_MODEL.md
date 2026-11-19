# Threat Model

Two different things are modelled here: (1) the **synthetic OT threats** the platform demonstrates detection for, and
(2) the **security of the platform itself** as a web application.

## 1. Synthetic OT threats in scope

The simulated asset is a tank level control loop. Scenarios represent what an adversary *or* a fault could do to the
process data or equipment. All are implemented inside the simulator only.

| Threat (synthetic) | Example technique (MITRE ATT&CK for ICS, for orientation) | Scenario | Physics evidence |
|---|---|---|---|
| False-data injection on the controller PV | Manipulation of Control / Spoof Reporting Message | C | redundancy, mass balance, control impact |
| Replay / cached value of a transmitter | Spoof Reporting Message | F (stuck) | flatline vs. independent prediction |
| Loss of view (telemetry stops) | Block Reporting Message | F (stale) | source timestamp age |
| Actuator does not follow command | Manipulation of Control (or mechanical fault) | B | healthy stroking envelope |
| Equipment degradation masking | Loss of Productivity / Damage to Property | D, E | pump curve, valve equation |
| Gradual sensor tampering vs. ageing | Spoof Reporting Message | G | residual growth rate |

The classifier deliberately reports *suspected manipulation* only when a falsified value is isolated, abrupt and
demonstrably steering the controller — and even then lists non-malicious explanations. Telemetry alone cannot prove
intent.

### Known evasions (limitations)

* **Coordinated falsification:** an adversary who modifies LT-101, LT-102 *and* the flow meters consistently with a
  plausible (but false) mass balance can evade physics-consistency rules. Mitigations outside this project: independent
  measurement paths, signed telemetry, out-of-band verification.
* **Sub-threshold manipulation:** offsets smaller than the disagreement tolerance (0.10 m) that also stay within the
  mass-balance residual budget are not detected (by design, to keep false positives near zero).
* **Model knowledge:** an attacker who knows the thresholds can stay below them. Thresholds are configurable and
  should be tuned per site.
* **Compromised detector host:** out of scope; the detector trusts its own process.

## 2. Platform security (STRIDE summary)

Assets: the simulation state, stored evidence (runs, incidents, notes, audit trail), host resources.

| Threat | Control in v0.1.0 |
|---|---|
| **S**poofing — cross-site use of the API/WebSocket from a malicious page | restrictive CORS allow-list; WebSocket `Origin` validated (allow-list or same-origin), cross-origin handshakes refused (tested) |
| **T**ampering — malformed or oversized input | Pydantic validation with `extra="forbid"`, path parameter patterns, 64 KiB body limit, 1 KiB WebSocket inbound limit, parameterised SQL |
| **R**epudiation — unattributed analyst actions | local audit trail for every state-changing action (actor from validated `X-Analyst` header) — *not* authenticated in local mode |
| **I**nformation disclosure — error details, path traversal | consistent error format without stack traces; IDs validated by regex; export filenames sanitised; `nosniff`, `DENY` framing, `no-referrer`, CSP in nginx |
| **D**enial of service — unlimited simulations, alert storms, slow clients | single runtime per process (no user-spawned simulations), speed capped (default 10x), evaluation one-at-a-time and disabled in read-only mode, rate limit on state-changing calls, bounded buffers/queues/retention, WebSocket client cap, container CPU/memory limits |
| **E**levation of privilege — container breakout | non-root users, read-only root filesystems, `cap_drop: ALL`, `no-new-privileges`, ports bound to 127.0.0.1 |

### Deployment guidance

* Local use: defaults are safe (localhost-only, no external services, no secrets).
* Public demo: `OTST_READ_ONLY=true` (+ `OTST_DEMO_MODE=true`) so no state can be changed; put a TLS reverse proxy in
  front; keep the container limits.
* Shared/internal: set `OTST_API_TOKEN` (constant-time comparison) and restrict network access. There is no user
  management or RBAC in v0.1.0.
