"""SQLAlchemy ORM schema. SQLite by default; the schema is portable to PostgreSQL."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class SimulationConfiguration(Base):
    __tablename__ = "simulation_configurations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)
    label: Mapped[str] = mapped_column(String(120), default="default")
    seed: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)


class SimulationRun(Base):
    __tablename__ = "simulation_runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    config_id: Mapped[int | None] = mapped_column(ForeignKey("simulation_configurations.id"), nullable=True)
    started_at: Mapped[str] = mapped_column(String(32), default=utcnow, index=True)
    ended_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    epoch: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="running")
    mode: Mapped[str] = mapped_column(String(16), default="live")
    seed: Mapped[int] = mapped_column(Integer)
    sample_interval_s: Mapped[float] = mapped_column(Float)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seq: Mapped[int] = mapped_column(Integer, default=0)
    sim_duration_s: Mapped[float] = mapped_column(Float, default=0.0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)

    samples = relationship("TelemetrySample", cascade="all, delete-orphan", passive_deletes=True)
    scenario_events = relationship("ScenarioEvent", cascade="all, delete-orphan", passive_deletes=True)
    detections = relationship("DetectionEvent", cascade="all, delete-orphan", passive_deletes=True)
    incidents = relationship("Incident", cascade="all, delete-orphan", passive_deletes=True)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    signals: Mapped[list] = mapped_column(JSON, default=list)


class TelemetrySample(Base):
    """Wide row per scan: indexed numeric columns for fast charts + full JSON payload for replay."""

    __tablename__ = "telemetry_samples"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_sample_run_seq"),
        Index("ix_sample_run_t", "run_id", "sim_time_s"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer)
    sim_time_s: Mapped[float] = mapped_column(Float)
    ts: Mapped[str] = mapped_column(String(32))
    lt101: Mapped[float | None] = mapped_column(Float, nullable=True)
    lt102: Mapped[float | None] = mapped_column(Float, nullable=True)
    ft101: Mapped[float | None] = mapped_column(Float, nullable=True)
    ft102: Mapped[float | None] = mapped_column(Float, nullable=True)
    pt101: Mapped[float | None] = mapped_column(Float, nullable=True)
    zt101: Mapped[float | None] = mapped_column(Float, nullable=True)
    zt102: Mapped[float | None] = mapped_column(Float, nullable=True)
    inlet_cmd: Mapped[float | None] = mapped_column(Float, nullable=True)
    outlet_cmd: Mapped[float | None] = mapped_column(Float, nullable=True)
    pump_cmd: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pump_running: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    pump_kw: Mapped[float | None] = mapped_column(Float, nullable=True)
    setpoint: Mapped[float | None] = mapped_column(Float, nullable=True)
    mode: Mapped[str | None] = mapped_column(String(8), nullable=True)
    true_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_lt101: Mapped[float | None] = mapped_column(Float, nullable=True)
    residual_lt102: Mapped[float | None] = mapped_column(Float, nullable=True)
    disagreement: Mapped[float | None] = mapped_column(Float, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    scenario_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)


class ScenarioEvent(Base):
    __tablename__ = "scenario_events"
    __table_args__ = (Index("ix_scen_run_t", "run_id", "sim_time_s"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    scenario_id: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))
    sim_time_s: Mapped[float] = mapped_column(Float)
    ts: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    ground_truth: Mapped[dict] = mapped_column(JSON, default=dict)


class DetectionRule(Base):
    __tablename__ = "detection_rules"
    rule_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20))
    description: Mapped[str] = mapped_column(Text)
    methodology: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[str] = mapped_column(String(32), default=utcnow)


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (Index("ix_inc_run", "run_id"),)
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    classification: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[str] = mapped_column(String(8))
    severity: Mapped[str] = mapped_column(String(10))
    detection_state: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="open")
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen_t: Mapped[float] = mapped_column(Float)
    first_seen: Mapped[str] = mapped_column(String(32), index=True)
    last_seen_t: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[str] = mapped_column(String(32))
    rule_ids: Mapped[list] = mapped_column(JSON, default=list)
    assets: Mapped[list] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text, default="")
    expected_behavior: Mapped[str] = mapped_column(Text, default="")
    observed_behavior: Mapped[str] = mapped_column(Text, default="")
    classification_basis: Mapped[list] = mapped_column(JSON, default=list)
    confidence_rationale: Mapped[str] = mapped_column(Text, default="")
    alternatives: Mapped[list] = mapped_column(JSON, default=list)
    recommended_steps: Mapped[list] = mapped_column(JSON, default=list)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)
    updated_at: Mapped[str] = mapped_column(String(32), default=utcnow)

    notes = relationship(
        "InvestigationNote",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InvestigationNote.id",
    )


class DetectionEvent(Base):
    __tablename__ = "detection_events"
    __table_args__ = (Index("ix_det_run_raised", "run_id", "raised_t"),)
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("simulation_runs.id", ondelete="CASCADE"))
    rule_id: Mapped[str] = mapped_column(ForeignKey("detection_rules.rule_id"))
    incident_id: Mapped[str | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(20))
    severity: Mapped[str] = mapped_column(String(10))
    asset_id: Mapped[str] = mapped_column(String(40))
    instance_key: Mapped[str] = mapped_column(String(40))
    signal: Mapped[str] = mapped_column(String(120))
    units: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(10))
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    expected_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    statistic: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_observed: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_expected: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_explanation: Mapped[str] = mapped_column(Text, default="")
    expected_label: Mapped[str] = mapped_column(String(80), default="Expected")
    observed_label: Mapped[str] = mapped_column(String(80), default="Observed")
    first_seen_t: Mapped[float] = mapped_column(Float)
    raised_t: Mapped[float] = mapped_column(Float)
    last_seen_t: Mapped[float] = mapped_column(Float)
    cleared_t: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_seen: Mapped[str] = mapped_column(String(32))
    raised_at: Mapped[str] = mapped_column(String(32))
    last_seen: Mapped[str] = mapped_column(String(32))
    cleared_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    explanation: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class InvestigationNote(Base):
    __tablename__ = "investigation_notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    author: Mapped[str] = mapped_column(String(60))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(32), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)


def make_engine(url: str) -> Engine:
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
