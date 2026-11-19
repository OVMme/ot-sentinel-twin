import { Download, FileText, Printer } from "lucide-react";
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, ClassificationBadge, EmptyState, ErrorState, KV, Loading, PageHeader, SeverityBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { dateTimeOf, num } from "../lib/format";
import type { Incident, Page, Report } from "../types/api";

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-4">
      <h2 className="mb-2 text-sm font-semibold"><span className="num mr-2 text-cyan">{n}.</span>{title}</h2>
      <div className="text-[13px] leading-relaxed">{children}</div>
    </section>
  );
}

export default function ReportsPage() {
  const [params, setParams] = useSearchParams();
  const list = useApi<Page<Incident>>("/api/incidents?limit=100");
  const id = params.get("incident") ?? list.data?.items[0]?.id ?? null;
  const report = useApi<Report>(id ? `/api/reports/${id}?format=json` : null);
  const r = report.data;

  return (
    <div className="space-y-4">
      <div className="no-print">
        <PageHeader
          title="Security reports"
          subtitle="Incident reports generated strictly from stored evidence. Export Markdown or JSON, or print / save as PDF from the browser."
          actions={
            <>
              <select aria-label="Select incident" className="input h-9 max-w-[380px]" value={id ?? ""} onChange={(e) => setParams({ incident: e.target.value })}>
                {list.data?.items.map((i) => <option key={i.id} value={i.id}>{i.id} · {i.title.slice(0, 60)}</option>)}
              </select>
              {id && (
                <>
                  <a className="inline-flex h-9 items-center gap-2 rounded-lg bg-raised px-3.5 text-[13px] ring-1 ring-inset ring-line-strong hover:bg-line-strong/60" href={`/api/reports/${id}?format=md&download=true`} download>
                    <Download className="size-3.5" /> Markdown
                  </a>
                  <a className="inline-flex h-9 items-center gap-2 rounded-lg bg-raised px-3.5 text-[13px] ring-1 ring-inset ring-line-strong hover:bg-line-strong/60" href={`/api/reports/${id}?format=json&download=true`} download>
                    <Download className="size-3.5" /> JSON
                  </a>
                  <Button icon={Printer} onClick={() => window.print()}>Print / PDF</Button>
                </>
              )}
            </>
          }
        />
      </div>
      {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : list.loading && !list.data ? <Loading /> : !list.data?.items.length ? (
        <Card><EmptyState icon={FileText} title="No incidents to report">Reports become available once an incident has been detected.</EmptyState></Card>
      ) : report.error ? <ErrorState error={report.error} onRetry={report.reload} /> : !r ? <Loading label="Generating report" /> : (
        <Card className="print-area">
          <article className="space-y-4">
            <div className="rounded-lg border border-warn/30 bg-warn/10 px-3 py-2 text-xs font-medium text-warn">{r.data_notice}</div>
            <header>
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="cyan" className="num">{r.incident.id}</Badge>
                <ClassificationBadge value={r.incident.classification} />
                <SeverityBadge severity={r.incident.severity} />
                <Badge>confidence {r.incident.confidence}</Badge>
                <Badge>status {r.incident.status}</Badge>
              </div>
              <h1 className="mt-2 text-lg font-semibold">Incident report: {r.incident.title}</h1>
              <p className="num text-xs text-muted">{r.report_id} · generated {dateTimeOf(r.generated_at)}</p>
            </header>
            <Section n={1} title="Executive summary"><p>{r.executive_summary}</p></Section>
            <Section n={2} title="Simulation identification">
              <KV items={Object.entries(r.simulation).map(([k, v]) => [k.replace(/_/g, " "), <span key={k} className="num">{String(v)}</span>])} />
            </Section>
            <Section n={3} title="Affected simulated assets">
              <ul className="list-disc pl-5">{r.affected_assets.map((a) => <li key={a.id}><span className="num">{a.id}</span> — {a.name} ({a.kind})</li>)}</ul>
            </Section>
            <Section n={4} title="Incident timeline">
              <ul className="space-y-1">
                {r.timeline.map((e, i) => (
                  <li key={i} className="grid grid-cols-[150px_120px_1fr] gap-2 text-xs">
                    <span className="num text-muted">{dateTimeOf(e.ts)}</span>
                    <span className="text-faint">{e.source}</span>
                    <span>{e.text}</span>
                  </li>
                ))}
              </ul>
            </Section>
            <Section n={5} title="Triggered detection rules">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[700px] text-left text-xs">
                  <thead className="text-muted"><tr className="border-b border-line">
                    <th className="py-1.5 font-medium">Detection</th><th className="py-1.5 font-medium">Rule</th><th className="py-1.5 font-medium">Instance</th>
                    <th className="py-1.5 font-medium">Raised</th><th className="py-1.5 font-medium">Observed</th><th className="py-1.5 font-medium">Expected</th><th className="py-1.5 font-medium">Threshold</th>
                  </tr></thead>
                  <tbody className="divide-y divide-line">
                    {r.triggered_rules.map((d) => (
                      <tr key={d.id}>
                        <td className="num py-1.5">{d.id}</td><td className="py-1.5">{d.rule_id} {d.title}</td><td className="num py-1.5">{d.instance_key}</td>
                        <td className="num py-1.5">{dateTimeOf(d.raised_at)}</td><td className="num py-1.5">{num(d.observed_value, 3)} {d.units}</td>
                        <td className="num py-1.5">{num(d.expected_value, 3)} {d.units}</td><td className="num py-1.5">{num(d.threshold, 3)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
            <Section n={6} title="Physical process discrepancies">
              <p><span className="text-muted">Expected:</span> {r.expected_behavior}</p>
              <p><span className="text-muted">Observed:</span> {r.observed_behavior}</p>
              <ul className="mt-2 list-disc space-y-1 pl-5">{r.triggered_rules.map((d) => <li key={d.id}><b>{d.rule_id} / {d.instance_key}:</b> {d.explanation}</li>)}</ul>
            </Section>
            <Section n={7} title="Supporting telemetry">
              <p className="mb-2 text-xs text-muted">Statistics 60 s before onset vs. during the incident (sim time {r.supporting_telemetry.window_s[0]} s – {r.supporting_telemetry.window_s[1]} s).</p>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[620px] text-left text-xs">
                  <thead className="text-muted"><tr className="border-b border-line"><th className="py-1.5 font-medium">Signal</th><th className="py-1.5 font-medium">Before (min / mean / max)</th><th className="py-1.5 font-medium">During (min / mean / max)</th></tr></thead>
                  <tbody className="divide-y divide-line">
                    {r.supporting_telemetry.signals.map((s) => (
                      <tr key={s.signal}>
                        <td className="py-1.5">{s.label} <span className="text-faint">({s.unit})</span></td>
                        <td className="num py-1.5">{s.before ? `${s.before.min} / ${s.before.mean} / ${s.before.max}` : "—"}</td>
                        <td className="num py-1.5">{s.during ? `${s.during.min} / ${s.during.mean} / ${s.during.max}` : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>
            <Section n={8} title="Detection methodology">
              <ul className="space-y-2">{r.methodology.map((m) => (
                <li key={m.rule_id}><b>{m.rule_id} {m.title}.</b> {m.description} <span className="text-muted">Method: {m.methodology}</span>{" "}
                  <span className="num text-xs text-faint">(threshold {m.config.threshold} {m.config.units}, debounce {m.config.debounce_s} s)</span></li>
              ))}</ul>
            </Section>
            <Section n={9} title="Evidence and limitations">
              <p className="label mb-1">Classification basis</p>
              <ul className="mb-2 list-disc pl-5">{r.classification_basis.map((b) => <li key={b}>{b}</li>)}</ul>
              <p className="mb-2"><span className="text-muted">Confidence {r.incident.confidence}:</span> {r.confidence_rationale}</p>
              <p className="label mb-1">Possible non-malicious explanations</p>
              <ul className="mb-2 list-disc pl-5">{r.alternative_explanations.map((b) => <li key={b}>{b}</li>)}</ul>
              <p className="label mb-1">Limitations</p>
              <ul className="list-disc pl-5 text-muted">{r.evidence_limitations.map((b) => <li key={b}>{b}</li>)}</ul>
            </Section>
            <Section n={10} title="Recommended investigation steps">
              <ol className="list-decimal pl-5">{r.recommended_investigation_steps.map((s) => <li key={s}>{s}</li>)}</ol>
              {r.analyst_notes.length > 0 && (
                <>
                  <p className="label mb-1 mt-3">Analyst notes</p>
                  <ul className="list-disc pl-5">{r.analyst_notes.map((n) => <li key={n.id}>{dateTimeOf(n.created_at)} {n.author}: {n.text}</li>)}</ul>
                </>
              )}
            </Section>
            <Section n={11} title="Conclusions"><p>{r.conclusions}</p></Section>
            {r.simulator_ground_truth.events.length > 0 && (
              <section className="rounded-lg border border-truth/30 bg-truth/5 p-3 text-xs">
                <p className="mb-1 font-semibold text-truth">Appendix — {r.simulator_ground_truth.notice}</p>
                <ul className="space-y-0.5">{r.simulator_ground_truth.events.map((e, i) => <li key={i} className="num">{dateTimeOf(e.ts)} · {e.kind} · {e.scenario_id}: {e.description}</li>)}</ul>
              </section>
            )}
          </article>
        </Card>
      )}
    </div>
  );
}
