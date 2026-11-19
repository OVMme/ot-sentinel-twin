import { vi } from "vitest";
import type { Alert, Incident, Sample, ScenarioDef, SimState } from "../types/api";

// ------------------------------------------------------------------ synthetic fixtures
export function makeSample(seq: number, overrides: Partial<Record<string, number | boolean | string>> = {}): Sample {
  const t = seq * 0.5;
  const v: Record<string, number | boolean | string> = {
    "sensor.primary_level": 3.0,
    "sensor.secondary_level": 3.002,
    "tank.level_percent": 60,
    "tank.level_meters": 3.0,
    "flow.inlet_lps": 27.1,
    "flow.outlet_lps": 27.0,
    "pressure.line_bar": 2.5,
    "valve.inlet_command": 45,
    "valve.inlet_position": 45.1,
    "valve.outlet_command": 50,
    "valve.outlet_position": 50.2,
    "pump.command": true,
    "pump.running": true,
    "pump.power_kw": 10.6,
    "controller.mode": "auto",
    "controller.health": "ok",
    "controller.setpoint_percent": 60,
    ...overrides,
  };
  const signals = Object.fromEntries(
    Object.entries(v).map(([k, val]) => [k, { v: val, u: "", t_src: t, q: "good" as const, valid: true, tag: k.split(".")[0].toUpperCase() }]),
  );
  signals["sensor.primary_level"].tag = "LT-101";
  signals["sensor.secondary_level"].tag = "LT-102";
  return {
    run_id: "run-20260101-000000-abcd",
    seq,
    t,
    ts: new Date(Date.UTC(2026, 0, 1) + t * 1000).toISOString(),
    signals,
    truth: {
      level_m: 3.4, level_pct: 68, volume_m3: 40.8, qin_lps: 27, qout_lps: 27, overflow_lps: 0, inlet_pos_pct: 45,
      outlet_pos_pct: 50, pump_speed: 1, line_pressure_bar: 2.5, pump_power_kw: 10.6, dry_running: false,
      interlock_high: false, interlock_low: false, faults: [],
    },
    derived: { anomaly_score: 0.1, predicted_level_m: 3.0, disagreement_m: -0.002, mass_residual_m3: { "LT-101": 0.01, "LT-102": 0.0 } },
    validity: {},
    scenario_id: null,
  };
}

export const simState: SimState = {
  run_id: "run-20260101-000000-abcd",
  status: "running",
  speed: 1,
  max_speed: 10,
  sim_time_s: 100,
  seq: 200,
  epoch: "2026-01-01T00:00:00.000Z",
  sim_timestamp: "2026-01-01T00:01:40.000Z",
  mode: "auto",
  setpoint_pct: 60,
  manual_commands: { inlet_valve_pct: 50, outlet_valve_pct: 50, pump_on: true },
  interlocks: { high: false, low: false },
  controller_health: "ok",
  scenario: null,
  detection: { status: "running", samples_processed: 200, active_alerts: 0, rules_enabled: 8, rules_total: 8, anomaly_score: 0.1, warmup_complete: true },
  health: { loop_lag_ms: 0, ws_clients: 1, pending_samples: 0 },
  read_only: false,
  demo_mode: false,
  config: { seed: 1337, sample_interval_s: 0.5, tank_area_m2: 12, tank_height_m: 5 },
};

export const alert: Alert = {
  id: "DET-000001", rule_id: "PHYS-002", title: "Redundant Sensor Disagreement", category: "physics", severity: "high",
  asset_id: "TANK-001", instance_key: "LT-101/LT-102", signal: "sensor.primary_level", units: "m", threshold: 0.1,
  observed_value: 2.0, expected_value: 3.4, peak_score: 14, first_seen: "2026-01-01T00:01:00Z", raised_at: "2026-01-01T00:01:05Z",
  last_seen: "2026-01-01T00:01:40Z", cleared_at: null, first_seen_t: 60, raised_t: 65, last_seen_t: 100, cleared_t: null,
  status: "active", explanation: "LT-101 reports 2.000 m while redundant LT-102 reports 3.400 m.", evidence: [], metrics: {},
  incident_id: "INC-0001",
};

