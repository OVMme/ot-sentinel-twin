import { FastForward, History, Pause, Play, RefreshCw, Rewind, SkipBack } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PlantDiagram } from "../components/PlantDiagram";
import { TimeChart } from "../components/charts/TimeChart";
import { Badge, Button, Card, ClassificationBadge, EmptyState, ErrorState, Loading, PageHeader, Segmented, SeverityBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { cn, dateTimeOf, duration, num, signed, simClock } from "../lib/format";
import { alertAnchors, viewFromReplay } from "../lib/plant";
import type { Alert, ReplayData, RunInfo } from "../types/api";

const SPEEDS = [1, 2, 5, 10, 30].map((s) => ({ value: s, label: `${s}x` }));
const TICK_MS = 125;

function indexAt(times: number[], t: number): number {
  let lo = 0;
  let hi = times.length - 1;
  if (hi < 0) return -1;
  if (t <= times[0]) return 0;
  if (t >= times[hi]) return hi;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= t) lo = mid;
    else hi = mid - 1;
  }
  return lo;
}

function Timeline({ data, t, onSeek }: { data: ReplayData; t: number; onSeek: (t: number) => void }) {
  const times = data.columns.sim_time_s;
  const t0 = times[0] ?? 0;
  const t1 = times[times.length - 1] ?? 1;
  const span = Math.max(t1 - t0, 1);
  const X = (v: number) => ((v - t0) / span) * 1000;
  const ref = useRef<SVGSVGElement>(null);
  const dragging = useRef(false);
  const seekFromEvent = (e: RPointerEvent<SVGSVGElement>) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    const frac = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
    onSeek(t0 + frac * span);
  };
  const scen: { from: number; to: number; id: string; onset?: number }[] = [];
  for (const e of data.scenario_events) {
    const et = e.sim_time_s ?? 0;
    if (e.kind === "started") scen.push({ from: et, to: t1, id: e.scenario_id });
    if (e.kind === "fault_onset" && scen.length) scen[scen.length - 1].onset = et;
    if (e.kind === "stopped" && scen.length) scen[scen.length - 1].to = et;
  }
  return (
    <div>
      <svg
        ref={ref}
        viewBox="0 0 1000 70"
        preserveAspectRatio="none"
        className="h-[70px] w-full cursor-pointer touch-none select-none"
        onPointerDown={(e) => { dragging.current = true; e.currentTarget.setPointerCapture(e.pointerId); seekFromEvent(e); }}
        onPointerMove={(e) => dragging.current && seekFromEvent(e)}
        onPointerUp={() => { dragging.current = false; }}
        aria-hidden
      >
        <rect x={0} y={0} width={1000} height={70} fill="#0a1120" />
        {scen.map((s, i) => (
          <g key={i}>
            <rect x={X(s.from)} y={4} width={Math.max(X(s.to) - X(s.from), 1)} height={18} fill="#a78bfa" fillOpacity={0.18} />
            {s.onset != null && <line x1={X(s.onset)} x2={X(s.onset)} y1={4} y2={22} stroke="#a78bfa" strokeWidth={2} />}
          </g>
        ))}
        {data.incidents.map((inc) => (
          <rect key={inc.id} x={X(inc.first_seen_t)} y={50} width={Math.max(X(inc.last_seen_t) - X(inc.first_seen_t), 2)} height={12} rx={2}
            fill={inc.classification === "suspected_manipulation" ? "#ef4444" : "#f59e0b"} fillOpacity={0.7} />
        ))}
        {data.detections.map((a) => (
          <line key={a.id} x1={X(a.raised_t)} x2={X(a.raised_t)} y1={26} y2={46} stroke={a.severity === "high" ? "#ef4444" : "#f59e0b"} strokeWidth={2} />
        ))}
        <line x1={X(t)} x2={X(t)} y1={0} y2={70} stroke="#a78bfa" strokeWidth={3} />
      </svg>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 rounded-sm bg-replay/40" /> scenario window (ground truth)</span>
        <span className="flex items-center gap-1"><span className="inline-block h-3 w-0.5 bg-crit" /> alert raised</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2.5 w-4 rounded-sm bg-warn/70" /> incident span</span>
        <span className="num ml-auto">T+{simClock(t0)} — T+{simClock(t1)}</span>
      </div>
      <label className="sr-only" htmlFor="replay-scrub">Replay position</label>
      <input id="replay-scrub" type="range" min={t0} max={t1} step={0.5} value={t} onChange={(e) => onSeek(Number(e.target.value))}
        className="mt-2 w-full accent-[#a78bfa]" />
    </div>
  );
}

