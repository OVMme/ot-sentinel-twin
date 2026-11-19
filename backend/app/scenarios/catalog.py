"""Scenario laboratory catalogue (scenarios A-H).

Each scenario is a *ground-truth* description of a synthetic fault or manipulation applied to
the simulated plant only. The detection engine never receives any of this information; it is
used exclusively to drive the simulation and to score detections afterwards.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from app.simulation.sensors import SensorFault

if TYPE_CHECKING:
    from app.simulation.engine import SimulationEngine

GroundTruthCategory = Literal[
    "normal", "equipment_fault", "physical_anomaly", "data_quality", "suspected_manipulation"
]


@dataclass(frozen=True)
class ScenarioParam:
    name: str
    label: str
    kind: Literal["number", "select"]
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    unit: str = ""
    options: tuple[str, ...] = ()

    def validate(self, value: Any) -> Any:
        if self.kind == "number":
            try:
                v = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{self.name} must be a number") from exc
            if self.minimum is not None and v < self.minimum:
                raise ValueError(f"{self.name} must be >= {self.minimum}")
            if self.maximum is not None and v > self.maximum:
                raise ValueError(f"{self.name} must be <= {self.maximum}")
            return v
        if value not in self.options:
            raise ValueError(f"{self.name} must be one of {', '.join(self.options)}")
        return value


Action = Callable[["SimulationEngine", dict[str, Any], "ScenarioContext"], None]


@dataclass
class ScenarioContext:
    """Mutable bookkeeping of a running scenario (restore values, ramp state)."""

    saved: dict[str, Any] = field(default_factory=dict)
    onset_t: float = 0.0


@dataclass(frozen=True)
class TimedAction:
    offset_s: float  # seconds after fault onset
    description: str
    apply: Action


@dataclass(frozen=True)
class ScenarioDefinition:
    id: str
    code: str
    title: str
    category: GroundTruthCategory
    summary: str
    initial_conditions: str
    trigger: str
    changes: tuple[str, ...]
    expected_behavior: str
    required_evidence: tuple[str, ...]
    reset_behavior: str
    onset_delay_s: float
    expected_latency_s: float | None
    params: tuple[ScenarioParam, ...]
    actions: tuple[TimedAction, ...]
    revert: Action
    expected_rules_fn: Callable[[dict[str, Any]], tuple[str, ...]]
    allowed_rules_fn: Callable[[dict[str, Any]], tuple[str, ...]]
    expected_classification_fn: Callable[[dict[str, Any]], str | None]
    per_tick: Action | None = None
    eval_duration_s: float = 240.0

    def resolve_params(self, raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        unknown = set(raw) - {p.name for p in self.params}
        if unknown:
            raise ValueError(f"unknown parameter(s): {', '.join(sorted(unknown))}")
        return {p.name: p.validate(raw.get(p.name, p.default)) for p in self.params}

    def ground_truth(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "scenario_id": self.id,
            "code": self.code,
            "category": self.category,
            "params": params,
            "expected_rules": list(self.expected_rules_fn(params)),
            "allowed_rules": list(self.allowed_rules_fn(params)),
            "expected_classification": self.expected_classification_fn(params),
            "expected_latency_s": self.expected_latency_s,
        }

    def to_public(self) -> dict[str, Any]:
        defaults = {p.name: p.default for p in self.params}
        return {
            "id": self.id,
            "code": self.code,
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "initial_conditions": self.initial_conditions,
            "trigger": self.trigger,
            "changes": list(self.changes),
            "expected_behavior": self.expected_behavior,
            "required_evidence": list(self.required_evidence),
            "reset_behavior": self.reset_behavior,
            "onset_delay_s": self.onset_delay_s,
            "expected_latency_s": self.expected_latency_s,
            "params": [
                {
                    "name": p.name,
                    "label": p.label,
                    "kind": p.kind,
                    "default": p.default,
                    "minimum": p.minimum,
                    "maximum": p.maximum,
                    "unit": p.unit,
                    "options": list(p.options),
                }
                for p in self.params
            ],
            "timeline": [{"offset_s": a.offset_s, "description": a.description} for a in self.actions],
            "ground_truth_defaults": self.ground_truth(defaults),
        }


# ------------------------------------------------------------------------------- helpers
def _noop(engine: SimulationEngine, p: dict[str, Any], ctx: ScenarioContext) -> None:
    return None


def _setpoint_step(delta: float) -> Action:
    def apply(engine: SimulationEngine, p: dict[str, Any], ctx: ScenarioContext) -> None:
        ctx.saved.setdefault("setpoint", engine.controller.state.setpoint_pct)
        engine.set_setpoint(ctx.saved["setpoint"] + delta)

    return apply


def _restore_setpoint(engine: SimulationEngine, ctx: ScenarioContext) -> None:
    if "setpoint" in ctx.saved:
        engine.set_setpoint(ctx.saved["setpoint"])


def _sensor(engine: SimulationEngine, tag: str):
    return engine.sensors.by_tag()[tag]


def _clear_all_sensor_faults(engine: SimulationEngine) -> None:
    for s in engine.sensors.all():
        s.clear_fault()


def _const(*rules: str) -> Callable[[dict[str, Any]], tuple[str, ...]]:
    return lambda p: tuple(rules)


# ------------------------------------------------------------------------------- A normal
def _a_revert(engine, p, ctx):
    return None


SCENARIO_A = ScenarioDefinition(
    id="normal-operation",
    code="A",
    title="Normal Operation",
    category="normal",
    summary="The plant runs in AUTO with documented sensor noise, seeded demand changes and healthy actuators.",
    initial_conditions="Current plant state; no faults are injected.",
    trigger="None - marks a labelled normal-operation window.",
    changes=("No change to physics or instruments.",),
    expected_behavior="No alerts after stabilisation. Any alert in this window is counted as a false positive.",
    required_evidence=("Absence of alerts", "Mass-balance residual within threshold"),
    reset_behavior="Nothing to revert.",
    onset_delay_s=0.0,
    expected_latency_s=None,
    params=(),
    actions=(),
    revert=_a_revert,
    expected_rules_fn=_const(),
    allowed_rules_fn=_const(),
    expected_classification_fn=lambda p: None,
    eval_duration_s=600.0,
)


# ------------------------------------------------------------------------------- B stuck valve
def _b_stick(engine, p, ctx):
    engine.faults.inlet_valve_stuck = True


def _b_revert(engine, p, ctx):
    engine.faults.inlet_valve_stuck = False
    _restore_setpoint(engine, ctx)


SCENARIO_B = ScenarioDefinition(
    id="stuck-inlet-valve",
    code="B",
    title="Stuck Inlet Valve",
    category="equipment_fault",
    summary="The inlet valve XV-101 seizes in its current position; the controller then demands a transition.",
    initial_conditions="AUTO mode, level at setpoint, inlet valve modulating.",
    trigger="Fault onset 5 s after start; operator raises the level setpoint by +10 % five seconds later.",
    changes=(
        "Physical inlet valve position frozen (actuator stops responding to commands).",
        "Position feedback ZT-101 keeps reporting the true (frozen) position.",
        "Level setpoint +10 % at onset + 5 s (legitimate operator action that requires valve travel).",
    ),
    expected_behavior="PHYS-004 Command/Actuator Mismatch on XV-101 once the command moves away from the frozen "
    "position; mass balance stays consistent because flows are measured correctly.",
    required_evidence=("Command vs. expected vs. feedback position", "Deviation duration beyond stroke time"),
    reset_behavior="Valve released; setpoint restored to its value before the scenario.",
    onset_delay_s=5.0,
    expected_latency_s=15.0,
    params=(),
    actions=(
        TimedAction(0.0, "Inlet valve XV-101 seizes", _b_stick),
        TimedAction(5.0, "Operator raises level setpoint +10 %", _setpoint_step(10.0)),
    ),
    revert=_b_revert,
    expected_rules_fn=_const("PHYS-004"),
    allowed_rules_fn=_const(),
    expected_classification_fn=lambda p: "equipment_fault",
)


# ------------------------------------------------------------------------------- C manipulation
def _c_inject(engine, p, ctx):
    _sensor(engine, "LT-101").fault = SensorFault(
        offset_target=p["offset_m"], offset_ramp_s=p["ramp_s"], onset_time_s=engine.sim_time_s
    )


def _c_revert(engine, p, ctx):
    _sensor(engine, "LT-101").clear_fault()


SCENARIO_C = ScenarioDefinition(
    id="sensor-manipulation",
    code="C",
    title="Sensor Value Manipulation",
    category="suspected_manipulation",
    summary="Synthetic false-data injection: the reported primary level LT-101 is offset from the true level, "
    "so the controller drives the real tank away from setpoint while LT-101 still looks normal.",
    initial_conditions="AUTO mode, level at setpoint; LT-101 is the controller's process variable.",
    trigger="Onset 5 s after start; the offset is ramped in to imitate a plausible trend.",
    changes=(
        "LT-101 reported value = true level + offset(t), offset ramped linearly to the target.",
        "Physics, LT-102 and all flow/pressure instruments remain truthful.",
    ),
    expected_behavior="PHYS-002 disagreement between LT-101 and LT-102 and PHYS-001 mass-balance residual on "
    "LT-101; classified as suspected manipulation once the controller is seen acting on the false value.",
    required_evidence=(
        "LT-101 vs LT-102 difference",
        "Mass-balance residual isolated to LT-101",
        "Abrupt onset rate",
        "Controller PV near setpoint while redundant level departs",
    ),
    reset_behavior="LT-101 returns to truthful reporting; the controller then corrects the real level.",
    onset_delay_s=5.0,
    expected_latency_s=20.0,
    params=(
        ScenarioParam("offset_m", "Injected offset", "number", -1.4, -2.0, 2.0, "m"),
        ScenarioParam("ramp_s", "Ramp duration", "number", 50.0, 0.0, 600.0, "s"),
    ),
    actions=(TimedAction(0.0, "False level offset injected on LT-101", _c_inject),),
    revert=_c_revert,
    expected_rules_fn=_const("PHYS-002", "PHYS-001"),
    allowed_rules_fn=_const("PHYS-003"),
    expected_classification_fn=lambda p: "suspected_manipulation",
)


# ------------------------------------------------------------------------------- D pump fault
def _d_fault(engine, p, ctx):
    engine.faults.pump_head_factor = p["head_factor"]


def _d_revert(engine, p, ctx):
    engine.faults.pump_head_factor = 1.0


SCENARIO_D = ScenarioDefinition(
    id="pump-fault",
    code="D",
    title="Pump Fault",
    category="equipment_fault",
    summary="Pump P-101 keeps running (motor energised, run feedback true) but its impeller no longer develops "
    "the head of its characteristic curve.",
    initial_conditions="AUTO mode, pump running, outlet valve modulating.",
    trigger="Onset 5 s after start.",
    changes=("Pump hydraulic head multiplied by the head factor; motor and run feedback unaffected.",),
    expected_behavior="PHYS-005: measured differential pressure is far below the pump curve at the measured flow.",
    required_evidence=("Measured vs. curve differential pressure", "Run feedback TRUE", "Outlet flow drop"),
    reset_behavior="Pump head restored.",
    onset_delay_s=5.0,
    expected_latency_s=15.0,
    params=(ScenarioParam("head_factor", "Remaining head", "number", 0.15, 0.0, 0.9, "x"),),
    actions=(TimedAction(0.0, "Pump impeller loses head", _d_fault),),
    revert=_d_revert,
    expected_rules_fn=_const("PHYS-005"),
    allowed_rules_fn=_const(),
    expected_classification_fn=lambda p: "equipment_fault",
)


# ------------------------------------------------------------------------------- E blocked outlet
def _e_start(engine, p, ctx):
    ctx.saved["restriction_target"] = p["restriction"]


def _e_tick(engine, p, ctx):
    target = ctx.saved.get("restriction_target")
    if target is None:
        return
    frac = min(max((engine.sim_time_s - ctx.onset_t) / 10.0, 0.0), 1.0)
    engine.faults.outlet_restriction = target * frac


def _e_revert(engine, p, ctx):
    ctx.saved.pop("restriction_target", None)
    engine.faults.outlet_restriction = 0.0


SCENARIO_E = ScenarioDefinition(
    id="blocked-outlet",
    code="E",
    title="Blocked Outlet",
    category="physical_anomaly",
    summary="A restriction develops in the outlet line downstream of PT-101 (e.g. a fouled strainer), "
    "reducing outlet flow at unchanged valve opening.",
    initial_conditions="AUTO mode, pump running, outlet valve modulating.",
    trigger="Onset 5 s after start; restriction ramps to target over 10 s.",
    changes=("Effective outlet flow coefficient reduced by the restriction fraction.",),
    expected_behavior="PHYS-007: at the measured line pressure and valve opening, FT-102 reads far less than the "
    "valve equation requires. The pump curve stays consistent, so PHYS-005 should not fire.",
    required_evidence=(
        "Measured vs. predicted outlet flow",
        "Line pressure rise",
        "Unchanged valve position",
    ),
    reset_behavior="Restriction removed.",
    onset_delay_s=5.0,
    expected_latency_s=20.0,
    params=(ScenarioParam("restriction", "Restriction", "number", 0.75, 0.1, 0.95, "fraction"),),
    actions=(TimedAction(0.0, "Outlet restriction starts to build", _e_start),),
    revert=_e_revert,
    expected_rules_fn=_const("PHYS-007"),
    allowed_rules_fn=_const(),
    expected_classification_fn=lambda p: "physical_anomaly",
    per_tick=_e_tick,
)


# ------------------------------------------------------------------------------- F frozen telemetry
FREEZABLE = ("LT-102", "LT-101", "FT-101", "FT-102", "PT-101")


def _f_freeze(engine, p, ctx):
    _sensor(engine, p["signal"]).fault = SensorFault(freeze=p["mode"], onset_time_s=engine.sim_time_s)


def _f_revert(engine, p, ctx):
    _sensor(engine, p["signal"]).clear_fault()
    _restore_setpoint(engine, ctx)


def _f_expected(p: dict[str, Any]) -> tuple[str, ...]:
    return ("DATA-001",) if p["mode"] == "stale" else ("PHYS-006",)


def _f_allowed(p: dict[str, Any]) -> tuple[str, ...]:
    if p["mode"] == "stale":
        return ()
    sig = p["signal"]
    if sig in ("LT-101", "LT-102"):
        return ("PHYS-001", "PHYS-002", "PHYS-003")
    if sig == "FT-101":
        return ("PHYS-001",)
    return ("PHYS-001", "PHYS-005", "PHYS-007")


SCENARIO_F = ScenarioDefinition(
    id="frozen-telemetry",
    code="F",
    title="Frozen Telemetry",
    category="data_quality",
    summary="One measurement stops updating. 'stuck': the value freezes but timestamps keep refreshing (e.g. a "
    "gateway republishing a cached value). 'stale': value and source timestamp both stop.",
    initial_conditions="AUTO mode, level at setpoint.",
    trigger="Onset 5 s after start; operator raises the setpoint +15 % ten seconds later so the process changes.",
    changes=(
        "Selected transmitter holds its last value (and, for 'stale', its last source timestamp).",
        "Level setpoint +15 % at onset + 10 s (legitimate operator action).",
    ),
    expected_behavior="'stale' -> DATA-001 freshness (physics rules suspend evaluation of that signal). "
    "'stuck' -> PHYS-006 frozen sensor once independent signals show the process changing.",
    required_evidence=("Source timestamp age or flatline duration", "Independent predicted change"),
    reset_behavior="Transmitter resumes live reporting; setpoint restored.",
    onset_delay_s=5.0,
    expected_latency_s=45.0,
    params=(
        ScenarioParam("signal", "Transmitter", "select", "LT-102", options=FREEZABLE),
        ScenarioParam("mode", "Failure mode", "select", "stuck", options=("stuck", "stale")),
    ),
    actions=(
        TimedAction(0.0, "Transmitter stops updating", _f_freeze),
        TimedAction(10.0, "Operator raises level setpoint +15 %", _setpoint_step(15.0)),
    ),
    revert=_f_revert,
    expected_rules_fn=_f_expected,
    allowed_rules_fn=_f_allowed,
    expected_classification_fn=lambda p: "data_quality" if p["mode"] == "stale" else "equipment_fault",
)


# ------------------------------------------------------------------------------- G drift
def _g_drift(engine, p, ctx):
    _sensor(engine, p["signal"]).fault = SensorFault(
        drift_per_s=p["drift_mm_s"] / 1000.0, onset_time_s=engine.sim_time_s
    )


def _g_revert(engine, p, ctx):
    _sensor(engine, p["signal"]).clear_fault()


SCENARIO_G = ScenarioDefinition(
    id="sensor-drift",
    code="G",
    title="Gradual Sensor Drift",
    category="equipment_fault",
    summary="A level transmitter slowly drifts away from the true level (ageing / fouling).",
    initial_conditions="AUTO mode, level at setpoint.",
    trigger="Onset 5 s after start.",
    changes=("Additive drift on the selected level transmitter at the configured rate.",),
    expected_behavior="Progressive detection: PHYS-001 residual accumulates first, PHYS-002 follows when the "
    "difference exceeds tolerance. Slow onset -> classified as equipment fault (drift), not manipulation.",
    required_evidence=("Growing residual", "Redundant difference", "Deviation growth rate"),
    reset_behavior="Drift removed; transmitter reads truthfully again.",
    onset_delay_s=5.0,
    expected_latency_s=60.0,
    params=(
        ScenarioParam("signal", "Transmitter", "select", "LT-102", options=("LT-102", "LT-101")),
        ScenarioParam("drift_mm_s", "Drift rate", "number", 2.0, 0.2, 20.0, "mm/s"),
    ),
    actions=(TimedAction(0.0, "Transmitter starts drifting", _g_drift),),
    revert=_g_revert,
    expected_rules_fn=_const("PHYS-001", "PHYS-002"),
    allowed_rules_fn=_const("PHYS-003"),
    expected_classification_fn=lambda p: "equipment_fault",
)


# ------------------------------------------------------------------------------- H conflict
def _h_step(engine, p, ctx):
    _sensor(engine, "LT-102").fault = SensorFault(offset_target=p["offset_m"], onset_time_s=engine.sim_time_s)


def _h_revert(engine, p, ctx):
    _sensor(engine, "LT-102").clear_fault()


SCENARIO_H = ScenarioDefinition(
    id="conflicting-measurements",
    code="H",
    title="Conflicting Measurements",
    category="equipment_fault",
    summary="The redundant level transmitter LT-102 suddenly reports a value incompatible with LT-101 "
    "(e.g. a wrong range/span loaded).",
    initial_conditions="AUTO mode, level at setpoint.",
    trigger="Onset 5 s after start (step change).",
    changes=("Step offset added to LT-102.",),
    expected_behavior="PHYS-002 sensor disagreement; PHYS-003 may flag the physically impossible step, PHYS-001 "
    "the residual on LT-102. LT-102 is not the controller PV, so no masking -> equipment fault.",
    required_evidence=("LT-101 vs LT-102 difference", "Step rate beyond physical limit"),
    reset_behavior="Offset removed.",
    onset_delay_s=5.0,
    expected_latency_s=10.0,
    params=(ScenarioParam("offset_m", "Step offset", "number", 0.8, -2.0, 2.0, "m"),),
    actions=(TimedAction(0.0, "LT-102 step offset", _h_step),),
    revert=_h_revert,
    expected_rules_fn=_const("PHYS-002"),
    allowed_rules_fn=_const("PHYS-001", "PHYS-003"),
    expected_classification_fn=lambda p: "equipment_fault",
)


SCENARIOS: dict[str, ScenarioDefinition] = {
    s.id: s
    for s in (SCENARIO_A, SCENARIO_B, SCENARIO_C, SCENARIO_D, SCENARIO_E, SCENARIO_F, SCENARIO_G, SCENARIO_H)
}


def get_scenario(scenario_id: str) -> ScenarioDefinition:
    if scenario_id in SCENARIOS:
        return SCENARIOS[scenario_id]
    for s in SCENARIOS.values():
        if s.code.lower() == scenario_id.lower():
            return s
    raise KeyError(scenario_id)


__all__ = [
    "SCENARIOS",
    "ScenarioContext",
    "ScenarioDefinition",
    "_clear_all_sensor_faults",
    "_noop",
    "get_scenario",
]
