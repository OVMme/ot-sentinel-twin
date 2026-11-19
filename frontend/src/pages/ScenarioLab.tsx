import { CheckCircle2, CircleDashed, FlaskConical, Pause, Play, RotateCcw, Square, Timer, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Badge, Button, Card, ErrorState, KV, Loading, PageHeader, Segmented, type Tone } from "../components/ui";
import { useAction } from "../hooks/useAction";
import { useApi } from "../hooks/useApi";
import { useLive } from "../hooks/useLive";
import { CLASSIFICATION_LABEL, cn, num, simClock, titleCase } from "../lib/format";
import { api } from "../services/api";
import type { ScenarioDef, SimState } from "../types/api";

const CATEGORY_TONE: Record<string, Tone> = {
  normal: "ok",
  equipment_fault: "warn",
  physical_anomaly: "cyan",
  data_quality: "neutral",
  suspected_manipulation: "crit",
};

function Controls() {
  const { state, setSimState } = useLive();
  const { run, busy, error } = useAction();
  const [confirmReset, setConfirmReset] = useState(false);
  if (!state) return null;
  const ro = state.read_only;
  const post = (k: string, path: string, body?: unknown) => run(k, async () => setSimState(await api.post<SimState>(path, body)));
  const speeds = [1, 2, 5, 10].filter((s) => s <= state.max_speed).map((s) => ({ value: s, label: `${s}x` }));
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3">
        {state.status === "running" ? (
          <Button icon={Pause} disabled={ro} busy={busy === "pause"} onClick={() => post("pause", "/api/simulation/pause")}>Pause</Button>
        ) : (
          <Button variant="primary" icon={Play} disabled={ro} busy={busy === "start"} onClick={() => post("start", "/api/simulation/start")}>Start</Button>
        )}
        {confirmReset ? (
          <div className="flex items-center gap-2 rounded-lg border border-warn/30 bg-warn/10 px-2 py-1 text-xs text-warn">
            Reset starts a new run from the documented initial state.
            <Button size="sm" variant="danger" busy={busy === "reset"} onClick={() => { setConfirmReset(false); void post("reset", "/api/simulation/reset", {}); }}>Confirm reset</Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmReset(false)}>Cancel</Button>
          </div>
        ) : (
          <Button icon={RotateCcw} disabled={ro} onClick={() => setConfirmReset(true)}>Reset</Button>
        )}
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted">Speed</span>
          <Segmented label="Simulation speed" value={state.speed} disabled={ro} options={speeds}
            onChange={(s) => post("speed", "/api/simulation/speed", { speed: s })} />
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-4 text-xs text-muted">
          <span>Status <Badge tone={state.status === "running" ? "ok" : "warn"}>{state.status}</Badge></span>
          <span>Sim time <span className="num text-text">T+{simClock(state.sim_time_s)}</span></span>
          <span>Seed <span className="num text-text">{state.config.seed}</span></span>
          <span className="num hidden text-faint lg:inline">{state.run_id}</span>
        </div>
      </div>
      {ro && <p className="mt-2 text-xs text-warn">Read-only deployment: controls are disabled.</p>}
      {error && <p role="alert" className="mt-2 text-xs text-crit">{error}</p>}
    </Card>
  );
}

