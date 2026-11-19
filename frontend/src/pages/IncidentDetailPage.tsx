import { ArrowLeft, CheckCheck, Download, Eye, FileText, MessageSquarePlus, ShieldQuestion } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { TimeChart } from "../components/charts/TimeChart";
import {
  Badge, Button, Card, ClassificationBadge, EmptyState, ErrorState, KV, Loading, PageHeader, SeverityBadge, StatusBadge,
} from "../components/ui";
import { useAction } from "../hooks/useAction";
import { useApi } from "../hooks/useApi";
import { useLive } from "../hooks/useLive";
import { dateTimeOf, duration, num, simClock, timeOf } from "../lib/format";
import { api } from "../services/api";
import type { IncidentDetail } from "../types/api";

const STATUSES = ["open", "acknowledged", "investigating", "reviewed", "closed"];

export default function IncidentDetailPage() {
  const { id = "" } = useParams();
  const { incidents, state } = useLive();
  const inc = useApi<IncidentDetail>(`/api/incidents/${encodeURIComponent(id)}`);
  const { run, busy, error } = useAction();
  const [note, setNote] = useState("");
  const [showTruth, setShowTruth] = useState(false);
  const live = incidents.find((i) => i.id === id);
  const liveKey = live ? `${live.alert_ids?.length}:${live.detection_state}:${live.classification}:${Math.floor(live.last_seen_t / 10)}` : "";
  useEffect(() => {
    if (liveKey) void inc.reload();
  }, [liveKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const d = inc.data;
  const epoch = d?.telemetry.length ? Date.parse(d.telemetry[0].ts) - d.telemetry[0].t * 1000 : 0;
  const chart = useMemo(() => {
    if (!d) return null;
    const tel = d.telemetry;
    const x = (t: number) => epoch + t * 1000;
    return {
      level: [
        { name: "LT-101", data: tel.map((r) => [x(r.t), r.lt101] as [number, number | null]), color: "#22d3ee" },
        { name: "LT-102", data: tel.map((r) => [x(r.t), r.lt102] as [number, number | null]), color: "#7dd3fc", dashed: true },
        { name: "Predicted", data: tel.map((r) => [x(r.t), r.predicted_level] as [number, number | null]), color: "#a78bfa", width: 1.2 },
      ],
      residual: [
        { name: "Residual LT-101", data: tel.map((r) => [x(r.t), r.residual_lt101] as [number, number | null]), color: "#22d3ee" },
        { name: "Residual LT-102", data: tel.map((r) => [x(r.t), r.residual_lt102] as [number, number | null]), color: "#7dd3fc", dashed: true },
        { name: "Score", data: tel.map((r) => [x(r.t), r.anomaly_score] as [number, number | null]), color: "#f59e0b", yAxisIndex: 1 as const },
      ],
      flows: [
        { name: "FT-101", data: tel.map((r) => [x(r.t), r.ft101] as [number, number | null]), color: "#22d3ee" },
        { name: "FT-102", data: tel.map((r) => [x(r.t), r.ft102] as [number, number | null]), color: "#34d399" },
        { name: "PT-101", data: tel.map((r) => [x(r.t), r.pt101] as [number, number | null]), color: "#fbbf24", yAxisIndex: 1 as const },
      ],
      markers: d.detections.map((a) => ({ x: x(a.raised_t), label: a.rule_id, color: a.severity === "high" ? "#ef4444" : "#f59e0b" })),
      bands: [{ from: x(d.first_seen_t), to: x(d.last_seen_t), color: "rgba(239,68,68,0.08)", label: "incident" }],
    };
  }, [d, epoch]);

  if (inc.loading && !d) return <Loading label="Loading incident" />;
  if (inc.error) return <ErrorState error={inc.error} onRetry={inc.reload} />;
  if (!d) return <EmptyState icon={ShieldQuestion} title="Incident not found" />;
  const ro = Boolean(state?.read_only);
  const act = (key: string, fn: () => Promise<unknown>) => run(key, async () => { await fn(); await inc.reload(); });

  const timeline = [
    ...(d.timeline ?? []).map((e) => ({ ts: e.ts ?? "", who: "detection engine", text: e.text, kind: e.type })),
    ...d.notes.map((n) => ({ ts: n.created_at, who: n.author, text: n.text, kind: "note" })),
    ...d.audit.filter((a) => a.action !== "incident.note").map((a) => ({
      ts: a.ts, who: a.actor, text: `${a.action.replace("incident.", "")}${a.details && Object.keys(a.details).length ? ` ${JSON.stringify(a.details)}` : ""}`, kind: "action",
    })),
  ];

  return (
    <div className="space-y-4">
      <Link to="/incidents" className="inline-flex items-center gap-1 text-xs text-muted hover:text-text"><ArrowLeft className="size-3.5" /> All incidents</Link>
      <PageHeader
        eyebrow={
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone="cyan" className="num">{d.id}</Badge>
            <ClassificationBadge value={d.classification} />
            <SeverityBadge severity={d.severity} />
            <StatusBadge status={d.status} />
            {d.detection_state === "active" && <Badge tone="crit">DETECTIONS ACTIVE</Badge>}
            <Badge>confidence: {d.confidence}</Badge>
          </div>
        }
        title={d.title}
        subtitle={`First anomalous sample ${dateTimeOf(d.first_seen)} · last activity ${timeOf(d.last_seen)} · duration ${duration(d.last_seen_t - d.first_seen_t)} · run ${d.run_id}`}
        actions={
          <>
            <Button icon={CheckCheck} disabled={ro || d.acknowledged} busy={busy === "ack"} onClick={() => act("ack", () => api.post(`/api/incidents/${d.id}/acknowledge`))}>
              {d.acknowledged ? "Acknowledged" : "Acknowledge"}
            </Button>
            <select aria-label="Investigation status" className="input h-9" disabled={ro} value={d.status}
              onChange={(e) => act("status", () => api.post(`/api/incidents/${d.id}/status`, { status: e.target.value }))}>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <a href={`/api/incidents/${d.id}/evidence`} download className="inline-flex h-9 items-center gap-2 rounded-lg bg-raised px-3.5 text-[13px] ring-1 ring-inset ring-line-strong hover:bg-line-strong/60">
              <Download className="size-3.5" /> Export evidence
            </a>
            <Link to={`/reports?incident=${d.id}`} className="inline-flex h-9 items-center gap-2 rounded-lg bg-cyan px-3.5 text-[13px] font-semibold text-bg hover:bg-cyan/90">
              <FileText className="size-3.5" /> Report
            </Link>
          </>
        }
      />
      {error && <p role="alert" className="text-xs text-crit">{error}</p>}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="What was detected" className="xl:col-span-2">
          <p className="text-[14px] leading-relaxed">{d.summary}</p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="rounded-lg border border-line bg-bg/50 p-3">
              <div className="label mb-1">Expected physical behaviour</div>
              <p className="num text-[13px] text-ok">{d.expected_behavior}</p>
            </div>
            <div className="rounded-lg border border-crit/30 bg-crit/5 p-3">
              <div className="label mb-1">Actual observed behaviour</div>
              <p className="num text-[13px] text-crit">{d.observed_behavior}</p>
            </div>
          </div>
          <div className="mt-4">
            <div className="label mb-1.5">Classification basis</div>
            <ul className="list-disc space-y-1 pl-5 text-[13px] text-text">
              {d.classification_basis.map((b) => <li key={b}>{b}</li>)}
            </ul>
            <p className="mt-2 text-xs text-muted"><span className="text-text">Confidence {d.confidence}:</span> {d.confidence_rationale}</p>
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="Possible non-malicious explanations">
            <ul className="list-disc space-y-1 pl-5 text-[13px]">{d.alternatives.map((a) => <li key={a}>{a}</li>)}</ul>
          </Card>
          <Card title="Recommended investigation steps">
            <ol className="list-decimal space-y-1 pl-5 text-[13px]">{d.recommended_steps.map((a) => <li key={a}>{a}</li>)}</ol>
          </Card>
          <Card title="Affected simulated assets">
            <div className="flex flex-wrap gap-1.5">{d.assets.map((a) => <Badge key={a} tone="cyan">{a}</Badge>)}</div>
          </Card>
        </div>
      </div>

      <Card title="Supporting telemetry" subtitle="Recorded samples from 90 s before onset; red band = incident window, markers = alert raises (simulated data)">
        {chart && d.telemetry.length > 1 ? (
          <div className="grid gap-4 xl:grid-cols-3">
            <TimeChart ariaLabel="Incident level" series={chart.level} unit="m" digits={3} markers={chart.markers} bands={chart.bands} height={230} />
            <TimeChart ariaLabel="Incident residual" series={chart.residual} unit="m³" digits={3} y2={{ unit: "×thr", digits: 2 }} markers={chart.markers} bands={chart.bands} height={230} />
            <TimeChart ariaLabel="Incident flows" series={chart.flows} unit="L/s" digits={2} y2={{ unit: "bar", digits: 3 }} markers={chart.markers} bands={chart.bands} height={230} />
          </div>
        ) : <EmptyState icon={Eye} title="No stored telemetry for this window" />}
      </Card>

      <Card title="Triggered detections" subtitle="Each row is one deduplicated alert episode with its measured evidence">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-left text-xs">
            <thead className="text-muted">
              <tr className="border-b border-line">
                <th className="py-2 font-medium">Detection</th>
                <th className="py-2 font-medium">Rule</th>
                <th className="py-2 font-medium">Instance</th>
                <th className="py-2 font-medium">Onset → raised</th>
                <th className="py-2 font-medium">Observed (peak)</th>
                <th className="py-2 font-medium">Expected (peak)</th>
                <th className="py-2 font-medium">Threshold</th>
                <th className="py-2 font-medium">Peak</th>
                <th className="py-2 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {d.detections.map((a) => (
                <tr key={a.id} className="align-top">
                  <td className="num py-2">{a.id}</td>
                  <td className="py-2"><Badge tone="cyan">{a.rule_id}</Badge> <span className="text-text">{a.title}</span>
                    <p className="mt-1 max-w-md text-[11px] text-muted">{a.peak_explanation || a.explanation}</p>
                  </td>
                  <td className="num py-2">{a.instance_key}</td>
                  <td className="num py-2">T+{simClock(a.first_seen_t)} → T+{simClock(a.raised_t)}</td>
                  <td className="num py-2" title={a.observed_label}>{num(a.peak_observed ?? a.observed_value, 3)} {a.units}</td>
                  <td className="num py-2" title={a.expected_label}>{num(a.peak_expected ?? a.expected_value, 3)} {a.units}</td>
                  <td className="num py-2">{num(a.threshold, 3)}</td>
                  <td className="num py-2">{num(a.peak_score, 1)}×</td>
                  <td className="py-2"><Badge tone={a.status === "active" ? "crit" : "neutral"}>{a.status}</Badge>
                    {a.cleared_at && <div className="num mt-1 text-[10px] text-faint">cleared {timeOf(a.cleared_at)}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Investigation timeline" subtitle="Detection events, analyst actions and notes (local audit trail)">
          <ol className="relative space-y-3 border-l border-line pl-4">
            {timeline.sort((a, b) => a.ts.localeCompare(b.ts)).map((e, i) => (
              <li key={i} className="text-[13px]">
                <span className={`absolute -left-[5px] mt-1.5 size-2.5 rounded-full ${e.kind === "detection_raised" ? "bg-crit" : e.kind === "detection_cleared" ? "bg-ok" : e.kind === "note" ? "bg-cyan" : "bg-muted"}`} />
                <div className="num text-[11px] text-faint">{dateTimeOf(e.ts)} · {e.who}</div>
                <div className="text-text">{e.text}</div>
              </li>
            ))}
          </ol>
        </Card>
        <div className="space-y-4">
          <Card title="Analyst notes" icon={MessageSquarePlus}>
            <form
              onSubmit={(ev) => {
                ev.preventDefault();
                if (!note.trim()) return;
                void act("note", async () => { await api.post(`/api/incidents/${d.id}/notes`, { text: note.trim() }); setNote(""); });
              }}
              className="space-y-2"
            >
              <label htmlFor="note" className="sr-only">Add investigation note</label>
              <textarea id="note" value={note} maxLength={2000} disabled={ro} onChange={(e) => setNote(e.target.value)}
                placeholder="Add an investigation note (stored locally, audited)…" className="input min-h-20 w-full" />
              <Button type="submit" size="sm" variant="primary" disabled={ro || !note.trim()} busy={busy === "note"}>Add note</Button>
            </form>
            {d.notes.length > 0 && (
              <ul className="mt-3 space-y-2">
                {d.notes.map((n) => (
                  <li key={n.id} className="rounded-lg border border-line bg-bg/50 p-2.5 text-[13px]">
                    <div className="num mb-0.5 text-[11px] text-faint">{dateTimeOf(n.created_at)} · {n.author}</div>
                    {n.text}
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card title="Simulator ground truth" subtitle="Scenario labels from the lab. Never available to the detection engine."
            actions={<Button size="sm" variant="ghost" onClick={() => setShowTruth(!showTruth)}>{showTruth ? "Hide" : "Reveal"}</Button>}>
            {showTruth ? (
              d.scenario_events.length ? (
                <KV items={d.scenario_events.map((e) => [`T+${simClock(e.sim_time_s ?? 0)}`, <span key={e.ts}><Badge tone="truth">{e.kind}</Badge> {e.description}</span>])} />
              ) : <p className="text-xs text-muted">No scenario was active in this run.</p>
            ) : <p className="text-xs text-muted">Hidden to support blind investigation. Reveal to compare with the detector's conclusion.</p>}
          </Card>
        </div>
      </div>
    </div>
  );
}
