import type { ReplayColumns, Sample } from "../types/api";

/** Everything the plant diagram needs, from either a live sample or a recorded replay row. */
export interface PlantView {
  levelPrimaryM: number | null;
  levelSecondaryM: number | null;
  trueLevelM: number | null;
  tankHeightM: number;
  setpointPct: number | null;
  inletCmd: number | null;
  inletPos: number | null;
  outletCmd: number | null;
  outletPos: number | null;
  pumpCmd: boolean | null;
  pumpRunning: boolean | null;
  pumpKw: number | null;
  flowIn: number | null;
  flowOut: number | null;
  pressure: number | null;
  mode: string | null;
  health: string | null;
  quality: Record<string, string>;
  trueFlowIn: number | null;
  trueFlowOut: number | null;
  overflow: number | null;
  interlockHigh: boolean;
  interlockLow: boolean;
}

const n = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const b = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);

export function viewFromSample(s: Sample | null | undefined, tankHeightM = 5): PlantView | null {
  if (!s) return null;
  const g = (name: string) => s.signals[name]?.v;
  const quality: Record<string, string> = {};
  for (const [name, r] of Object.entries(s.signals)) {
    const stale = s.t - r.t_src > 2.5;
    quality[r.tag || name] = stale ? "stale" : r.q;
  }
  return {
    levelPrimaryM: n(g("sensor.primary_level")),
    levelSecondaryM: n(g("sensor.secondary_level")),
    trueLevelM: n(s.truth?.level_m),
    tankHeightM,
    setpointPct: n(g("controller.setpoint_percent")),
    inletCmd: n(g("valve.inlet_command")),
    inletPos: n(g("valve.inlet_position")),
    outletCmd: n(g("valve.outlet_command")),
    outletPos: n(g("valve.outlet_position")),
    pumpCmd: b(g("pump.command")),
    pumpRunning: b(g("pump.running")),
    pumpKw: n(g("pump.power_kw")),
    flowIn: n(g("flow.inlet_lps")),
    flowOut: n(g("flow.outlet_lps")),
    pressure: n(g("pressure.line_bar")),
    mode: (g("controller.mode") as string) ?? null,
    health: (g("controller.health") as string) ?? null,
    quality,
    trueFlowIn: n(s.truth?.qin_lps),
    trueFlowOut: n(s.truth?.qout_lps),
    overflow: n(s.truth?.overflow_lps),
    interlockHigh: Boolean(s.truth?.interlock_high),
    interlockLow: Boolean(s.truth?.interlock_low),
  };
}

export function viewFromReplay(c: ReplayColumns, i: number, tankHeightM = 5): PlantView | null {
  if (i < 0 || i >= c.seq.length) return null;
  return {
    levelPrimaryM: c.lt101[i],
    levelSecondaryM: c.lt102[i],
    trueLevelM: c.true_level[i],
    tankHeightM,
    setpointPct: c.setpoint[i],
    inletCmd: c.inlet_cmd[i],
    inletPos: c.zt101[i],
    outletCmd: c.outlet_cmd[i],
    outletPos: c.zt102[i],
    pumpCmd: c.pump_cmd[i],
    pumpRunning: c.pump_running[i],
    pumpKw: c.pump_kw[i],
    flowIn: c.ft101[i],
    flowOut: c.ft102[i],
    pressure: c.pt101[i],
    mode: c.mode[i],
    health: null,
    quality: {},
    trueFlowIn: null,
    trueFlowOut: null,
    overflow: null,
    interlockHigh: false,
    interlockLow: false,
  };
}

/** Map active alerts to diagram anchors (asset ids or instance keys). */
export function alertAnchors(alerts: { asset_id: string; instance_key: string; rule_id: string; severity: string }[]) {
  const out: Record<string, { rules: string[]; severity: string }> = {};
  const add = (k: string, rule: string, sev: string) => {
    const cur = out[k] ?? { rules: [], severity: "low" };
    if (!cur.rules.includes(rule)) cur.rules.push(rule);
    if (sev === "high" || sev === "critical" || cur.severity === "low") cur.severity = sev;
    out[k] = cur;
  };
  for (const a of alerts) {
    add(a.asset_id, a.rule_id, a.severity);
    for (const part of a.instance_key.split("/")) add(part, a.rule_id, a.severity);
  }
  return out;
}
