import { ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Card, ClassificationBadge, EmptyState, ErrorState, Loading, PageHeader, SeverityBadge, StatusBadge } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useLive } from "../hooks/useLive";
import { dateTimeOf, duration } from "../lib/format";
import type { Incident, Page } from "../types/api";

export default function IncidentsPage() {
  const { incidents: liveIncidents } = useLive();
  const [status, setStatus] = useState("");
  const [cls, setCls] = useState("");
  const q = new URLSearchParams({ limit: "100" });
  if (status) q.set("status", status);
  if (cls) q.set("classification", cls);
  const list = useApi<Page<Incident>>(`/api/incidents?${q.toString()}`);
  const liveKey = liveIncidents.map((i) => `${i.id}:${i.alert_ids?.length}:${i.detection_state}`).join("|");
  useEffect(() => {
    void list.reload();
  }, [liveKey]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div>
      <PageHeader
        title="Incident investigation"
        subtitle="Correlated detections grouped into incidents. Classification is an evidence-based hypothesis — an anomaly is never automatically called an attack."
        actions={
          <>
            <select aria-label="Filter by status" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All statuses</option>
              {["open", "acknowledged", "investigating", "reviewed", "closed"].map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select aria-label="Filter by classification" className="input" value={cls} onChange={(e) => setCls(e.target.value)}>
              <option value="">All classifications</option>
              <option value="suspected_manipulation">Suspected manipulation</option>
              <option value="equipment_fault">Equipment fault</option>
              <option value="physical_anomaly">Physical anomaly</option>
              <option value="data_quality">Data-quality issue</option>
            </select>
          </>
        }
      />
      <Card>
        {list.loading && !list.data ? <Loading /> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : !list.data?.items.length ? (
          <EmptyState icon={ShieldAlert} title="No incidents">
            Incidents appear when detection rules raise alerts. Start a scenario in the Scenario Lab to create a synthetic one.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-left text-[13px]">
              <thead className="text-xs text-muted">
                <tr className="border-b border-line">
                  <th className="py-2 font-medium">Incident</th>
                  <th className="py-2 font-medium">Classification</th>
                  <th className="py-2 font-medium">Severity</th>
                  <th className="py-2 font-medium">Status</th>
                  <th className="py-2 font-medium">Rules</th>
                  <th className="py-2 font-medium">Assets</th>
                  <th className="py-2 font-medium">First seen (sim)</th>
                  <th className="py-2 font-medium">Duration</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {list.data.items.map((i) => (
                  <tr key={i.id} className="hover:bg-white/[0.02]">
                    <td className="py-2.5 pr-3">
                      <Link to={`/incidents/${i.id}`} className="font-medium text-text hover:text-cyan">
                        <span className="num text-cyan">{i.id}</span> · {i.title}
                      </Link>
                      {i.detection_state === "active" && <Badge tone="crit" className="ml-2">LIVE</Badge>}
                    </td>
                    <td className="py-2.5 pr-2"><ClassificationBadge value={i.classification} /></td>
                    <td className="py-2.5 pr-2"><SeverityBadge severity={i.severity} /></td>
                    <td className="py-2.5 pr-2"><StatusBadge status={i.status} /></td>
                    <td className="num py-2.5 pr-2 text-xs text-muted">{i.rule_ids.join(", ")}</td>
                    <td className="num py-2.5 pr-2 text-xs text-muted">{i.assets.join(", ")}</td>
                    <td className="num py-2.5 pr-2 text-xs">{dateTimeOf(i.first_seen)}</td>
                    <td className="num py-2.5 text-xs text-muted">{duration(i.last_seen_t - i.first_seen_t)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
