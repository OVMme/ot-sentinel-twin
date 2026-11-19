import { RotateCcw, Save, ScrollText, Settings2, UserRound } from "lucide-react";
import { useEffect, useState } from "react";
import { Badge, Button, Card, ErrorState, KV, Loading, PageHeader } from "../components/ui";
import { useAction } from "../hooks/useAction";
import { useApi } from "../hooks/useApi";
import { useLive } from "../hooks/useLive";
import { dateTimeOf } from "../lib/format";
import { api, ApiError, getAnalyst, setAnalyst } from "../services/api";
import type { AuditEvent, Page } from "../types/api";

type Cfg = Record<string, Record<string, number> | number>;

const FIELDS: { group: string; label: string; fields: [string, string, string][] }[] = [
  { group: "", label: "Run", fields: [["seed", "Random seed", ""], ["sample_interval_s", "Scan interval", "s"], ["physics_dt_s", "Physics step", "s"]] },
  { group: "tank", label: "Tank TK-001", fields: [["area_m2", "Cross-section A", "m²"], ["height_m", "Height (weir)", "m"], ["initial_level_m", "Initial level", "m"]] },
  { group: "inlet", label: "Inlet XV-101", fields: [["max_flow_lps", "Flow at 100 %", "L/s"]] },
  { group: "pump", label: "Pump P-101", fields: [["shutoff_bar", "Shut-off ΔP", "bar"], ["curve_k_bar_per_lps2", "Curve k", "bar/(L/s)²"], ["spin_tau_s", "Speed τ", "s"], ["efficiency", "Efficiency", ""]] },
  { group: "outlet", label: "Outlet XV-102", fields: [["valve_kv_lps_per_sqrt_bar", "Kv at 100 %", "L/s/√bar"], ["back_pressure_bar", "Back pressure", "bar"]] },
  { group: "valve", label: "Actuators", fields: [["travel_rate_pct_s", "Stroke speed", "%/s"]] },
  { group: "noise", label: "Instrument noise (σ)", fields: [["level_m", "Level", "m"], ["flow_lps", "Flow", "L/s"], ["pressure_bar", "Pressure", "bar"], ["position_pct", "Position", "%"]] },
  { group: "controller", label: "Controller LIC-101", fields: [["setpoint_pct", "Setpoint", "%"], ["kp", "Kp", ""], ["ki", "Ki", "1/s"], ["feedforward_gain", "Feed-forward", ""], ["demand_base_pct", "Demand base", "%"], ["demand_amplitude_pct", "Demand amplitude", "%"], ["demand_step_pct", "Demand steps", "%"]] },
];