function ActiveScenario({ defs }: { defs: ScenarioDef[] }) {
  const { state, alerts, setSimState } = useLive();
  const { run, busy, error } = useAction();
  const sc = state?.scenario;
  if (!state || !sc) return null;
  const def = defs.find((d) => d.id === sc.scenario_id);
  const gt = sc.ground_truth;
  const since = alerts.filter((a) => a.raised_t >= sc.onset_t - 1e-6);
  const firstBy = (rule: string) => since.filter((a) => a.rule_id === rule).sort((a, b) => a.raised_t - b.raised_t)[0];
  const others = [...new Set(since.map((a) => a.rule_id))].filter((r) => !gt.expected_rules.includes(r));
  const elapsedSinceOnset = state.sim_time_s - sc.onset_t;
  return (
    <Card
      title={<span className="flex items-center gap-2"><Badge tone="warn">{sc.code}</Badge> Active scenario: {sc.title}</span>}
      subtitle="Ground truth below comes from the scenario lab and is never passed to the detection engine."
      actions={<Button variant="danger" icon={Square} disabled={state.read_only} busy={busy === "stop"}
        onClick={() => run("stop", async () => setSimState(await api.post<SimState>("/api/scenarios/stop")))}>End scenario</Button>}
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <div>
          <div className="label mb-2">Progress</div>
          <KV items={[
            ["Phase", <Badge key="p" tone={sc.phase === "active" ? "crit" : "warn"}>{sc.phase}</Badge>],
            ["Elapsed", <span key="e" className="num">{num(sc.elapsed_s, 0)} s</span>],
            ["Fault onset", <span key="o" className="num">T+{simClock(sc.onset_t)}</span>],
            ["Params", <span key="pa" className="num text-xs">{Object.entries(sc.params).map(([k, v]) => `${k}=${v}`).join(", ") || "defaults"}</span>],
          ]} />
          <ul className="mt-3 space-y-1.5 text-xs">
            {sc.next_actions.map((a) => (
              <li key={a.description} className="flex items-center gap-2">
                {a.done ? <CheckCircle2 className="size-3.5 text-ok" /> : <CircleDashed className="size-3.5 text-muted" />}
                <span className="num text-faint">+{a.offset_s}s</span> {a.description}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="label mb-2">Expected vs actual detection</div>
          {gt.expected_rules.length === 0 ? (
            <p className="text-[13px]">
              Normal operation: no alerts expected.{" "}
              {since.length ? <span className="text-crit">{since.length} alert(s) raised — counted as false positives.</span> : <span className="text-ok">None raised so far.</span>}
            </p>
          ) : (
            <ul className="space-y-2">
              {gt.expected_rules.map((r) => {
                const hit = firstBy(r);
                const lat = hit ? hit.raised_t - sc.onset_t : null;
                return (
                  <li key={r} className="flex items-center gap-2 text-[13px]">
                    {hit ? <CheckCircle2 className="size-4 text-ok" /> : sc.phase === "active" && gt.expected_latency_s && elapsedSinceOnset > gt.expected_latency_s * 3 ? <XCircle className="size-4 text-crit" /> : <Timer className="size-4 text-warn" />}
                    <Badge tone="cyan">{r}</Badge>
                    {hit ? <span className="text-ok">detected after <span className="num">{num(lat, 1)} s</span></span> : <span className="text-muted">waiting…</span>}
                  </li>
                );
              })}
            </ul>
          )}
          {gt.expected_latency_s != null && <p className="mt-2 text-xs text-muted">Design target: first expected detection within {gt.expected_latency_s} s of onset.</p>}
          {others.length > 0 && (
            <p className="mt-2 text-xs text-muted">
              Other rules fired:{" "}
              {others.map((r) => <Badge key={r} tone={gt.allowed_rules.includes(r) ? "neutral" : "crit"} className="mr-1">{r}{gt.allowed_rules.includes(r) ? " (allowed)" : " (unexpected)"}</Badge>)}
            </p>
          )}
        </div>
        <div>
          <div className="label mb-2">Ground truth</div>
          <KV items={[
            ["Category", <Badge key="c" tone={CATEGORY_TONE[gt.category] ?? "neutral"}>{titleCase(gt.category)}</Badge>],
            ["Expected class", gt.expected_classification ? CLASSIFICATION_LABEL[gt.expected_classification] : "—"],
            ["Allowed rules", gt.allowed_rules.join(", ") || "—"],
          ]} />
          {def && <p className="mt-3 text-xs text-muted">{def.expected_behavior}</p>}
        </div>
      </div>
      {error && <p role="alert" className="mt-2 text-xs text-crit">{error}</p>}
    </Card>
  );
}

function ScenarioDetail({ def }: { def: ScenarioDef }) {
  const { state, setSimState } = useLive();
  const { run, busy, error } = useAction();
  const [params, setParams] = useState<Record<string, string>>({});
  useEffect(() => {
    setParams(Object.fromEntries(def.params.map((p) => [p.name, String(p.default)])));
  }, [def]);
  const ro = Boolean(state?.read_only);
  const start = () =>
    run("start", async () => {
      const body: Record<string, number | string> = {};
      for (const p of def.params) body[p.name] = p.kind === "number" ? Number(params[p.name]) : params[p.name];
      setSimState(await api.post<SimState>(`/api/scenarios/${def.id}/start`, { params: body }));
    });
  const gt = def.ground_truth_defaults;
  return (
    <Card
      title={<span className="flex items-center gap-2"><Badge tone={CATEGORY_TONE[def.category] ?? "neutral"}>{def.code}</Badge>{def.title}</span>}
      subtitle={def.summary}
      actions={<Button variant="primary" icon={FlaskConical} disabled={ro || state?.status !== "running"} busy={busy === "start"} onClick={start}>
        {state?.scenario ? "Replace active scenario" : "Start scenario"}
      </Button>}
    >
      {state?.status !== "running" && <p className="mb-3 text-xs text-warn">Start the simulation to run a scenario.</p>}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-3 text-[13px]">
          <KV items={[
            ["Initial conditions", def.initial_conditions],
            ["Trigger", def.trigger],
            ["Onset delay", `${def.onset_delay_s} s after start`],
            ["Reset behaviour", def.reset_behavior],
          ]} />
          <div>
            <div className="label mb-1">Exact changes to the simulation</div>
            <ul className="list-disc space-y-1 pl-5 text-muted">{def.changes.map((c) => <li key={c}>{c}</li>)}</ul>
          </div>
          {def.timeline.length > 0 && (
            <div>
              <div className="label mb-1">Timeline</div>
              <ul className="space-y-0.5 text-xs text-muted">{def.timeline.map((t) => <li key={t.description}><span className="num text-faint">onset +{t.offset_s}s</span> · {t.description}</li>)}</ul>
            </div>
          )}
        </div>
        <div className="space-y-3 text-[13px]">
          <div>
            <div className="label mb-1">Expected behaviour</div>
            <p className="text-muted">{def.expected_behavior}</p>
          </div>
          <KV items={[
            ["Expected detectors", <span key="r" className="flex flex-wrap gap-1">{gt.expected_rules.length ? gt.expected_rules.map((r) => <Badge key={r} tone="cyan">{r}</Badge>) : <span className="text-muted">none (no alerts)</span>}</span>],
            ["May also fire", gt.allowed_rules.join(", ") || "—"],
            ["Expected class", gt.expected_classification ? CLASSIFICATION_LABEL[gt.expected_classification] : "—"],
            ["Target latency", gt.expected_latency_s != null ? `≤ ${gt.expected_latency_s} s` : "—"],
          ]} />
          <div>
            <div className="label mb-1">Required evidence</div>
            <ul className="list-disc space-y-0.5 pl-5 text-xs text-muted">{def.required_evidence.map((e) => <li key={e}>{e}</li>)}</ul>
          </div>
          {def.params.length > 0 && (
            <div className="rounded-lg border border-line p-3">
              <div className="label mb-2">Parameters</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {def.params.map((p) => (
                  <label key={p.name} className="text-xs text-muted">
                    {p.label} {p.unit && <span className="text-faint">({p.unit})</span>}
                    {p.kind === "select" ? (
                      <select className="input mt-1 w-full" value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
                        {p.options.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                    ) : (
                      <input className="input num mt-1 w-full" type="number" step="any" min={p.minimum ?? undefined} max={p.maximum ?? undefined}
                        value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
                    )}
                  </label>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
      {error && <p role="alert" className="mt-3 text-xs text-crit">{error}</p>}
    </Card>
  );
}

export default function ScenarioLab() {
  const defs = useApi<ScenarioDef[]>("/api/scenarios");
  const { state } = useLive();
  const [sel, setSel] = useState<string | null>(null);
  const list = useMemo(() => defs.data ?? [], [defs.data]);
  const selected = list.find((d) => d.id === (sel ?? state?.scenario?.scenario_id ?? list[2]?.id)) ?? list[0];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Simulation & Scenario Lab"
        subtitle="Inject synthetic faults and manipulations into the simulated plant only. The detection engine sees nothing but the resulting telemetry; compare what it finds with the ground truth."
      />
      <Controls />
      {defs.data && <ActiveScenario defs={list} />}
      {defs.loading && !defs.data ? <Loading /> : defs.error ? <ErrorState error={defs.error} onRetry={defs.reload} /> : (
        <>
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Scenarios">
            {list.map((d) => {
              const active = state?.scenario?.scenario_id === d.id;
              const isSel = selected?.id === d.id;
              return (
                <li key={d.id} className="flex">
                <button
                  type="button"
                  onClick={() => setSel(d.id)}
                  aria-pressed={isSel}
                  className={cn(
                    "panel w-full p-3.5 text-left transition-colors hover:border-line-strong",
                    isSel && "border-cyan/50 ring-1 ring-cyan/30",
                    active && "border-warn/60",
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="num flex size-7 items-center justify-center rounded-md bg-raised text-sm font-bold text-cyan ring-1 ring-line-strong">{d.code}</span>
                    <span className="text-[13px] font-semibold">{d.title}</span>
                    {active && <Badge tone="warn" className="ml-auto">ACTIVE</Badge>}
                  </div>
                  <p className="mt-2 line-clamp-2 text-xs text-muted">{d.summary}</p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    <Badge tone={CATEGORY_TONE[d.category] ?? "neutral"}>{titleCase(d.category)}</Badge>
                    {d.ground_truth_defaults.expected_rules.map((r) => <Badge key={r}>{r}</Badge>)}
                  </div>
                </button>
                </li>
              );
            })}
          </ul>
          {selected && <ScenarioDetail def={selected} />}
        </>
      )}
    </div>
  );
}