export const incident: Incident = {
  id: "INC-0001", title: "LT-101 reports values inconsistent with physics - suspected manipulation",
  classification: "suspected_manipulation", confidence: "medium", severity: "high", detection_state: "active", status: "open",
  acknowledged: false, first_seen_t: 60, first_seen: "2026-01-01T00:01:00Z", last_seen_t: 100, last_seen: "2026-01-01T00:01:40Z",
  rule_ids: ["PHYS-002"], assets: ["TANK-001"], summary: "LT-101 disagrees with LT-102.", expected_behavior: "Expected 3.4 m",
  observed_behavior: "Observed 2.0 m", classification_basis: ["LT-101 is isolated."], confidence_rationale: "Two checks agree.",
  alternatives: ["Calibration error"], recommended_steps: ["Verify level locally"], timeline: [],
};

export const scenarios: ScenarioDef[] = ["A", "B", "C"].map((code, i) => ({
  id: ["normal-operation", "stuck-inlet-valve", "sensor-manipulation"][i],
  code,
  title: ["Normal Operation", "Stuck Inlet Valve", "Sensor Value Manipulation"][i],
  category: ["normal", "equipment_fault", "suspected_manipulation"][i],
  summary: "summary",
  initial_conditions: "AUTO",
  trigger: "onset",
  changes: ["change"],
  expected_behavior: "expected",
  required_evidence: ["evidence"],
  reset_behavior: "reset",
  onset_delay_s: 5,
  expected_latency_s: 20,
  params: code === "C" ? [{ name: "offset_m", label: "Injected offset", kind: "number", default: -1.4, minimum: -2, maximum: 2, unit: "m", options: [] }] : [],
  timeline: [],
  ground_truth_defaults: {
    scenario_id: "x", code, category: "normal", params: {}, expected_rules: code === "C" ? ["PHYS-002"] : [],
    allowed_rules: [], expected_classification: null, expected_latency_s: 20,
  },
}));

// ------------------------------------------------------------------ fake transport
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }
  send() {}
  close() {
    this.onclose?.();
  }
  emit(msg: unknown) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  open() {
    this.onopen?.();
  }
}

export type Route = (method: string, url: string, body: unknown) => unknown | undefined;

export function installFetch(route: Route) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  const fn = vi.fn(async (input: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url: input, body });
    const res = route(method, input, body);
    if (res instanceof Error) throw res;
    if (res === undefined) return new Response(JSON.stringify({ error: { code: "not_found", message: "nope" } }), { status: 404 });
    return new Response(JSON.stringify(res), { status: 200 });
  });
  vi.stubGlobal("fetch", fn);
  return calls;
}

export function defaultRoutes(extra: Route = () => undefined): Route {
  return (method, url, body) => {
    const r = extra(method, url, body);
    if (r !== undefined) return r;
    if (method === "POST" && (url.startsWith("/api/scenarios") || url.startsWith("/api/simulation"))) return simState;
    if (url.startsWith("/api/telemetry/recent")) return { run_id: simState.run_id, samples: [] };
    if (url.startsWith("/api/simulation/state")) return simState;
    if (url.startsWith("/api/detections/rules")) return [];
    if (url.startsWith("/api/detections/events")) return { total: 0, limit: 25, offset: 0, items: [] };
    if (url.startsWith("/api/evaluation")) return { status: { running: false, started_at: null, error: null }, result: null };
    if (url.startsWith("/api/incidents/INC-0001")) return { ...incident, notes: [], detections: [alert], scenario_events: [], audit: [], telemetry: [] };
    if (url.startsWith("/api/incidents")) return { total: 0, limit: 100, offset: 0, items: [] };
    if (url.startsWith("/api/scenarios")) return scenarios;
    if (url.startsWith("/api/replay/runs")) return [];
    if (url.startsWith("/api/simulation/config")) return { active: { seed: 1337, tank: { area_m2: 12 } } };
    if (url.startsWith("/api/audit")) return { total: 0, limit: 50, offset: 0, items: [] };
    return undefined;
  };
}
