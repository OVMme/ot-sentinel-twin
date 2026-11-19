import { Power, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { PlantDiagram } from "../components/PlantDiagram";
import { Badge, Button, Card, Loading, PageHeader, Segmented } from "../components/ui";
import { useAction } from "../hooks/useAction";
import { useLive } from "../hooks/useLive";
import { cn, num } from "../lib/format";
import { alertAnchors, viewFromSample } from "../lib/plant";
import { api } from "../services/api";
import type { SimState } from "../types/api";

const SIGNAL_ORDER = [
  "sensor.primary_level",
  "sensor.secondary_level",
  "tank.level_percent",
  "flow.inlet_lps",
  "flow.outlet_lps",
  "pressure.line_bar",
  "valve.inlet_command",
  "valve.inlet_position",
  "valve.outlet_command",
  "valve.outlet_position",
  "pump.command",
  "pump.running",
  "pump.power_kw",
  "controller.mode",
  "controller.health",
  "controller.setpoint_percent",
];

function Slider({ label, value, onChange, disabled, id }: {
  label: string; value: number; onChange: (v: number) => void; disabled?: boolean; id: string;
}) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-xs">
        <label htmlFor={id} className="text-muted">{label}</label>
        <span className="num text-text">{value.toFixed(0)} %</span>
      </div>
      <input
        id={id}
        type="range"
        min={0}
        max={100}
        step={1}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-cyan disabled:opacity-40"
      />
    </div>
  );
}

