import { Download, Pause, Play } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { TimeChart, type Series } from "../components/charts/TimeChart";
import { Badge, Button, Card, Loading, PageHeader, Segmented } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useLive } from "../hooks/useLive";
import { alertMarkers, pick, runEpochMs, sig } from "../lib/series";
import type { RuleStatus, Sample } from "../types/api";

const WINDOWS = [
  { value: 240, label: "2 min" },
  { value: 600, label: "5 min" },
  { value: 1200, label: "10 min" },
];

export default function TelemetryPage() {
  const live = useLive();
  const [paused, setPaused] = useState(false);
  const [win, setWin] = useState(600);
  const frozen = useRef<{ samples: Sample[]; alerts: typeof live.alerts } | null>(null);
  const rules = useApi<RuleStatus[]>("/api/detections/rules");

  if (paused && !frozen.current) frozen.current = { samples: live.samples, alerts: live.alerts };
  if (!paused) frozen.current = null;
  const source = frozen.current ?? { samples: live.samples, alerts: live.alerts };
  const samples = useMemo(() => source.samples.slice(-win), [source.samples, win]);
  const epoch = runEpochMs(samples[samples.length - 1]);
  const fromT = samples[0]?.t ?? 0;
  const thr = (id: string) => rules.data?.find((r) => r.rule_id === id)?.config.threshold;
  const markers = useMemo(() => alertMarkers(source.alerts, epoch, fromT), [source.alerts, epoch, fromT]);

  const charts = useMemo(() => {
    const p = (f: (s: Sample) => unknown) => pick(samples, epoch, f);
    const s = (name: string, data: Series["data"], color: string, extra: Partial<Series> = {}): Series => ({ name, data, color, ...extra });
    return {
      level: [
        s("LT-101", p(sig("sensor.primary_level")), "#22d3ee", { area: true }),
        s("LT-102", p(sig("sensor.secondary_level")), "#7dd3fc", { dashed: true }),
      ],
      flows: [s("FT-101 inlet", p(sig("flow.inlet_lps")), "#22d3ee"), s("FT-102 outlet", p(sig("flow.outlet_lps")), "#34d399")],
      pressure: [s("PT-101", p(sig("pressure.line_bar")), "#fbbf24", { area: true })],
      pump: [
        s("Running (1/0)", p(sig("pump.running")), "#22c55e", { step: true }),
        s("Motor power", p(sig("pump.power_kw")), "#a78bfa", { yAxisIndex: 1 }),
      ],
      disagreement: [s("LT-101 − LT-102", p((x) => x.derived.disagreement_m), "#f472b6", { area: true })],
      predicted: [
        s("Observed (LT-101)", p(sig("sensor.primary_level")), "#22d3ee"),
        s("Predicted from flows", p((x) => x.derived.predicted_level_m), "#a78bfa", { dashed: true }),
      ],
      residual: [
        s("Residual LT-101", p((x) => x.derived.mass_residual_m3?.["LT-101"]), "#22d3ee"),
        s("Residual LT-102", p((x) => x.derived.mass_residual_m3?.["LT-102"]), "#7dd3fc", { dashed: true }),
      ],
      score: [s("Anomaly score", p((x) => x.derived.anomaly_score), "#f59e0b", { area: true })],
    };
  }, [samples, epoch]);

  if (!live.state) return <Loading label="Connecting to the simulator" />;
  const mb = thr("PHYS-001") ?? 0.3;
  const dis = thr("PHYS-002") ?? 0.1;
  const run = live.state.run_id;

  return (
    <div>
      <PageHeader
        title="Live telemetry"
        subtitle="Streaming synthetic measurements and detector analytics. Scroll to zoom, drag to pan; pause to inspect history. Red markers show when alerts were raised."
        actions={
          <>
            {paused ? <Badge tone="warn">PAUSED VIEW</Badge> : <Badge tone="ok">STREAMING</Badge>}
            <Segmented label="Time window" value={win} onChange={setWin} options={WINDOWS} />
            <Button icon={paused ? Play : Pause} onClick={() => setPaused(!paused)}>{paused ? "Resume" : "Pause"}</Button>
            <a className="inline-flex h-9 items-center gap-2 rounded-lg bg-raised px-3.5 text-[13px] ring-1 ring-inset ring-line-strong hover:bg-line-strong/60"
              href={`/api/telemetry/export?run_id=${run}&format=csv`} download>
              <Download className="size-3.5" aria-hidden /> CSV
            </a>
            <a className="inline-flex h-9 items-center gap-2 rounded-lg bg-raised px-3.5 text-[13px] ring-1 ring-inset ring-line-strong hover:bg-line-strong/60"
              href={`/api/telemetry/export?run_id=${run}&format=json`} download>
              <Download className="size-3.5" aria-hidden /> JSON
            </a>
          </>
        }
      />
      {samples.length < 2 ? (
        <Card><Loading label="Waiting for telemetry" /></Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="1 · Tank level" subtitle="Redundant transmitters (simulated)">
            <TimeChart ariaLabel="Tank level" series={charts.level} unit="m" digits={3} markers={markers} />
          </Card>
          <Card title="2 · Inlet vs outlet flow" subtitle="FT-101 / FT-102 (simulated)">
            <TimeChart ariaLabel="Flows" series={charts.flows} unit="L/s" digits={2} markers={markers} />
          </Card>
          <Card title="3 · Line pressure" subtitle="PT-101 pump discharge (simulated)">
            <TimeChart ariaLabel="Pressure" series={charts.pressure} unit="bar" digits={3} markers={markers} />
          </Card>
          <Card title="4 · Pump operating state" subtitle="Run feedback YS-101 and motor power JT-101">
            <TimeChart ariaLabel="Pump state" series={charts.pump} unit="state" digits={0} yMin={0} yMax={1.2} y2={{ unit: "kW", digits: 2 }} markers={markers} />
          </Card>
          <Card title="5 · Sensor disagreement" subtitle={`3 s means · PHYS-002 tolerance ±${dis} m`}>
            <TimeChart ariaLabel="Sensor disagreement" series={charts.disagreement} unit="m" digits={3}
              thresholds={[{ value: dis, label: `+${dis}`, color: "#ef4444" }, { value: -dis, label: `−${dis}`, color: "#ef4444" }]} markers={markers} />
          </Card>
          <Card title="6 · Predicted vs observed level" subtitle="Prediction = level 60 s ago + ∫(Qin − Qout) dt / A">
            <TimeChart ariaLabel="Predicted vs observed level" series={charts.predicted} unit="m" digits={3} markers={markers} />
          </Card>
          <Card title="7 · Mass-balance residual" subtitle={`60 s window · PHYS-001 limit ±${mb} m³`}>
            <TimeChart ariaLabel="Mass balance residual" series={charts.residual} unit="m³" digits={3}
              thresholds={[{ value: mb, label: `+${mb}`, color: "#ef4444" }, { value: -mb, label: `−${mb}`, color: "#ef4444" }]} markers={markers} />
          </Card>
          <Card title="8 · Normalised rule severity" subtitle="max(|statistic| / threshold) across all rules">
            <TimeChart ariaLabel="Anomaly score" series={charts.score} unit="×thr" digits={2} yMin={0}
              thresholds={[{ value: 1, label: "threshold", color: "#ef4444" }]} markers={markers} />
          </Card>
        </div>
      )}
    </div>
  );
}
