# API

Interactive OpenAPI documentation is generated automatically at **`/api/docs`** (schema: `/api/openapi.json`).
All data is synthetic. Every response carries `X-Synthetic-Data: true`.

## Conventions

* JSON in and out; request bodies validated with Pydantic (`extra` fields rejected); body limit 64 KiB.
* Errors use one format:
  ```json
  {"error": {"code": "validation_error", "message": "Request validation failed.", "details": [{"loc": ["body", "speed"], "msg": "..."}]}}
  ```
  Codes include `validation_error`, `not_found`, `not_manual`, `speed_limit`, `invalid_config`, `invalid_params`,
  `read_only`, `unauthorized`, `rate_limited`, `busy`, `payload_too_large`.
* Paginated lists return `{"total", "limit", "offset", "items"}`.
* **State-changing** endpoints (POST/PUT below) are refused with `403 read_only` when `OTST_READ_ONLY=true`, require
  `X-API-Key` when `OTST_API_TOKEN` is set, are rate limited per client, and are written to the audit trail. The
  optional `X-Analyst` header (`[A-Za-z0-9 ._-]{1,40}`) names the actor.

## Endpoints

### System
| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | status, version, simulation state, database check |
| GET | `/api/assets` | synthetic asset register |
| GET | `/api/signals` | signal catalogue (name, asset, tag, unit) |
| GET | `/api/audit?limit&offset` | audit trail |

### Simulation
| Method | Path | Description |
|---|---|---|
| GET | `/api/simulation/state` | run id, status, speed, sim time, mode, setpoint, interlocks, active scenario, detection status, health |
| POST | `/api/simulation/start` | start / resume pacing |
| POST | `/api/simulation/pause` | pause (flushes pending writes) |
| POST | `/api/simulation/reset` | `{"seed"?: int}` — stop scenario, close run, start a new run from the documented initial state |
| POST | `/api/simulation/speed` | `{"speed": 0.25…max}` |
| POST | `/api/simulation/mode` | `{"mode": "auto" \| "manual"}` |
| POST | `/api/simulation/operator` | `{"setpoint_pct"?, "inlet_valve_pct"?, "outlet_valve_pct"?, "pump_on"?}` — valve/pump commands require MANUAL (`409 not_manual`) |
| GET | `/api/simulation/config` | active configuration + JSON schema |
| PUT | `/api/simulation/config` | full `SimulationConfig`; validated, applied via reset |

### Telemetry
| Method | Path | Description |
|---|---|---|
| GET | `/api/telemetry` | latest sample |
| GET | `/api/telemetry/recent?limit≤1200` | in-memory recent samples of the current run |
| GET | `/api/telemetry/history?run_id&from_seq&limit≤5000&full` | stored samples (columns, or full payloads with quality/timestamps/truth) with `next_from_seq` cursor |
| GET | `/api/telemetry/export?run_id&format=csv\|json` | attachment download |
| WS | `/ws/telemetry` | live stream (see below) |

### Detection
| Method | Path | Description |
|---|---|---|
| GET | `/api/detections/rules` | rule metadata, configuration and live per-instance state |
| PUT | `/api/detections/rules/{rule_id}` | `{"threshold"?, "debounce_s"?, "clear_s"?, "clear_ratio"?, "window_s"?, "severity"?, "enabled"?}` |
| GET | `/api/detections/active` | currently active alerts |
| GET | `/api/detections/events?run_id&status&rule_id&incident_id&limit&offset` | stored detection events |
| GET | `/api/evaluation` | latest evaluation result and run status |
| POST | `/api/evaluation/run` | `{"seeds": [int, ≤3]}` — background evaluation (one at a time, `409 busy`) |

### Incidents & reports
| Method | Path | Description |
|---|---|---|
| GET | `/api/incidents?run_id&status&classification&limit&offset` | incident list |
| GET | `/api/incidents/{id}` | detail with detections, notes, audit, scenario events (ground truth) and a telemetry window |
| POST | `/api/incidents/{id}/acknowledge` | acknowledge |
| POST | `/api/incidents/{id}/status` | `{"status": "open"\|"acknowledged"\|"investigating"\|"reviewed"\|"closed"}` |
| POST | `/api/incidents/{id}/notes` | `{"text": "1-2000 chars"}` |
| GET | `/api/incidents/{id}/evidence` | JSON evidence package (attachment) |
| GET | `/api/reports/{incident_id}?format=json\|md&download` | report generated from stored evidence |

### Scenarios & replay
| Method | Path | Description |
|---|---|---|
| GET | `/api/scenarios` | catalogue with parameters, timelines and ground-truth defaults |
| GET | `/api/scenarios/active` | active scenario and recent scenario events |
| POST | `/api/scenarios/{id}/start` | `{"params": {...}}` (validated against the scenario's parameter specs) |
| POST | `/api/scenarios/stop` | end the active scenario (reverts its changes) |
| GET | `/api/replay/runs` | recorded runs with counts |
| GET | `/api/replay/{run_id}?from_seq&limit≤20000` | columnar samples + detections + incidents + scenario events |
| GET | `/api/replay/{run_id}/sample/{seq}` | one full stored payload |

## WebSocket `/ws/telemetry`

Browser connections must come from an allowed origin (or the same origin); others are closed with 1008. Messages are
JSON objects with a `type`:

| type | data |
|---|---|
| `hello` | `{state, recent: Sample[≤300], active_alerts, recent_alerts, synthetic_data_only: true}` |
| `telemetry` | `Sample`: `{run_id, seq, t, ts, signals: {name: {v, u, t_src, q, valid, tag}}, truth, derived, validity, scenario_id}` |
| `alert` | `{change: raised\|updated\|cleared, data: Alert}` |
| `incident` | `{change: created\|updated, data: Incident}` |
| `scenario_event` | ground-truth event |
| `state` | simulation state (every 2 s and on change) |
| `reset` | `{run_id}` of the new run |

`truth` is simulator ground truth for the twin view; the detection engine never receives it.
