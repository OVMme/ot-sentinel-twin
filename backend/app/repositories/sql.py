"""Repository: the only module that talks SQL. All queries are parameterised via SQLAlchemy.

The class depends on a SQLAlchemy ``sessionmaker`` only, so pointing OTST_DATABASE_URL at
PostgreSQL works without code changes (JSON columns map to JSON/JSONB).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.db import (
    Asset,
    AuditEvent,
    Base,
    DetectionEvent,
    DetectionRule,
    Incident,
    InvestigationNote,
    ScenarioEvent,
    SimulationConfiguration,
    SimulationRun,
    TelemetrySample,
    utcnow,
)
from app.simulation.params import SimulationConfig

ASSETS: list[dict[str, Any]] = [
    {
        "id": "TANK-001",
        "name": "Main storage tank",
        "kind": "tank",
        "description": "Vertical cylindrical tank, constant cross-section, overflow weir at the top.",
        "tags": ["LT-101", "LT-102"],
        "signals": [
            "tank.level_percent",
            "tank.level_meters",
            "sensor.primary_level",
            "sensor.secondary_level",
        ],
    },
    {
        "id": "XV-101",
        "name": "Inlet control valve",
        "kind": "valve",
        "description": "Modulating inlet valve with positioner and position feedback ZT-101.",
        "tags": ["XC-101", "ZT-101"],
        "signals": ["valve.inlet_command", "valve.inlet_position"],
    },
    {
        "id": "XV-102",
        "name": "Outlet control valve",
        "kind": "valve",
        "description": "Modulating outlet valve on the pump discharge with position feedback ZT-102.",
        "tags": ["XC-102", "ZT-102"],
        "signals": ["valve.outlet_command", "valve.outlet_position"],
    },
    {
        "id": "P-101",
        "name": "Transfer pump",
        "kind": "pump",
        "description": "Centrifugal transfer pump, fixed speed, run feedback YS-101 and motor power JT-101.",
        "tags": ["HS-101", "YS-101", "JT-101"],
        "signals": ["pump.command", "pump.running", "pump.power_kw"],
    },
    {
        "id": "FT-101",
        "name": "Inlet flow transmitter",
        "kind": "transmitter",
        "description": "Magnetic flow meter on the inlet pipeline.",
        "tags": ["FT-101"],
        "signals": ["flow.inlet_lps"],
    },
    {
        "id": "FT-102",
        "name": "Outlet flow transmitter",
        "kind": "transmitter",
        "description": "Magnetic flow meter on the outlet pipeline.",
        "tags": ["FT-102"],
        "signals": ["flow.outlet_lps"],
    },
    {
        "id": "PT-101",
        "name": "Line pressure transmitter",
        "kind": "transmitter",
        "description": "Pump discharge pressure, upstream of the outlet valve.",
        "tags": ["PT-101"],
        "signals": ["pressure.line_bar"],
    },
    {
        "id": "OUTLET-LINE",
        "name": "Outlet pipeline",
        "kind": "pipeline",
        "description": "Discharge pipeline from P-101 through XV-102.",
        "tags": ["FT-102", "PT-101"],
        "signals": [],
    },
    {
        "id": "INLET-LINE",
        "name": "Inlet pipeline",
        "kind": "pipeline",
        "description": "Supply pipeline through XV-101 into the tank.",
        "tags": ["FT-101"],
        "signals": [],
    },
    {
        "id": "PLC-001",
        "name": "Simulated controller",
        "kind": "controller",
        "description": "Simulated BPCS: PI level control LIC-101 with feed-forward, interlocks on LT-102.",
        "tags": ["LIC-101"],
        "signals": ["controller.mode", "controller.health", "controller.setpoint_percent"],
    },
]

ALERT_FIELDS = (
    "rule_id",
    "title",
    "category",
    "severity",
    "asset_id",
    "instance_key",
    "signal",
    "units",
    "status",
    "threshold",
    "observed_value",
    "expected_value",
    "statistic",
    "peak_score",
    "peak_observed",
    "peak_expected",
    "peak_explanation",
    "expected_label",
    "observed_label",
    "first_seen_t",
    "raised_t",
    "last_seen_t",
    "cleared_t",
    "first_seen",
    "raised_at",
    "last_seen",
    "cleared_at",
    "explanation",
    "evidence",
    "metrics",
    "incident_id",
)
INCIDENT_DETECTION_FIELDS = (
    "title",
    "classification",
    "confidence",
    "severity",
    "detection_state",
    "first_seen_t",
    "first_seen",
    "last_seen_t",
    "last_seen",
    "rule_ids",
    "assets",
    "summary",
    "expected_behavior",
    "observed_behavior",
    "classification_basis",
    "confidence_rationale",
    "alternatives",
    "recommended_steps",
    "timeline",
    "evidence",
)
SAMPLE_COLUMNS = (
    "lt101",
    "lt102",
    "ft101",
    "ft102",
    "pt101",
    "zt101",
    "zt102",
    "inlet_cmd",
    "outlet_cmd",
    "pump_cmd",
    "pump_running",
    "pump_kw",
    "setpoint",
    "true_level",
    "predicted_level",
    "residual_lt101",
    "residual_lt102",
    "disagreement",
    "anomaly_score",
)


def _row_dict(obj: Any, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}


class Repository:
    def __init__(self, session_factory: sessionmaker) -> None:
        self._sf = session_factory

    def session(self) -> Session:
        return self._sf()

    # ------------------------------------------------------------------ schema / seed
    @staticmethod
    def init_schema(engine: Engine) -> None:
        Base.metadata.create_all(engine)

    def seed_assets(self) -> None:
        with self.session() as s, s.begin():
            existing = set(s.scalars(select(Asset.id)))
            for a in ASSETS:
                if a["id"] not in existing:
                    s.add(Asset(**a))

    def list_assets(self) -> list[dict[str, Any]]:
        with self.session() as s:
            return [_row_dict(a) for a in s.scalars(select(Asset).order_by(Asset.id))]

    # ------------------------------------------------------------------ configuration
    def save_config(self, cfg: SimulationConfig, label: str = "user") -> int:
        with self.session() as s, s.begin():
            row = SimulationConfiguration(label=label, seed=cfg.seed, config=cfg.model_dump())
            s.add(row)
            s.flush()
            return int(row.id)

    def latest_config(self) -> tuple[int, SimulationConfig] | None:
        with self.session() as s:
            row = s.scalars(
                select(SimulationConfiguration).order_by(SimulationConfiguration.id.desc())
            ).first()
            if row is None:
                return None
            try:
                return int(row.id), SimulationConfig.model_validate(row.config)
            except ValueError:
                return None

    # ------------------------------------------------------------------ runs
    def create_run(
        self, run_id: str, config_id: int | None, epoch: str, seed: int, interval: float, mode: str
    ) -> None:
        with self.session() as s, s.begin():
            s.add(
                SimulationRun(
                    id=run_id,
                    config_id=config_id,
                    epoch=epoch,
                    seed=seed,
                    sample_interval_s=interval,
                    mode=mode,
                    status="running",
                )
            )

    def finish_run(self, run_id: str, status: str = "stopped") -> None:
        with self.session() as s, s.begin():
            s.execute(
                update(SimulationRun)
                .where(SimulationRun.id == run_id)
                .values(status=status, ended_at=utcnow())
            )

    def set_run_status(self, run_id: str, status: str) -> None:
        with self.session() as s, s.begin():
            s.execute(update(SimulationRun).where(SimulationRun.id == run_id).values(status=status))

    def mark_stale_runs(self) -> None:
        """Runs left 'running' by a previous process are closed on startup."""
        with self.session() as s, s.begin():
            s.execute(
                update(SimulationRun)
                .where(SimulationRun.status.in_(["running", "paused"]))
                .values(status="interrupted", ended_at=utcnow())
            )

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.session() as s:
            runs = list(
                s.scalars(select(SimulationRun).order_by(SimulationRun.started_at.desc()).limit(limit))
            )
            inc_counts = dict(
                s.execute(select(Incident.run_id, func.count()).group_by(Incident.run_id)).all()
            )
            det_counts = dict(
                s.execute(select(DetectionEvent.run_id, func.count()).group_by(DetectionEvent.run_id)).all()
            )
            scen = s.execute(
                select(ScenarioEvent.run_id, ScenarioEvent.scenario_id).where(ScenarioEvent.kind == "started")
            ).all()
            scen_map: dict[str, list[str]] = {}
            for rid, sid in scen:
                scen_map.setdefault(rid, [])
                if sid not in scen_map[rid]:
                    scen_map[rid].append(sid)
            out = []
            for r in runs:
                d = _row_dict(r)
                d["incident_count"] = inc_counts.get(r.id, 0)
                d["detection_count"] = det_counts.get(r.id, 0)
                d["scenarios"] = scen_map.get(r.id, [])
                out.append(d)
            return out

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            r = s.get(SimulationRun, run_id)
            return None if r is None else _row_dict(r)

    def enforce_retention(self, keep: int, protect: str | None = None) -> int:
        with self.session() as s, s.begin():
            ids = list(s.scalars(select(SimulationRun.id).order_by(SimulationRun.started_at.desc())))
            victims = [i for i in ids[keep:] if i != protect]
            for rid in victims:
                # explicit deletes keep this fast and independent of ON DELETE support
                s.execute(delete(TelemetrySample).where(TelemetrySample.run_id == rid))
                s.execute(delete(ScenarioEvent).where(ScenarioEvent.run_id == rid))
                s.execute(delete(DetectionEvent).where(DetectionEvent.run_id == rid))
                inc_ids = list(s.scalars(select(Incident.id).where(Incident.run_id == rid)))
                if inc_ids:
                    s.execute(delete(InvestigationNote).where(InvestigationNote.incident_id.in_(inc_ids)))
                s.execute(delete(Incident).where(Incident.run_id == rid))
                s.execute(delete(SimulationRun).where(SimulationRun.id == rid))
            return len(victims)

    # ------------------------------------------------------------------ batch writes from the runtime
    def write_batch(
        self,
        run_id: str,
        samples: list[dict[str, Any]],
        scenario_events: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        incidents: list[dict[str, Any]],
        max_samples: int,
    ) -> None:
        with self.session() as s, s.begin():
            # incidents first (alerts reference them)
            for inc in incidents:
                existing = s.get(Incident, inc["id"])
                if existing is None:
                    s.add(
                        Incident(
                            run_id=run_id, id=inc["id"], **{k: inc[k] for k in INCIDENT_DETECTION_FIELDS}
                        )
                    )
                else:
                    for k in INCIDENT_DETECTION_FIELDS:
                        setattr(existing, k, inc[k])
                    existing.updated_at = utcnow()
            s.flush()
            for a in alerts:
                existing_a = s.get(DetectionEvent, a["id"])
                values = {k: a.get(k) for k in ALERT_FIELDS}
                if existing_a is None:
                    s.add(DetectionEvent(id=a["id"], run_id=run_id, **values))
                else:
                    for k, v in values.items():
                        setattr(existing_a, k, v)
            for ev in scenario_events:
                s.add(
                    ScenarioEvent(
                        run_id=run_id,
                        scenario_id=ev["scenario_id"],
                        kind=ev["kind"],
                        sim_time_s=ev["t"],
                        ts=ev["ts"],
                        description=ev["description"],
                        ground_truth=ev.get("ground_truth", {}),
                    )
                )
            if samples:
                s.bulk_insert_mappings(TelemetrySample, [_sample_row(run_id, x) for x in samples])
                last = samples[-1]
                run = s.get(SimulationRun, run_id)
                if run is not None:
                    run.sample_count = (run.sample_count or 0) + len(samples)
                    run.sim_duration_s = float(last["t"])
                    if run.sample_count > max_samples:
                        cutoff = int(last["seq"]) - max_samples
                        s.execute(
                            delete(TelemetrySample).where(
                                TelemetrySample.run_id == run_id, TelemetrySample.seq <= cutoff
                            )
                        )
                        run.sample_count = max_samples
                        run.first_seq = cutoff + 1
                        run.truncated = True

    # ------------------------------------------------------------------ telemetry queries
    def telemetry_page(self, run_id: str, from_seq: int, limit: int, full: bool) -> list[dict[str, Any]]:
        with self.session() as s:
            q = (
                select(TelemetrySample)
                .where(TelemetrySample.run_id == run_id, TelemetrySample.seq >= from_seq)
                .order_by(TelemetrySample.seq)
                .limit(limit)
            )
            rows = list(s.scalars(q))
            if full:
                return [r.payload for r in rows]
            return [
                {"seq": r.seq, "t": r.sim_time_s, "ts": r.ts, **{c: getattr(r, c) for c in SAMPLE_COLUMNS}}
                for r in rows
            ]

    def replay_columns(self, run_id: str, from_seq: int, limit: int) -> dict[str, list[Any]]:
        cols = ["seq", "sim_time_s", "ts", *SAMPLE_COLUMNS, "mode", "scenario_id"]
        with self.session() as s:
            q = (
                select(*[getattr(TelemetrySample, c) for c in cols])
                .where(TelemetrySample.run_id == run_id, TelemetrySample.seq >= from_seq)
                .order_by(TelemetrySample.seq)
                .limit(limit)
            )
            rows = s.execute(q).all()
        out: dict[str, list[Any]] = {c: [] for c in cols}
        for r in rows:
            for c, v in zip(cols, r, strict=True):
                out[c].append(v)
        return out

    def sample_payload(self, run_id: str, seq: int) -> dict[str, Any] | None:
        with self.session() as s:
            row = s.scalars(
                select(TelemetrySample).where(TelemetrySample.run_id == run_id, TelemetrySample.seq == seq)
            ).first()
            return None if row is None else row.payload

    def samples_window(
        self, run_id: str, t_from: float, t_to: float, limit: int = 5000
    ) -> list[dict[str, Any]]:
        with self.session() as s:
            q = (
                select(TelemetrySample)
                .where(
                    TelemetrySample.run_id == run_id,
                    TelemetrySample.sim_time_s >= t_from,
                    TelemetrySample.sim_time_s <= t_to,
                )
                .order_by(TelemetrySample.seq)
                .limit(limit)
            )
            return [
                {"seq": r.seq, "t": r.sim_time_s, "ts": r.ts, **{c: getattr(r, c) for c in SAMPLE_COLUMNS}}
                for r in s.scalars(q)
            ]

    # ------------------------------------------------------------------ rules
    def sync_rules(self, descriptions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Insert missing rules; return stored configs (user edits survive restarts)."""
        with self.session() as s, s.begin():
            stored = {r.rule_id: r for r in s.scalars(select(DetectionRule))}
            for d in descriptions:
                if d["rule_id"] not in stored:
                    s.add(
                        DetectionRule(
                            rule_id=d["rule_id"],
                            title=d["title"],
                            category=d["category"],
                            description=d["description"],
                            methodology=d["methodology"],
                            config=d["config"],
                        )
                    )
                else:
                    row = stored[d["rule_id"]]
                    row.title, row.description, row.methodology = (
                        d["title"],
                        d["description"],
                        d["methodology"],
                    )
            s.flush()
            return {r.rule_id: dict(r.config) for r in s.scalars(select(DetectionRule))}

    def save_rule_config(self, rule_id: str, config: dict[str, Any]) -> None:
        with self.session() as s, s.begin():
            s.execute(
                update(DetectionRule)
                .where(DetectionRule.rule_id == rule_id)
                .values(config=config, updated_at=utcnow())
            )

    # ------------------------------------------------------------------ detections
    def list_detections(
        self,
        run_id: str | None,
        status: str | None,
        rule_id: str | None,
        incident_id: str | None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[dict[str, Any]]]:
        with self.session() as s:
            conds = []
            if run_id:
                conds.append(DetectionEvent.run_id == run_id)
            if status:
                conds.append(DetectionEvent.status == status)
            if rule_id:
                conds.append(DetectionEvent.rule_id == rule_id)
            if incident_id:
                conds.append(DetectionEvent.incident_id == incident_id)
            total = s.scalar(select(func.count()).select_from(DetectionEvent).where(*conds)) or 0
            rows = s.scalars(
                select(DetectionEvent)
                .where(*conds)
                .order_by(DetectionEvent.raised_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return int(total), [_row_dict(r) for r in rows]

    # ------------------------------------------------------------------ incidents
    def list_incidents(
        self, run_id: str | None, status: str | None, classification: str | None, limit: int, offset: int
    ) -> tuple[int, list[dict[str, Any]]]:
        with self.session() as s:
            conds = []
            if run_id:
                conds.append(Incident.run_id == run_id)
            if status:
                conds.append(Incident.status == status)
            if classification:
                conds.append(Incident.classification == classification)
            total = s.scalar(select(func.count()).select_from(Incident).where(*conds)) or 0
            rows = s.scalars(
                select(Incident)
                .where(*conds)
                .order_by(Incident.first_seen.desc())
                .limit(limit)
                .offset(offset)
            )
            return int(total), [_row_dict(r, exclude=("timeline", "evidence")) for r in rows]

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self.session() as s:
            inc = s.get(Incident, incident_id)
            if inc is None:
                return None
            d = _row_dict(inc)
            d["notes"] = [_row_dict(n) for n in inc.notes]
            d["detections"] = [
                _row_dict(x)
                for x in s.scalars(
                    select(DetectionEvent)
                    .where(DetectionEvent.incident_id == incident_id)
                    .order_by(DetectionEvent.raised_t)
                )
            ]
            d["scenario_events"] = [
                _row_dict(x)
                for x in s.scalars(
                    select(ScenarioEvent)
                    .where(ScenarioEvent.run_id == inc.run_id)
                    .order_by(ScenarioEvent.sim_time_s)
                )
            ]
            d["audit"] = [
                _row_dict(x)
                for x in s.scalars(
                    select(AuditEvent)
                    .where(AuditEvent.target == f"incident:{incident_id}")
                    .order_by(AuditEvent.id)
                )
            ]
            return d

    def update_incident(self, incident_id: str, **values: Any) -> bool:
        with self.session() as s, s.begin():
            inc = s.get(Incident, incident_id)
            if inc is None:
                return False
            for k, v in values.items():
                setattr(inc, k, v)
            inc.updated_at = utcnow()
            return True

    def add_note(self, incident_id: str, author: str, text: str) -> dict[str, Any] | None:
        with self.session() as s, s.begin():
            if s.get(Incident, incident_id) is None:
                return None
            note = InvestigationNote(incident_id=incident_id, author=author, text=text)
            s.add(note)
            s.flush()
            return _row_dict(note)

    # ------------------------------------------------------------------ audit
    def audit(self, actor: str, action: str, target: str = "", details: dict[str, Any] | None = None) -> None:
        with self.session() as s, s.begin():
            s.add(AuditEvent(actor=actor, action=action, target=target, details=details or {}))

    def list_audit(self, limit: int, offset: int) -> tuple[int, list[dict[str, Any]]]:
        with self.session() as s:
            total = s.scalar(select(func.count()).select_from(AuditEvent)) or 0
            rows = s.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit).offset(offset))
            return int(total), [_row_dict(r) for r in rows]

    def scenario_events(self, run_id: str) -> list[dict[str, Any]]:
        with self.session() as s:
            return [
                _row_dict(x)
                for x in s.scalars(
                    select(ScenarioEvent)
                    .where(ScenarioEvent.run_id == run_id)
                    .order_by(ScenarioEvent.sim_time_s)
                )
            ]

    # ------------------------------------------------------------------ id counters
    def max_counter(self, kind: str) -> int:
        model = DetectionEvent if kind == "alert" else Incident
        with self.session() as s:
            ids = s.scalars(select(model.id)).all()
        best = 0
        for i in ids:
            try:
                best = max(best, int(str(i).rsplit("-", 1)[-1]))
            except ValueError:
                continue
        return best


