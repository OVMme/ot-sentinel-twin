import { Activity, Droplets, Gauge, Play, Radar, ShieldAlert, Waves } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";
import { AlertList } from "../components/AlertList";
import { PlantDiagram } from "../components/PlantDiagram";
import { TimeChart } from "../components/charts/TimeChart";
import { Badge, Button, Card, Loading, Meter, PageHeader, Stat } from "../components/ui";
import { useAction } from "../hooks/useAction";
import { useLive } from "../hooks/useLive";
import { CLASSIFICATION_LABEL, num } from "../lib/format";
import { alertAnchors, viewFromSample } from "../lib/plant";
import { alertMarkers, pick, runEpochMs, sig } from "../lib/series";
import { api } from "../services/api";
import type { SimState } from "../types/api";

export default function Overview() {
  const { latest, samples, state, activeAlerts, alerts, incidents, setSimState } = useLive();
  const { run, busy } = useAction();
  const h = state?.config.tank_height_m ?? 5;
  const view = viewFromSample(latest, h);
  const anchors = useMemo(() => alertAnchors(activeAlerts), [activeAlerts]);
  const recent = useMemo(() => samples.slice(-600), [samples]);
  const epoch = runEpochMs(latest);
  const fromT = recent[0]?.t ?? 0;
  const levelSeries = useMemo(
    () => [
      { name: "LT-101 (primary)", data: pick(recent, epoch, sig("sensor.primary_level")), color: "#22d3ee", area: true },
      { name: "LT-102 (secondary)", data: pick(recent, epoch, sig("sensor.secondary_level")), color: "#7dd3fc", dashed: true },
      { name: "Model prediction", data: pick(recent, epoch, (s) => s.derived.predicted_level_m), color: "#a78bfa", width: 1.2 },
    ],
    [recent, epoch],
  );
  const scoreSeries = useMemo(
    () => [{ name: "Anomaly score", data: pick(recent, epoch, (s) => s.derived.anomaly_score), color: "#f59e0b", area: true }],
    [recent, epoch],
  );
  const markers = useMemo(() => alertMarkers(alerts, epoch, fromT), [alerts, epoch, fromT]);

  if (!state) return <Loading label="Connecting to the simulator" />;
  const lt1 = view?.levelPrimaryM != null ? (view.levelPrimaryM / h) * 100 : null;
  const lt2 = view?.levelSecondaryM != null ? (view.levelSecondaryM / h) * 100 : null;
  const latestIncident = incidents[0];
  const det = state.detection;

  return (
    <div>
      <PageHeader
        title="Plant overview"
        subtitle="Synthetic water-treatment storage tank with physics-consistency monitoring. Every value below comes from the running simulation."
        actions={
          state.status !== "running" && !state.read_only ? (
            <Button
              variant="primary"
              icon={Play}
              busy={busy === "start"}
              onClick={() => run("start", async () => setSimState(await api.post<SimState>("/api/simulation/start")))}
            >
              Start simulation
            </Button>
          ) : undefined
        }
      />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Tank level (LT-101)" value={num(lt1, 1)} unit="%" icon={Droplets} sub={<>LT-102 {num(lt2, 1)} %</>} />
        <Stat label="Inlet flow (FT-101)" value={num(view?.flowIn, 1)} unit="L/s" icon={Waves} sub={`XV-101 at ${num(view?.inletPos, 0)} %`} />
        <Stat label="Outlet flow (FT-102)" value={num(view?.flowOut, 1)} unit="L/s" icon={Waves} sub={`XV-102 at ${num(view?.outletPos, 0)} %`} />
        <Stat label="Line pressure (PT-101)" value={num(view?.pressure, 2)} unit="bar" icon={Gauge} sub={view?.pumpRunning ? `P-101 running · ${num(view.pumpKw, 1)} kW` : "P-101 stopped"} />
        <Stat
          label="Controller"
          value={(state.mode ?? "—").toUpperCase()}
          tone={state.mode === "manual" ? "warn" : "ok"}
          icon={Activity}
          sub={`SP ${num(state.setpoint_pct, 0)} % · health ${state.controller_health}`}
        />
        <Stat
          label="Active alerts"
          value={activeAlerts.length}
          tone={activeAlerts.length ? "crit" : "ok"}
          icon={ShieldAlert}
          sub={activeAlerts.length ? activeAlerts.map((a) => a.rule_id).slice(0, 3).join(", ") : "No physical inconsistencies"}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title="Digital twin"
          subtitle="Liquid = simulator truth · markers = what the level transmitters report"
          actions={<Link to="/plant" className="text-xs text-cyan hover:underline">Open twin →</Link>}
        >
          {view ? <PlantDiagram view={view} anchors={anchors} className="w-full" /> : <Loading label="Waiting for telemetry" />}
        </Card>
        <div className="flex flex-col gap-4">
          <Card title="Detection engine" icon={Radar}>
            <div className="space-y-3 text-[13px]">
              <div className="flex items-center justify-between">
                <span className="text-muted">Status</span>
                <Badge tone={det.status === "running" ? (det.warmup_complete ? "ok" : "warn") : "neutral"}>
                  {det.status === "running" ? (det.warmup_complete ? "EVALUATING" : "WARMING UP") : "IDLE"}
                </Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Rules enabled</span>
                <span className="num">{det.rules_enabled} / {det.rules_total}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Samples evaluated</span>
                <span className="num">{det.samples_processed.toLocaleString()}</span>
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-muted">Anomaly score (1.0 = threshold)</span>
                  <span className="num">{num(det.anomaly_score, 2)}</span>
                </div>
                <Meter value={det.anomaly_score} max={1} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-muted">Simulation loop lag</span>
                <span className="num">{num(state.health.loop_lag_ms, 1)} ms</span>
              </div>
            </div>
          </Card>
          {state.scenario ? (
            <Card title="Active scenario" subtitle="Simulator ground truth — hidden from the detection engine">
              <div className="flex items-center gap-2">
                <Badge tone="warn">{state.scenario.code}</Badge>
                <span className="text-sm font-medium">{state.scenario.title}</span>
              </div>
              <p className="mt-2 text-xs text-muted">
                Phase {state.scenario.phase} · elapsed {num(state.scenario.elapsed_s, 0)} s · expected:{" "}
                {state.scenario.ground_truth.expected_rules.join(", ") || "no alerts"}
              </p>
              <Link to="/scenarios" className="mt-2 inline-block text-xs text-cyan hover:underline">Scenario lab →</Link>
            </Card>
          ) : latestIncident ? (
            <Card title="Latest incident">
              <Link to={`/incidents/${latestIncident.id}`} className="text-sm font-medium hover:text-cyan">
                {latestIncident.id} · {latestIncident.title}
              </Link>
              <p className="mt-1 text-xs text-muted">{CLASSIFICATION_LABEL[latestIncident.classification]} · {latestIncident.confidence} confidence</p>
            </Card>
          ) : null}
          <Card title="Recent detections" className="flex-1">
            <AlertList alerts={alerts} limit={4} />
          </Card>
        </div>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card title="Tank level — reported vs model" subtitle="Model prediction = level 60 s ago + integrated measured flows / tank area">
          <TimeChart ariaLabel="Tank level chart" series={levelSeries} unit="m" digits={3} markers={markers} />
        </Card>
        <Card title="Normalised anomaly score" subtitle="Maximum rule statistic divided by its threshold (simulated data)">
          <TimeChart ariaLabel="Anomaly score chart" series={scoreSeries} unit="×thr" yMin={0} thresholds={[{ value: 1, label: "threshold", color: "#ef4444" }]} markers={markers} />
        </Card>
      </div>
    </div>
  );
}