export default function ReplayPage() {
  const [params, setParams] = useSearchParams();
  const runs = useApi<RunInfo[]>("/api/replay/runs");
  const runId = params.get("run") ?? runs.data?.[0]?.id ?? null;
  const data = useApi<ReplayData>(runId ? `/api/replay/${runId}` : null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(5);
  const [cmpIncident, setCmpIncident] = useState<string>("");
  const d = data.data;
  const times = useMemo(() => d?.columns.sim_time_s ?? [], [d]);
  const t0 = times[0] ?? 0;
  const t1 = times[times.length - 1] ?? 0;

  useEffect(() => {
    setPlaying(false);
    setT(d?.columns.sim_time_s[0] ?? 0);
    setCmpIncident(d?.incidents[0]?.id ?? "");
  }, [d]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setT((cur) => {
        const next = cur + (TICK_MS / 1000) * speed;
        if (next >= t1) {
          setPlaying(false);
          return t1;
        }
        return next;
      });
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [playing, speed, t1]);

  const idx = indexAt(times, t);
  const epoch = d ? Date.parse(d.run.epoch) : 0;
  const x = (s: number) => epoch + s * 1000;
  const view = d ? viewFromReplay(d.columns, idx) : null;
  const activeAtT = useMemo<Alert[]>(
    () => (d ? d.detections.filter((a) => a.raised_t <= t && (a.cleared_t == null || a.cleared_t > t)) : []),
    [d, t],
  );
  const anchors = useMemo(() => alertAnchors(activeAtT), [activeAtT]);
  const seenAtT = useMemo(() => (d ? d.detections.filter((a) => a.raised_t <= t).slice().reverse() : []), [d, t]);

  const series = useMemo(() => {
    if (!d) return null;
    const c = d.columns;
    const S = (vals: (number | null)[]) => vals.map((v, i) => [x(c.sim_time_s[i]), v] as [number, number | null]);
    return {
      level: [
        { name: "LT-101", data: S(c.lt101), color: "#22d3ee" },
        { name: "LT-102", data: S(c.lt102), color: "#7dd3fc", dashed: true },
        { name: "Physical truth", data: S(c.true_level), color: "#f0abfc", width: 1.2 },
        { name: "Predicted", data: S(c.predicted_level), color: "#a78bfa", width: 1 },
      ],
      residual: [
        { name: "Residual LT-101", data: S(c.residual_lt101), color: "#22d3ee" },
        { name: "Residual LT-102", data: S(c.residual_lt102), color: "#7dd3fc", dashed: true },
        { name: "Anomaly score", data: S(c.anomaly_score), color: "#f59e0b", yAxisIndex: 1 as const },
      ],
      markers: d.detections.slice(0, 40).map((a) => ({ x: x(a.raised_t), label: a.rule_id, color: a.severity === "high" ? "#ef4444" : "#f59e0b" })),
    };
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps

  // Coarser playhead for charts (re-rendering 2 large charts at 8 Hz is wasteful)
  const chartPlayhead = d ? x(Math.round(t)) : null;

  const cmp = useMemo(() => {
    if (!d || !cmpIncident) return null;
    const inc = d.incidents.find((i) => i.id === cmpIncident);
    if (!inc) return null;
    const c = d.columns;
    const bi = indexAt(times, inc.first_seen_t - 30);
    const rows: [string, string, (number | null)[], number][] = [
      ["LT-101 level", "m", c.lt101, 3],
      ["LT-102 level", "m", c.lt102, 3],
      ["Physical truth level", "m", c.true_level, 3],
      ["Predicted level (from flows)", "m", c.predicted_level, 3],
      ["FT-101 inlet flow", "L/s", c.ft101, 2],
      ["FT-102 outlet flow", "L/s", c.ft102, 2],
      ["PT-101 pressure", "bar", c.pt101, 3],
      ["XV-101 command", "%", c.inlet_cmd, 1],
      ["ZT-101 inlet position", "%", c.zt101, 1],
      ["Mass residual LT-101", "m³", c.residual_lt101, 3],
      ["LT-101 − LT-102", "m", c.disagreement, 3],
    ];
    return { inc, bi, rows };
  }, [d, cmpIncident, times]);

  const seek = (v: number) => setT(Math.min(Math.max(v, t0), t1));

  return (
    <div className="space-y-4">
      <PageHeader
        eyebrow={<Badge tone="replay">REPLAY MODE · RECORDED DATA · NO LIVE EFFECTS</Badge>}
        title="Time-travel replay"
        subtitle="Deterministic playback of stored telemetry, detections and scenario events. Nothing is re-simulated and nothing is sent to the live plant."
        actions={
          <>
            <select aria-label="Select recorded run" className="input h-9 max-w-[360px]" value={runId ?? ""}
              onChange={(e) => setParams({ run: e.target.value })}>
              {runs.data?.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.id} · {duration(r.sim_duration_s)} · {r.incident_count} incident(s){r.status === "running" ? " · recording" : ""}
                </option>
              ))}
            </select>
            <Button icon={RefreshCw} onClick={() => { void runs.reload(); void data.reload(); }}>Reload</Button>
          </>
        }
      />
      {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} /> : runs.loading && !runs.data ? <Loading /> : !runs.data?.length ? (
        <Card><EmptyState icon={History} title="No recorded runs yet">Start the simulation; every run is recorded automatically.</EmptyState></Card>
      ) : data.error ? <ErrorState error={data.error} onRetry={data.reload} /> : !d ? <Loading label="Loading recording" /> : d.count === 0 ? (
        <Card><EmptyState icon={History} title="This run has no stored samples" /></Card>
      ) : (
        <>
          <Card className="border-replay/30">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <Button size="sm" icon={SkipBack} onClick={() => seek(t0)} aria-label="Jump to start">Start</Button>
              <Button size="sm" icon={Rewind} onClick={() => seek(t - 10)} aria-label="Back 10 seconds">−10 s</Button>
              <Button size="sm" variant="primary" icon={playing ? Pause : Play} onClick={() => { if (t >= t1) seek(t0); setPlaying(!playing); }}
                className="!bg-replay hover:!bg-replay/90 !shadow-none">
                {playing ? "Pause" : "Play"}
              </Button>
              <Button size="sm" icon={FastForward} onClick={() => seek(t + 10)} aria-label="Forward 10 seconds">+10 s</Button>
              <Segmented label="Playback speed" value={speed} onChange={setSpeed} options={SPEEDS} />
              <span className="num ml-2 text-lg text-replay">T+{simClock(t)}</span>
              <span className="num text-xs text-muted">{dateTimeOf(d.columns.ts[idx])} · sample {d.columns.seq[idx]}</span>
              <div className="ml-auto flex flex-wrap gap-1.5">
                {d.incidents.map((i) => (
                  <Button key={i.id} size="sm" variant="ghost" onClick={() => seek(i.first_seen_t - 30)}>{i.id} −30 s</Button>
                ))}
              </div>
            </div>
            <Timeline data={d} t={t} onSeek={seek} />
            {d.next_from_seq != null && <p className="mt-2 text-xs text-warn">Showing the first {d.count} samples of this run.</p>}
          </Card>

          <div className="grid gap-4 2xl:grid-cols-[1fr_400px]">
            <Card title="Recorded plant state" subtitle="Rendered from stored telemetry at the playhead">
              <PlantDiagram view={view} anchors={anchors} variant="twin" replay className="w-full" />
            </Card>
            <Card title="Alerts as they occurred" subtitle={`${activeAtT.length} active at playhead · ${seenAtT.length} raised so far`}>
              {seenAtT.length === 0 ? <EmptyState icon={History} title="No alerts yet at this point" /> : (
                <ul className="max-h-[440px] divide-y divide-line overflow-auto">
                  {seenAtT.map((a) => {
                    const active = a.cleared_t == null || a.cleared_t > t;
                    return (
                      <li key={a.id} className={cn("py-2", !active && "opacity-60")}>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <SeverityBadge severity={a.severity} />
                          <Badge tone="cyan">{a.rule_id}</Badge>
                          <span className="num text-xs">{a.instance_key}</span>
                          <button type="button" className="num ml-auto text-[11px] text-replay hover:underline" onClick={() => seek(a.raised_t)}>T+{simClock(a.raised_t)}</button>
                        </div>
                        <p className="mt-1 text-xs text-muted">{a.peak_explanation || a.explanation}</p>
                        <p className="num mt-0.5 text-[11px] text-faint">expected {num(a.peak_expected ?? a.expected_value, 3)} · observed {num(a.peak_observed ?? a.observed_value, 3)} {a.units} (at peak){a.incident_id ? ` · ${a.incident_id}` : ""}</p>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>
          </div>

          {series && (
            <div className="grid gap-4 xl:grid-cols-2">
              <Card title="Level: reported, predicted and physical truth" subtitle="Click a chart to move the playhead">
                <TimeChart ariaLabel="Replay level" series={series.level} unit="m" digits={3} markers={series.markers} playhead={chartPlayhead} slider onClickX={(ms) => seek((ms - epoch) / 1000)} height={250} />
              </Card>
              <Card title="Mass-balance residual and anomaly score" subtitle="Expected vs observed physics over the recording">
                <TimeChart ariaLabel="Replay residual" series={series.residual} unit="m³" digits={3} y2={{ unit: "×thr", digits: 2 }} markers={series.markers} playhead={chartPlayhead} slider onClickX={(ms) => seek((ms - epoch) / 1000)} height={250} />
              </Card>
            </div>
          )}

          <Card
            title="Before vs after the anomaly"
            subtitle="Recorded values 30 s before the incident's first anomalous sample compared with the playhead"
            actions={d.incidents.length ? (
              <select aria-label="Incident to compare" className="input py-1 text-xs" value={cmpIncident} onChange={(e) => setCmpIncident(e.target.value)}>
                {d.incidents.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.title.slice(0, 50)}</option>)}
              </select>
            ) : undefined}
          >
            {!cmp ? <EmptyState icon={History} title="No incidents in this run">Run a scenario to create an incident to compare.</EmptyState> : (
              <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-left text-xs">
                    <thead className="text-muted">
                      <tr className="border-b border-line">
                        <th className="py-2 font-medium">Signal</th>
                        <th className="py-2 text-right font-medium">Before (T+{simClock(times[cmp.bi])})</th>
                        <th className="py-2 text-right font-medium">Playhead (T+{simClock(t)})</th>
                        <th className="py-2 text-right font-medium">Δ</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-line">
                      {cmp.rows.map(([label, unit, col, dg]) => {
                        const a = col[cmp.bi];
                        const b = col[idx];
                        const delta = a != null && b != null ? b - a : null;
                        return (
                          <tr key={label}>
                            <td className="py-1.5">{label}</td>
                            <td className="num py-1.5 text-right">{num(a, dg)} {unit}</td>
                            <td className="num py-1.5 text-right text-replay">{num(b, dg)} {unit}</td>
                            <td className={cn("num py-1.5 text-right", delta != null && Math.abs(delta) > 0 ? "text-text" : "text-faint")}>{signed(delta, dg)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="space-y-2 text-[13px]">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <ClassificationBadge value={cmp.inc.classification} />
                    <SeverityBadge severity={cmp.inc.severity} />
                  </div>
                  <p className="font-medium">{cmp.inc.title}</p>
                  <p className="text-xs text-muted">{cmp.inc.summary}</p>
                  <Link to={`/incidents/${cmp.inc.id}`} className="text-xs text-cyan hover:underline">Open investigation →</Link>
                </div>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
