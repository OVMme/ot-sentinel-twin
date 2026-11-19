import { ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { cn, simClock } from "../lib/format";
import type { Alert } from "../types/api";
import { Badge, EmptyState, SeverityBadge } from "./ui";

export function AlertList({ alerts, limit = 8, emptyText = "No detections. Every rule is within its physical tolerance." }: {
  alerts: Alert[];
  limit?: number;
  emptyText?: string;
}) {
  if (!alerts.length) return <EmptyState icon={ShieldCheck} title="All clear">{emptyText}</EmptyState>;
  return (
    <ul className="divide-y divide-line" aria-label="Detections">
      {alerts.slice(0, limit).map((a) => (
        <li key={a.id} className="py-2.5">
          <div className="flex flex-wrap items-center gap-1.5">
            <SeverityBadge severity={a.severity} />
            <Badge tone={a.category === "data_quality" ? "neutral" : "cyan"}>{a.rule_id}</Badge>
            <span className="text-[13px] font-medium">{a.title}</span>
            <span className="num text-xs text-muted">· {a.instance_key}</span>
            <span className={cn("ml-auto num text-[11px]", a.status === "active" ? "text-crit" : "text-faint")}>
              {a.status === "active" ? "ACTIVE" : "cleared"} · T+{simClock(a.raised_t)}
            </span>
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-muted">{a.peak_explanation || a.explanation}</p>
          {a.incident_id && (
            <Link to={`/incidents/${a.incident_id}`} className="mt-1 inline-block text-xs text-cyan hover:underline">
              {a.incident_id} →
            </Link>
          )}
        </li>
      ))}
    </ul>
  );
}
