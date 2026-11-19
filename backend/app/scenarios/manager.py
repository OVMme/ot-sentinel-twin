"""Runs one scenario at a time against a SimulationEngine and records ground-truth events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.simulation.engine import SimulationEngine, _iso

from .catalog import ScenarioContext, ScenarioDefinition, get_scenario


@dataclass
class ScenarioEventRecord:
    kind: Literal["started", "fault_onset", "action", "stopped"]
    scenario_id: str
    t: float
    ts: str
    description: str
    ground_truth: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "scenario_id": self.scenario_id,
            "t": self.t,
            "ts": self.ts,
            "description": self.description,
            "ground_truth": self.ground_truth,
        }


@dataclass
class ActiveScenario:
    definition: ScenarioDefinition
    params: dict[str, Any]
    started_t: float
    onset_t: float
    ctx: ScenarioContext
    fired: set[int] = field(default_factory=set)
    phase: Literal["armed", "active"] = "armed"

    def to_dict(self, now: float) -> dict[str, Any]:
        d = self.definition
        return {
            "scenario_id": d.id,
            "code": d.code,
            "title": d.title,
            "params": self.params,
            "phase": self.phase,
            "started_t": self.started_t,
            "onset_t": self.onset_t,
            "elapsed_s": round(now - self.started_t, 1),
            "ground_truth": d.ground_truth(self.params),
            "next_actions": [
                {"offset_s": a.offset_s, "description": a.description, "done": i in self.fired}
                for i, a in enumerate(d.actions)
            ],
        }


class ScenarioManager:
    def __init__(self, engine: SimulationEngine) -> None:
        self.engine = engine
        self.active: ActiveScenario | None = None
        self.events: list[ScenarioEventRecord] = []
        self._pending_events: list[ScenarioEventRecord] = []
        engine.pre_sample_hooks.append(self._tick)

    def _record(
        self, kind, sid: str, description: str, gt: dict[str, Any] | None = None
    ) -> ScenarioEventRecord:
        t = self.engine.sim_time_s
        from datetime import timedelta

        ev = ScenarioEventRecord(
            kind, sid, t, _iso(self.engine.epoch + timedelta(seconds=t)), description, gt or {}
        )
        self.events.append(ev)
        self._pending_events.append(ev)
        return ev

    def drain_events(self) -> list[ScenarioEventRecord]:
        out, self._pending_events = self._pending_events, []
        return out

    def start(self, scenario_id: str, params: dict[str, Any] | None = None) -> ActiveScenario:
        definition = get_scenario(scenario_id)
        resolved = definition.resolve_params(params)
        if self.active is not None:
            self.stop("replaced by new scenario")
        now = self.engine.sim_time_s
        self.active = ActiveScenario(
            definition=definition,
            params=resolved,
            started_t=now,
            onset_t=now + definition.onset_delay_s,
            ctx=ScenarioContext(),
        )
        self._record(
            "started",
            definition.id,
            f"Scenario {definition.code} '{definition.title}' started",
            definition.ground_truth(resolved),
        )
        return self.active

    def stop(self, reason: str = "stopped by user") -> ScenarioEventRecord | None:
        act = self.active
        if act is None:
            return None
        act.definition.revert(self.engine, act.params, act.ctx)
        self.active = None
        return self._record(
            "stopped",
            act.definition.id,
            f"Scenario {act.definition.code} ended ({reason})",
            act.definition.ground_truth(act.params),
        )

    def _tick(self, engine: SimulationEngine) -> None:
        act = self.active
        if act is None:
            return
        t = engine.sim_time_s
        if act.phase == "armed" and t >= act.onset_t - 1e-9:
            act.phase = "active"
            act.ctx.onset_t = t
            self._record(
                "fault_onset",
                act.definition.id,
                f"Ground truth: {act.definition.title} onset",
                act.definition.ground_truth(act.params),
            )
        if act.phase != "active":
            return
        for i, action in enumerate(act.definition.actions):
            if i in act.fired:
                continue
            if t >= act.ctx.onset_t + action.offset_s - 1e-9:
                action.apply(engine, act.params, act.ctx)
                act.fired.add(i)
                if action.offset_s > 0:
                    self._record("action", act.definition.id, action.description)
        if act.definition.per_tick is not None:
            act.definition.per_tick(engine, act.params, act.ctx)
