import { ChevronDown, ChevronRight, FlaskConical, ListChecks, Radar } from "lucide-react";
import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, Meter, PageHeader, SeverityBadge, Stat } from "../components/ui";
import { useAction } from "../hooks/useAction";
import { useApi } from "../hooks/useApi";
import { useLive } from "../hooks/useLive";
import { CLASSIFICATION_LABEL, cn, num, simClock } from "../lib/format";
import { api } from "../services/api";
import type { Alert, EvaluationResponse, Page, RuleStatus } from "../types/api";

function RuleRow({ rule, readOnly, onSaved }: { rule: RuleStatus; readOnly: boolean; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [thr, setThr] = useState(String(rule.config.threshold));
  const { run, busy, error } = useAction();
  useEffect(() => setThr(String(rule.config.threshold)), [rule.config.threshold]);
  const save = (changes: Record<string, unknown>) =>
    run("save", async () => {
      await api.put(`/api/detections/rules/${rule.rule_id}`, changes);
      onSaved();
    });
  const active = rule.instances.filter((i) => i.state === "active").length;
  const pending = rule.instances.filter((i) => i.state === "pending").length;
  return (
    <Fragment>
      <tr className="align-top">
        <td className="py-2.5 pr-2">
          <button type="button" onClick={() => setOpen(!open)} aria-expanded={open} className="flex items-center gap-1.5 text-left">
            {open ? <ChevronDown className="size-3.5 text-muted" /> : <ChevronRight className="size-3.5 text-muted" />}
            <Badge tone={rule.category === "data_quality" ? "neutral" : "cyan"}>{rule.rule_id}</Badge>
          </button>
        </td>
        <td className="py-2.5 pr-2 text-[13px] font-medium">{rule.title}</td>
        <td className="py-2.5 pr-2"><SeverityBadge severity={rule.config.severity} /></td>
        <td className="py-2.5 pr-2">
          <div className="flex items-center gap-1.5">
            <input
              aria-label={`${rule.rule_id} threshold`}
              className="input num w-20 py-1 text-xs"
              value={thr}
              disabled={readOnly}
              onChange={(e) => setThr(e.target.value)}
            />
            <span className="text-xs text-muted">{rule.config.units}</span>
            {thr !== String(rule.config.threshold) && (
              <Button size="sm" busy={busy === "save"} onClick={() => save({ threshold: Number(thr) })} disabled={!(Number(thr) > 0)}>
                Save
              </Button>
            )}
          </div>
          {error && <p className="mt-1 text-[11px] text-crit">{error}</p>}
        </td>
        <td className="num py-2.5 pr-2 text-xs text-muted">{rule.config.debounce_s}s / {rule.config.clear_s}s</td>
        <td className="py-2.5 pr-2">
          <div className="flex flex-wrap gap-1">
            {rule.instances.map((i) => (
              <span
                key={i.key}
                title={`${i.key}: ${i.state}${i.evaluable ? ` · score ${num(i.score, 2)}` : " · not evaluable"}`}
                className={cn(
                  "num rounded px-1.5 py-0.5 text-[10px] ring-1 ring-inset",
                  i.state === "active" ? "bg-crit/15 text-crit ring-crit/30"
                    : i.state === "pending" ? "bg-warn/15 text-warn ring-warn/30"
                    : !i.evaluable ? "bg-white/5 text-faint ring-white/10"
                    : "bg-ok/10 text-ok ring-ok/20",
                )}
              >
                {i.key}
              </span>
            ))}
          </div>
          <div className="mt-1.5 w-32">
            <Meter value={Math.max(0, ...rule.instances.map((i) => i.score ?? 0))} max={1} />
          </div>
        </td>
        <td className="py-2.5 text-right">
          <Button size="sm" variant={rule.config.enabled ? "ghost" : "danger"} disabled={readOnly} onClick={() => save({ enabled: !rule.config.enabled })}>
            {rule.config.enabled ? (active ? `${active} active` : pending ? `${pending} pending` : "enabled") : "disabled"}
          </Button>
        </td>
      </tr>
      {open && (
        <tr>
          <td colSpan={7} className="pb-3">
            <div className="rounded-lg border border-line bg-bg/60 p-3 text-xs leading-relaxed">
              <p className="text-text">{rule.description}</p>
              <p className="mt-2 text-muted"><span className="label mr-2">Method</span>{rule.methodology}</p>
              <p className="num mt-2 text-faint">
                window {rule.config.window_s}s · hysteresis clear below {rule.config.clear_ratio}× threshold
              </p>
            </div>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function Evaluation({ readOnly }: { readOnly: boolean }) {
  const ev = useApi<EvaluationResponse>("/api/evaluation");
  const { run, busy, error } = useAction();
  const running = ev.data?.status.running;
  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => void ev.reload(), 2000);
    return () => window.clearInterval(id);
  }, [running]); // eslint-disable-line react-hooks/exhaustive-deps
  const r = ev.data?.result;
  const s = r?.summary;
  return (
    <Card
      title="Detection performance evaluation"
      icon={ListChecks}
      subtitle={r ? `Executed ${r.summary.runs} labelled runs · seeds ${r.seeds.join(", ")} · generated ${r.generated_at}` : "Labelled scenario runs scored against ground truth"}
      actions={
        <Button size="sm" icon={FlaskConical} busy={running || busy === "eval"} disabled={readOnly}
          onClick={() => run("eval", async () => { await api.post("/api/evaluation/run", { seeds: [1337] }); await ev.reload(); })}>
          {running ? "Evaluating…" : "Re-run (1 seed)"}
        </Button>
      }
    >
      {ev.loading && !ev.data ? <Loading /> : ev.error ? <ErrorState error={ev.error} onRetry={ev.reload} /> : !s ? (
        <EmptyState icon={ListChecks} title="No evaluation yet">Run the evaluation to score every scenario.</EmptyState>
      ) : (
        <div className="space-y-4">
          <p className="text-xs text-muted">{r.data_notice}</p>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
            <Stat label="Precision" value={num(s.precision, 3)} tone="cyan" />
            <Stat label="Recall" value={num(s.recall, 3)} tone="cyan" />
            <Stat label="F1" value={num(s.f1, 3)} tone="cyan" />
            <Stat label="Mean latency" value={num(s.latency_mean_s, 1)} unit="s" tone="neutral" sub={`max ${num(s.latency_max_s, 1)} s`} />
            <Stat label="TP / FN" value={`${s.true_positives}/${s.false_negatives}`} tone="neutral" />
            <Stat label="FP alerts" value={s.false_positive_alerts} tone={s.false_positive_alerts ? "warn" : "ok"} sub={`${s.normal_operation_false_positives} in ${num(s.normal_operation_hours, 1)} h normal op.`} />
            <Stat label="Classification" value={s.classification_accuracy == null ? "—" : `${Math.round(s.classification_accuracy * 100)}%`} tone="neutral" sub="incident class accuracy" />
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px] text-left text-xs">
              <thead className="text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 font-medium">Scenario</th>
                  <th className="py-2 font-medium">Expected detection</th>
                  <th className="py-2 font-medium">Actual (rules fired)</th>
                  <th className="py-2 font-medium">Latency mean / max</th>
                  <th className="py-2 font-medium">Classification</th>
                  <th className="py-2 font-medium">Detected</th>
                  <th className="py-2 font-medium">FP</th>
                  <th className="py-2 text-right font-medium">Result</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {s.coverage_matrix.map((m) => (
                  <tr key={m.scenario}>
                    <td className="py-2 pr-2 font-medium text-text">{m.scenario}</td>
                    <td className="num py-2 pr-2">{m.expected_rules.join(", ") || "no alerts"}</td>
                    <td className="num py-2 pr-2 text-muted">{m.rules_fired.join(", ") || "none"}</td>
                    <td className="num py-2 pr-2">{m.latency_mean_s == null ? "—" : `${m.latency_mean_s} s / ${m.latency_max_s} s`}</td>
                    <td className="py-2 pr-2 text-muted">
                      {m.classification_expected ? `${CLASSIFICATION_LABEL[m.classification_expected]} → ${m.classifications.map((c) => CLASSIFICATION_LABEL[c] ?? c).join(", ") || "—"}` : "—"}
                    </td>
                    <td className="num py-2 pr-2">{m.anomalous ? `${m.detected}/${m.runs}` : "n/a"}</td>
                    <td className="num py-2 pr-2">{m.false_positives}</td>
                    <td className="py-2 text-right"><Badge tone={m.result === "PASS" ? "ok" : "crit"}>{m.result}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {r.robustness && (
            <div>
              <h3 className="label mb-1">Robustness — plant / model mismatch sweep</h3>
              <p className="mb-2 text-xs text-muted">{r.robustness.description}</p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] text-left text-xs">
                  <thead className="text-muted">
                    <tr className="border-b border-line">
                      <th className="py-2 font-medium">Severity</th>
                      <th className="py-2 font-medium">Precision</th>
                      <th className="py-2 font-medium">Recall</th>
                      <th className="py-2 font-medium">F1</th>
                      <th className="py-2 font-medium">FP (normal op.)</th>
                      <th className="py-2 font-medium">Rules with FPs</th>
                      <th className="py-2 font-medium">Missed</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {r.robustness.sweep.map((x) => (
                      <tr key={x.severity}>
                        <td className="num py-2">{x.severity}×</td>
                        <td className="num py-2">{num(x.precision, 3)}</td>
                        <td className="num py-2">{num(x.recall, 3)}</td>
                        <td className={cn("num py-2", x.f1 < 0.9 ? "text-warn" : "text-ok")}>{num(x.f1, 3)}</td>
                        <td className="num py-2">{x.false_positive_alerts} ({x.normal_operation_false_positives})</td>
                        <td className="num py-2 text-muted">{x.false_positive_rules.join(", ") || "—"}</td>
                        <td className="py-2 text-muted">{x.missed.join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          <details className="text-xs text-muted">
            <summary className="cursor-pointer text-text">Scoring definitions</summary>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              {Object.entries(r.definitions).map(([k, v]) => (
                <li key={k}><span className="text-text">{k.replace(/_/g, " ")}</span>: {String(v)}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
      {error && <p role="alert" className="mt-2 text-xs text-crit">{error}</p>}
      {ev.data?.status.error && <p className="mt-2 text-xs text-crit">Last evaluation failed: {ev.data.status.error}</p>}
    </Card>
  );
}

export default function DetectionPage() {
  const { state, version } = useLive();
  const rules = useApi<RuleStatus[]>("/api/detections/rules", 2000);
  const [status, setStatus] = useState<"" | "active" | "cleared">("");
  const [offset, setOffset] = useState(0);
  const runId = state?.run_id;
  const events = useApi<Page<Alert>>(
    runId ? `/api/detections/events?run_id=${runId}&limit=25&offset=${offset}${status ? `&status=${status}` : ""}` : null,
  );
  useEffect(() => {
    const id = window.setTimeout(() => void events.reload(), 0);
    return () => window.clearTimeout(id);
  }, [Math.floor(version / 12)]); // eslint-disable-line react-hooks/exhaustive-deps
  const ro = Boolean(state?.read_only);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Detection analytics"
        subtitle="Eight transparent, physics-based rules evaluate every sample against the documented process model. Chips show each rule instance live: green evaluating, amber pending (debounce), red active, grey not evaluable."
      />
      <Card title="Detection rules" icon={Radar} subtitle="Thresholds are editable (audited). Expand a rule for its method.">
        {rules.loading && !rules.data ? <Loading /> : rules.error ? <ErrorState error={rules.error} onRetry={rules.reload} /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 font-medium">Rule</th>
                  <th className="py-2 font-medium">Title</th>
                  <th className="py-2 font-medium">Severity</th>
                  <th className="py-2 font-medium">Threshold</th>
                  <th className="py-2 font-medium">Debounce / clear</th>
                  <th className="py-2 font-medium">Instances (live)</th>
                  <th className="py-2 text-right font-medium">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rules.data?.map((r) => <RuleRow key={r.rule_id} rule={r} readOnly={ro} onSaved={rules.reload} />)}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Detection events (current run)"
        subtitle="One event per raise-to-clear episode of a rule instance (deduplicated)"
        actions={
          <select aria-label="Filter by status" className="input py-1 text-xs" value={status} onChange={(e) => { setOffset(0); setStatus(e.target.value as typeof status); }}>
            <option value="">All</option>
            <option value="active">Active</option>
            <option value="cleared">Cleared</option>
          </select>
        }
      >
        {events.error ? <ErrorState error={events.error} onRetry={events.reload} /> : !events.data ? <Loading /> : events.data.items.length === 0 ? (
          <EmptyState icon={Radar} title="No detection events in this run">Start a scenario in the Scenario Lab to generate synthetic anomalies.</EmptyState>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[820px] text-left text-xs">
                <thead className="text-muted">
                  <tr className="border-b border-line">
                    <th className="py-2 font-medium">ID</th>
                    <th className="py-2 font-medium">Rule</th>
                    <th className="py-2 font-medium">Instance</th>
                    <th className="py-2 font-medium">Observed</th>
                    <th className="py-2 font-medium">Expected</th>
                    <th className="py-2 font-medium">Threshold</th>
                    <th className="py-2 font-medium">Raised</th>
                    <th className="py-2 font-medium">Status</th>
                    <th className="py-2 font-medium">Incident</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {events.data.items.map((a) => (
                    <tr key={a.id} title={a.explanation}>
                      <td className="num py-2">{a.id}</td>
                      <td className="py-2"><Badge tone="cyan">{a.rule_id}</Badge></td>
                      <td className="num py-2">{a.instance_key}</td>
                      <td className="num py-2">{num(a.observed_value, 3)} {a.units}</td>
                      <td className="num py-2">{num(a.expected_value, 3)} {a.units}</td>
                      <td className="num py-2">{num(a.threshold, 3)}</td>
                      <td className="num py-2">T+{simClock(a.raised_t)}</td>
                      <td className="py-2"><Badge tone={a.status === "active" ? "crit" : "neutral"}>{a.status}</Badge></td>
                      <td className="py-2">{a.incident_id ? <Link className="text-cyan hover:underline" to={`/incidents/${a.incident_id}`}>{a.incident_id}</Link> : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="mt-3 flex items-center justify-between text-xs text-muted">
              <span>{events.data.total} events</span>
              <div className="flex gap-2">
                <Button size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 25))}>Previous</Button>
                <Button size="sm" disabled={offset + 25 >= events.data.total} onClick={() => setOffset(offset + 25)}>Next</Button>
              </div>
            </div>
          </>
        )}
      </Card>

      <Evaluation readOnly={ro} />
    </div>
  );
}
