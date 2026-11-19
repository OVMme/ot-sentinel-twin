import type { Alert, Sample } from "../types/api";
import type { Marker } from "../components/charts/TimeChart";

/** Absolute epoch (ms) of the run, derived from a sample's timestamp and its sim time. */
export function runEpochMs(s: Sample | undefined | null): number {
  if (!s) return 0;
  return Date.parse(s.ts) - s.t * 1000;
}

export type Point = [number, number | null];

export function pick(samples: Sample[], epoch: number, f: (s: Sample) => unknown): Point[] {
  const out: Point[] = new Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = samples[i];
    const v = f(s);
    out[i] = [epoch + s.t * 1000, typeof v === "number" && Number.isFinite(v) ? v : typeof v === "boolean" ? (v ? 1 : 0) : null];
  }
  return out;
}

export const sig = (name: string) => (s: Sample) => s.signals[name]?.v;

export function alertMarkers(alerts: Alert[], epoch: number, fromT: number, rules?: string[]): Marker[] {
  return alerts
    .filter((a) => a.raised_t >= fromT && (!rules || rules.includes(a.rule_id)))
    .slice(0, 12)
    .map((a) => ({ x: epoch + a.raised_t * 1000, label: a.rule_id, color: a.severity === "high" ? "#ef4444" : "#f59e0b" }));
}