def _sample_row(run_id: str, x: dict[str, Any]) -> dict[str, Any]:
    sig = x["signals"]

    def v(name: str) -> Any:
        r = sig.get(name)
        return None if r is None else r.get("v")

    d = x.get("derived", {}) or {}
    res = d.get("mass_residual_m3") or {}
    truth = x.get("truth") or {}
    return {
        "run_id": run_id,
        "seq": x["seq"],
        "sim_time_s": x["t"],
        "ts": x["ts"],
        "lt101": v("sensor.primary_level"),
        "lt102": v("sensor.secondary_level"),
        "ft101": v("flow.inlet_lps"),
        "ft102": v("flow.outlet_lps"),
        "pt101": v("pressure.line_bar"),
        "zt101": v("valve.inlet_position"),
        "zt102": v("valve.outlet_position"),
        "inlet_cmd": v("valve.inlet_command"),
        "outlet_cmd": v("valve.outlet_command"),
        "pump_cmd": v("pump.command"),
        "pump_running": v("pump.running"),
        "pump_kw": v("pump.power_kw"),
        "setpoint": v("controller.setpoint_percent"),
        "mode": v("controller.mode"),
        "true_level": truth.get("level_m"),
        "predicted_level": d.get("predicted_level_m"),
        "residual_lt101": res.get("LT-101"),
        "residual_lt102": res.get("LT-102"),
        "disagreement": d.get("disagreement_m"),
        "anomaly_score": d.get("anomaly_score"),
        "scenario_id": x.get("scenario_id"),
        "payload": x,
    }