export default function PlantPage() {
  const { latest, state, activeAlerts, setSimState } = useLive();
  const [variant, setVariant] = useState<"twin" | "hmi">("twin");
  const { run, busy, error } = useAction();
  const h = state?.config.tank_height_m ?? 5;
  const view = viewFromSample(latest, h);
  const anchors = useMemo(() => alertAnchors(activeAlerts), [activeAlerts]);

  const [sp, setSp] = useState(60);
  const [inlet, setInlet] = useState(50);
  const [outlet, setOutlet] = useState(50);
  const [pumpOn, setPumpOn] = useState(true);
  const manual = state?.mode === "manual";
  const ro = Boolean(state?.read_only);

  // keep operator inputs in sync with the controller when they are not being edited
  useEffect(() => {
    if (!state) return;
    setSp(Math.round(state.setpoint_pct));
    setInlet(Math.round(state.manual_commands.inlet_valve_pct));
    setOutlet(Math.round(state.manual_commands.outlet_valve_pct));
    setPumpOn(state.manual_commands.pump_on);
  }, [state?.run_id, state?.mode]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!state) return <Loading label="Connecting to the simulator" />;
  const post = (key: string, path: string, body: unknown) =>
    run(key, async () => setSimState(await api.post<SimState>(path, body)));

  return (
    <div>
      <PageHeader
        title="Industrial digital twin"
        subtitle="Animated synthetic plant. Twin view overlays the simulator's physical truth (magenta) on what the instruments report; HMI view shows only reported values, as an operator would see them."
        actions={
          <Segmented
            label="Diagram view"
            value={variant}
            onChange={setVariant}
            options={[{ value: "twin", label: "Twin view (truth + sensors)" }, { value: "hmi", label: "HMI view (sensors only)" }]}
          />
        }
      />
      <div className="grid items-start gap-4 2xl:grid-cols-[1fr_420px]">
        <Card bodyClassName="pt-4">
          {view ? <PlantDiagram view={view} anchors={anchors} variant={variant} className="w-full" /> : <Loading label="Waiting for telemetry" />}
        </Card>
        <div className="grid content-start gap-4 md:grid-cols-2 2xl:grid-cols-1">
          <Card title="Operator console" icon={SlidersHorizontal} subtitle="Synthetic operator actions on the simulated controller only">
            {ro && <p className="mb-3 text-xs text-warn">Read-only deployment: operator actions are disabled.</p>}
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted">Control mode</span>
                <Segmented
                  label="Control mode"
                  value={state.mode}
                  disabled={ro || busy != null}
                  onChange={(m) => post("mode", "/api/simulation/mode", { mode: m })}
                  options={[{ value: "auto", label: "AUTO" }, { value: "manual", label: "MANUAL" }]}
                />
              </div>
              <div>
                <Slider id="sp" label="Level setpoint (LIC-101.SP)" value={sp} onChange={setSp} disabled={ro} />
                <Button size="sm" className="mt-2" disabled={ro || sp < 5 || sp > 95} busy={busy === "sp"}
                  onClick={() => post("sp", "/api/simulation/operator", { setpoint_pct: Math.min(95, Math.max(5, sp)) })}>
                  Apply setpoint
                </Button>
              </div>
              <div className={cn("space-y-3 rounded-lg border border-line p-3", !manual && "opacity-60")}>
                <div className="flex items-center justify-between">
                  <span className="label">Manual commands</span>
                  {!manual && <Badge>switch to MANUAL</Badge>}
                </div>
                <Slider id="inlet" label="XV-101 inlet valve command" value={inlet} onChange={setInlet} disabled={ro || !manual} />
                <Slider id="outlet" label="XV-102 outlet valve command" value={outlet} onChange={setOutlet} disabled={ro || !manual} />
                <div className="flex items-center justify-between">
                  <span className="text-xs text-muted">P-101 pump command</span>
                  <Button size="sm" icon={Power} variant={pumpOn ? "secondary" : "danger"} disabled={ro || !manual} onClick={() => setPumpOn(!pumpOn)}>
                    {pumpOn ? "ON" : "OFF"}
                  </Button>
                </div>
                <Button size="sm" variant="primary" disabled={ro || !manual} busy={busy === "manual"}
                  onClick={() => post("manual", "/api/simulation/operator", { inlet_valve_pct: inlet, outlet_valve_pct: outlet, pump_on: pumpOn })}>
                  Send commands
                </Button>
              </div>
              <div className="flex flex-wrap gap-2 text-xs">
                <Badge tone={state.interlocks.high ? "crit" : "neutral"}>LSHH high interlock {state.interlocks.high ? "TRIPPED" : "normal"}</Badge>
                <Badge tone={state.interlocks.low ? "crit" : "neutral"}>LSLL pump trip {state.interlocks.low ? "TRIPPED" : "normal"}</Badge>
              </div>
              {error && <p role="alert" className="text-xs text-crit">{error}</p>}
            </div>
          </Card>
          <Card title="Instrument readings" subtitle="Value, unit, quality and source-timestamp age per signal">
            {latest ? (
              <div className="max-h-[420px] overflow-auto">
                <table className="w-full text-left text-xs">
                  <thead className="sticky top-0 bg-panel text-muted">
                    <tr>
                      <th className="py-1.5 font-medium">Tag / signal</th>
                      <th className="py-1.5 text-right font-medium">Value</th>
                      <th className="py-1.5 pl-2 text-right font-medium">Age</th>
                      <th className="py-1.5 pl-2 text-right font-medium">Quality</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {SIGNAL_ORDER.filter((n) => latest.signals[n]).map((n) => {
                      const r = latest.signals[n];
                      const age = latest.t - r.t_src;
                      const stale = age > 2.5;
                      const v = typeof r.v === "number" ? num(r.v, r.u === "bar" ? 3 : r.u === "m" ? 3 : 1) : String(r.v);
                      return (
                        <tr key={n}>
                          <td className="py-1.5 pr-2">
                            <div className="font-mono text-[11px] font-semibold text-text">{r.tag}</div>
                            <div className="font-mono text-[10px] text-faint">{n}</div>
                          </td>
                          <td className="num whitespace-nowrap py-1.5 text-right">{v} <span className="text-faint">{r.u === "bool" || r.u === "enum" ? "" : r.u}</span></td>
                          <td className={cn("num whitespace-nowrap py-1.5 pl-2 text-right", stale ? "text-warn" : "text-muted")}>{age.toFixed(1)} s</td>
                          <td className="py-1.5 pl-2 text-right">
                            <Badge tone={stale ? "warn" : r.q === "good" ? "ok" : r.q === "uncertain" ? "warn" : "crit"}>{stale ? "stale" : r.q}</Badge>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <Loading label="Waiting for telemetry" />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