export default function SettingsPage() {
  const { state, setSimState } = useLive();
  const cfg = useApi<{ active: Cfg }>("/api/simulation/config");
  const audit = useApi<Page<AuditEvent>>("/api/audit?limit=50", 5000);
  const [draft, setDraft] = useState<Cfg | null>(null);
  const [analyst, setAnalystName] = useState(getAnalyst());
  const { run, busy, error } = useAction();
  const [details, setDetails] = useState<string[]>([]);
  useEffect(() => {
    if (cfg.data) setDraft(structuredClone(cfg.data.active));
  }, [cfg.data]);
  const ro = Boolean(state?.read_only);

  const get = (g: string, f: string): string => {
    if (!draft) return "";
    const v = g ? (draft[g] as Record<string, number> | undefined)?.[f] : draft[f];
    return v == null ? "" : String(v);
  };
  const put = (g: string, f: string, v: string) => {
    if (!draft) return;
    const n = Number(v);
    const next = structuredClone(draft);
    if (g) next[g] = { ...((next[g] as Record<string, number> | undefined) ?? {}), [f]: n };
    else next[f] = n;
    setDraft(next);
  };
  const apply = () =>
    run("apply", async () => {
      setDetails([]);
      try {
        const r = await api.put<{ state: typeof state }>("/api/simulation/config", draft);
        if (r.state) setSimState(r.state);
        await cfg.reload();
      } catch (e) {
        if (e instanceof ApiError && Array.isArray(e.details)) {
          setDetails((e.details as { loc: (string | number)[]; msg: string }[]).map((d) => `${d.loc.join(".")}: ${d.msg}`));
        }
        throw e;
      }
    });

  return (
    <div className="space-y-4">
      <PageHeader title="Simulation configuration" subtitle="Plant model parameters. Applying validates the configuration and resets the simulation into a new recorded run with the documented initial state." />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <Card title="Plant & controller parameters" icon={Settings2}
          actions={<>
            <Button size="sm" icon={RotateCcw} onClick={() => cfg.data && setDraft(structuredClone(cfg.data.active))}>Discard</Button>
            <Button size="sm" variant="primary" icon={Save} disabled={ro || !draft} busy={busy === "apply"} onClick={apply}>Apply & reset</Button>
          </>}>
          {cfg.loading && !cfg.data ? <Loading /> : cfg.error ? <ErrorState error={cfg.error} onRetry={cfg.reload} /> : (
            <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
              {FIELDS.map((sec) => (
                <fieldset key={sec.label} className="rounded-lg border border-line p-3">
                  <legend className="label px-1">{sec.label}</legend>
                  <div className="space-y-2">
                    {sec.fields.map(([f, label, unit]) => (
                      <label key={f} className="flex items-center justify-between gap-2 text-xs text-muted">
                        <span>{label} {unit && <span className="text-faint">({unit})</span>}</span>
                        <input className="input num w-28 py-1 text-right text-xs" type="number" step="any" disabled={ro}
                          value={get(sec.group, f)} onChange={(e) => put(sec.group, f, e.target.value)} aria-label={`${sec.label} ${label}`} />
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
            </div>
          )}
          {error && <p role="alert" className="mt-3 text-xs text-crit">{error}</p>}
          {details.length > 0 && <ul className="mt-1 list-disc pl-5 text-xs text-crit">{details.map((d) => <li key={d}>{d}</li>)}</ul>}
          <p className="mt-3 text-xs text-muted">Detection thresholds are tuned per rule on the Detection Analytics page. The detector's process model is derived from these parameters at reset.</p>
        </Card>
        <div className="space-y-4">
          <Card title="Analyst identity" icon={UserRound} subtitle="Local name recorded in notes and the audit trail (no authentication in local mode)">
            <div className="flex gap-2">
              <input className="input flex-1" value={analyst} maxLength={40} onChange={(e) => setAnalystName(e.target.value)} aria-label="Analyst name" />
              <Button size="sm" onClick={() => setAnalyst(analyst.replace(/[^A-Za-z0-9 ._-]/g, "").slice(0, 40) || "local-analyst")}>Save</Button>
            </div>
          </Card>
          <Card title="Deployment">
            {state && <KV items={[
              ["Mode", state.demo_mode ? <Badge key="m" tone="replay">demo storyline</Badge> : "interactive"],
              ["State changes", state.read_only ? <Badge key="r">read-only</Badge> : "allowed (local)"],
              ["Max speed", `${state.max_speed}x`],
              ["Run", <span key="run" className="num text-xs">{state.run_id}</span>],
              ["Data", "100 % synthetic"],
            ]} />}
          </Card>
          <Card title="Audit trail" icon={ScrollText} subtitle="Local record of operator and analyst actions">
            {audit.error ? <ErrorState error={audit.error} onRetry={audit.reload} /> : !audit.data ? <Loading /> : (
              <ul className="max-h-80 divide-y divide-line overflow-auto text-xs">
                {audit.data.items.map((a) => (
                  <li key={a.id} className="py-1.5">
                    <div className="num text-[11px] text-faint">{dateTimeOf(a.ts)} · {a.actor}</div>
                    <div><span className="text-cyan">{a.action}</span> <span className="text-muted">{a.target}</span></div>
                  </li>
                ))}
                {audit.data.items.length === 0 && <li className="py-2 text-muted">No actions recorded yet.</li>}
              </ul>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
