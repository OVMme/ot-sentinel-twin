import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, wsUrl } from "../services/api";
import type { Alert, Incident, Sample, ScenarioEventRow, SimState } from "../types/api";

/** Maximum samples kept in the browser (10 min at 2 Hz). Bounded to avoid memory growth. */
export const MAX_SAMPLES = 1200;
const MAX_ALERTS = 300;
const FLUSH_MS = 250;

export type Connection = "connecting" | "open" | "closed";

interface Snapshot {
  samples: Sample[];
  latest: Sample | null;
  alerts: Alert[];
  incidents: Incident[];
  scenarioEvents: ScenarioEventRow[];
  version: number;
}

export interface LiveContextValue extends Snapshot {
  connection: Connection;
  state: SimState | null;
  activeAlerts: Alert[];
  setSimState: (s: SimState) => void;
  refreshState: () => Promise<void>;
  reconnects: number;
}

const LiveContext = createContext<LiveContextValue | null>(null);

type Message =
  | { type: "hello"; data: { state: SimState; recent: Sample[]; active_alerts: Alert[]; recent_alerts?: Alert[] } }
  | { type: "telemetry"; data: Sample }
  | { type: "alert"; change: string; data: Alert }
  | { type: "incident"; change: string; data: Incident }
  | { type: "state"; data: SimState }
  | { type: "scenario_event"; data: ScenarioEventRow }
  | { type: "reset"; data: { run_id: string } };

export function LiveProvider({ children }: { children: ReactNode }) {
  const [connection, setConnection] = useState<Connection>("connecting");
  const [state, setState] = useState<SimState | null>(null);
  const [reconnects, setReconnects] = useState(0);
  const [snap, setSnap] = useState<Snapshot>({
    samples: [],
    latest: null,
    alerts: [],
    incidents: [],
    scenarioEvents: [],
    version: 0,
  });

  const buffer = useRef<Sample[]>([]);
  const alerts = useRef<Map<string, Alert>>(new Map());
  const incidents = useRef<Map<string, Incident>>(new Map());
  const scenarioEvents = useRef<ScenarioEventRow[]>([]);
  const runId = useRef<string | null>(null);
  const flushTimer = useRef<number | null>(null);
  const version = useRef(0);

  const flush = useCallback(() => {
    flushTimer.current = null;
    version.current += 1;
    const b = buffer.current;
    setSnap({
      samples: b.slice(),
      latest: b.length ? b[b.length - 1] : null,
      alerts: [...alerts.current.values()].sort((a, z) => z.raised_t - a.raised_t),
      incidents: [...incidents.current.values()].sort((a, z) => z.first_seen_t - a.first_seen_t),
      scenarioEvents: scenarioEvents.current.slice(-100),
      version: version.current,
    });
  }, []);

  const schedule = useCallback(() => {
    if (flushTimer.current == null) flushTimer.current = window.setTimeout(flush, FLUSH_MS);
  }, [flush]);

  const clearRun = useCallback((newRun: string | null) => {
    runId.current = newRun;
    buffer.current = [];
    alerts.current.clear();
    incidents.current.clear();
    scenarioEvents.current = [];
  }, []);

  const pushSample = useCallback((s: Sample) => {
    if (runId.current && s.run_id !== runId.current) clearRun(s.run_id);
    runId.current = s.run_id;
    const b = buffer.current;
    if (b.length && s.seq <= b[b.length - 1].seq) return; // duplicate after reconnect
    b.push(s);
    if (b.length > MAX_SAMPLES + 50) b.splice(0, b.length - MAX_SAMPLES);
  }, [clearRun]);

  const backfill = useCallback(async (run: string) => {
    try {
      const r = await api.get<{ run_id: string; samples: Sample[] }>(`/api/telemetry/recent?limit=${MAX_SAMPLES}`);
      if (r.run_id !== run || !r.samples.length) return;
      const firstLive = buffer.current[0]?.seq ?? Number.POSITIVE_INFINITY;
      const older = r.samples.filter((s) => s.seq < firstLive);
      buffer.current = [...older, ...buffer.current].slice(-MAX_SAMPLES);
      schedule();
    } catch {
      /* backfill is best-effort */
    }
  }, [schedule]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let retryTimer: number | null = null;

    const connect = () => {
      setConnection("connecting");
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        attempt = 0;
        setConnection("open");
      };
      ws.onmessage = (ev) => {
        let msg: Message;
        try {
          msg = JSON.parse(ev.data as string) as Message;
        } catch {
          return;
        }
        switch (msg.type) {
          case "hello": {
            clearRun(msg.data.state.run_id);
            msg.data.recent.forEach(pushSample);
            (msg.data.recent_alerts ?? []).forEach((a) => alerts.current.set(a.id, a));
            msg.data.active_alerts.forEach((a) => alerts.current.set(a.id, a));
            setState(msg.data.state);
            void backfill(msg.data.state.run_id);
            schedule();
            break;
          }
          case "telemetry":
            pushSample(msg.data);
            schedule();
            break;
          case "alert":
            alerts.current.set(msg.data.id, msg.data);
            if (alerts.current.size > MAX_ALERTS) {
              const victim = [...alerts.current.values()].find((a) => a.status !== "active");
              if (victim) alerts.current.delete(victim.id);
            }
            schedule();
            break;
          case "incident":
            incidents.current.set(msg.data.id, msg.data);
            schedule();
            break;
          case "scenario_event":
            scenarioEvents.current.push(msg.data);
            schedule();
            break;
          case "state":
            setState(msg.data);
            break;
          case "reset":
            clearRun(msg.data.run_id);
            schedule();
            break;
        }
      };
      ws.onclose = () => {
        setConnection("closed");
        if (closed) return;
        attempt += 1;
        setReconnects((r) => r + 1);
        retryTimer = window.setTimeout(connect, Math.min(1000 * 2 ** Math.min(attempt - 1, 4), 10000));
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      closed = true;
      if (retryTimer != null) window.clearTimeout(retryTimer);
      if (flushTimer.current != null) window.clearTimeout(flushTimer.current);
      ws?.close();
    };
  }, [backfill, clearRun, pushSample, schedule]);

  const refreshState = useCallback(async () => {
    try {
      setState(await api.get<SimState>("/api/simulation/state"));
    } catch {
      /* surfaced through connection state */
    }
  }, []);

  const value = useMemo<LiveContextValue>(
    () => ({
      ...snap,
      connection,
      state,
      activeAlerts: snap.alerts.filter((a) => a.status === "active"),
      setSimState: setState,
      refreshState,
      reconnects,
    }),
    [snap, connection, state, refreshState, reconnects],
  );
  return <LiveContext.Provider value={value}>{children}</LiveContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components -- provider + hook live together by design
export function useLive(): LiveContextValue {
  const ctx = useContext(LiveContext);
  if (!ctx) throw new Error("useLive must be used inside <LiveProvider>");
  return ctx;
}
