import { ShieldCheck } from "lucide-react";
import { Badge, Card, PageHeader } from "../components/ui";

const LAYERS = [
  { name: "Web application", items: ["Digital twin (SVG)", "Live telemetry", "Incidents", "Scenario lab", "Replay", "Reports"], color: "#22d3ee" },
  { name: "FastAPI", items: ["REST + WebSocket", "Validation & rate limits", "Report generator", "Evaluation harness"], color: "#7dd3fc" },
  { name: "Industrial twin engine", items: ["Tank mass balance", "Pump curve", "Rate-limited valves", "Sensors & noise", "PI controller + interlocks"], color: "#34d399" },
  { name: "Detection engine", items: ["8 physics / data rules", "Debounce & hysteresis", "Correlation", "Evidence-based classification"], color: "#f59e0b" },
  { name: "Data & evidence", items: ["SQLite (portable schema)", "Telemetry history", "Detections & incidents", "Audit trail"], color: "#a78bfa" },
];

const RULES: [string, string, string][] = [
  ["PHYS-001", "Mass balance", "A·Δh over 60 s vs ∫(FT-101 − FT-102) dt, per level transmitter"],
  ["PHYS-002", "Sensor disagreement", "|LT-101 − LT-102| beyond instrument tolerance"],
  ["PHYS-003", "Impossible rate of change", "level slope beyond Qmax / A (+ noise margin)"],
  ["PHYS-004", "Command / actuator mismatch", "feedback outside the healthy stroking envelope"],
  ["PHYS-005", "Pump / process inconsistency", "measured ΔP vs pump curve at measured flow"],
  ["PHYS-006", "Frozen sensor", "exact flatline while independent signals predict change"],
  ["PHYS-007", "Pressure / flow inconsistency", "FT-102 vs valve equation Kv·x·√(P − Pback)"],
  ["DATA-001", "Telemetry freshness", "stale, missing, out-of-order, gaps (data quality)"],
];

export default function AboutPage() {
  return (
    <div className="space-y-4">
      <PageHeader title="Architecture & methodology" subtitle="See the process. Detect the impossible. OT Sentinel Twin asks whether reported industrial behaviour is physically consistent — not just whether a network packet looks malicious." />
      <Card title="Logical architecture">
        <div className="grid gap-2 md:grid-cols-5">
          {LAYERS.map((l, i) => (
            <div key={l.name} className="relative rounded-xl border border-line bg-bg/60 p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="num flex size-6 items-center justify-center rounded-md text-xs font-bold text-bg" style={{ background: l.color }}>{i + 1}</span>
                <span className="text-[13px] font-semibold">{l.name}</span>
              </div>
              <ul className="space-y-1 text-xs text-muted">{l.items.map((x) => <li key={x}>· {x}</li>)}</ul>
            </div>
          ))}
        </div>
        <p className="mt-3 text-xs text-muted">
          Strict separation: the detection engine receives only reported telemetry plus static engineering data (tank geometry, valve and pump characteristics, instrument specs). Scenario labels and physical truth are used only for evaluation and visual comparison.
        </p>
      </Card>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Physical model">
          <div className="space-y-2 text-[13px]">
            <p className="num rounded-lg bg-bg/70 p-3 text-cyan">dV/dt = Qin − Qout − Qoverflow &nbsp;·&nbsp; V = A·h &nbsp;·&nbsp; dh/dt = (Qin − Qout)/A</p>
            <p className="num rounded-lg bg-bg/70 p-3 text-cyan">ΔPpump = s²·P0 − k·Q² &nbsp;·&nbsp; Pline = ρgh + ΔPpump &nbsp;·&nbsp; Q = Kv·x·√(Pline − Pback)</p>
            <p className="text-muted">Explicit 0.1 s integration with exact bookkeeping of overflow and dry-running, so conservation of mass holds to floating-point precision (verified by tests). Sensors add seeded noise, bias and quantisation; actuator commands are separate from physical positions.</p>
          </div>
        </Card>
        <Card title="Detection rules">
          <table className="w-full text-left text-xs">
            <tbody className="divide-y divide-line">
              {RULES.map(([id, t, m]) => (
                <tr key={id}><td className="py-1.5 pr-2"><Badge tone={id.startsWith("DATA") ? "neutral" : "cyan"}>{id}</Badge></td><td className="py-1.5 pr-2 font-medium">{t}</td><td className="py-1.5 text-muted">{m}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Incident classification">
          <ul className="space-y-2 text-[13px]">
            <li><Badge>Data-quality issue</Badge> <span className="text-muted">only freshness / integrity findings.</span></li>
            <li><Badge tone="warn">Equipment fault</Badge> <span className="text-muted">a valve, pump or single transmitter contradicts its model.</span></li>
            <li><Badge tone="cyan">Physical anomaly</Badge> <span className="text-muted">instruments agree with each other, but the process deviates from the model.</span></li>
            <li><Badge tone="crit">Suspected manipulation</Badge> <span className="text-muted">one sensor isolated by redundancy and mass balance, abrupt onset, and the controller demonstrably acting on the false value. Always a hypothesis, always listed with non-malicious explanations.</span></li>
          </ul>
        </Card>
        <Card title="Safety & scope" icon={ShieldCheck}>
          <ul className="list-disc space-y-1 pl-5 text-[13px] text-muted">
            <li>All telemetry, assets and events are synthetic; nothing connects to PLCs, gateways or industrial networks.</li>
            <li>No industrial protocol is implemented; scenarios modify the simulation only and are labelled as synthetic.</li>
            <li>Not a certified safety system and no replacement for real operational protections.</li>
            <li>Thresholds are calibrated to this twin's noise model and must be re-validated for any other process.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}
