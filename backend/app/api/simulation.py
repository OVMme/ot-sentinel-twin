"""Simulation control, plant configuration and scenario laboratory endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path
from pydantic import ValidationError

from app.repositories.sql import Repository
from app.scenarios.catalog import SCENARIOS, get_scenario
from app.services.runtime import SimulationRuntime
from app.simulation.params import SimulationConfig

from .deps import ApiError, analyst, get_repo, get_runtime, require_write
from .schemas import (
    SCENARIO_ID_PATTERN,
    ModeRequest,
    OperatorRequest,
    ResetRequest,
    ScenarioStartRequest,
    SpeedRequest,
)

router = APIRouter(prefix="/api", tags=["simulation"])


@router.get("/simulation/state")
async def simulation_state(rt: SimulationRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return rt.state()


@router.post("/simulation/start", dependencies=[Depends(require_write)])
async def simulation_start(
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    await rt.start()
    repo.audit(who, "simulation.start", f"run:{rt.run_id}")
    return rt.state()


@router.post("/simulation/pause", dependencies=[Depends(require_write)])
async def simulation_pause(
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    await rt.pause()
    repo.audit(who, "simulation.pause", f"run:{rt.run_id}")
    return rt.state()


@router.post("/simulation/reset", dependencies=[Depends(require_write)])
async def simulation_reset(
    body: ResetRequest | None = None,
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    old = rt.run_id
    new_cfg = None
    if body is not None and body.seed is not None:
        new_cfg = rt.config.model_copy(update={"seed": body.seed})
    await rt.reset(new_cfg)
    repo.audit(who, "simulation.reset", f"run:{old}", {"new_run": rt.run_id, "seed": rt.config.seed})
    return rt.state()


@router.post("/simulation/speed", dependencies=[Depends(require_write)])
async def simulation_speed(
    body: SpeedRequest,
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    if body.speed > rt.settings.max_speed:
        raise ApiError(422, "speed_limit", f"Maximum speed is {rt.settings.max_speed}x on this deployment.")
    rt.set_speed(body.speed)
    repo.audit(who, "simulation.speed", f"run:{rt.run_id}", {"speed": rt.speed})
    return rt.state()


@router.post("/simulation/mode", dependencies=[Depends(require_write)])
async def simulation_mode(
    body: ModeRequest,
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    rt.engine.set_mode(body.mode)
    repo.audit(who, "controller.mode", "PLC-001", {"mode": body.mode})
    rt.publish_state()
    return rt.state()


@router.post("/simulation/operator", dependencies=[Depends(require_write)])
async def simulation_operator(
    body: OperatorRequest,
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    """Synthetic operator actions on the simulated controller (never sent to real equipment)."""
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise ApiError(422, "empty", "Provide at least one operator value.")
    manual_fields = {"inlet_valve_pct", "outlet_valve_pct", "pump_on"} & changes.keys()
    if manual_fields and rt.engine.controller.state.mode != "manual":
        raise ApiError(409, "not_manual", "Valve and pump commands require MANUAL mode.")
    if "setpoint_pct" in changes:
        rt.engine.set_setpoint(changes["setpoint_pct"])
    rt.engine.set_manual_commands(
        changes.get("inlet_valve_pct"), changes.get("outlet_valve_pct"), changes.get("pump_on")
    )
    repo.audit(who, "controller.operator", "PLC-001", changes)
    rt.publish_state()
    return rt.state()


@router.get("/simulation/config")
async def get_config(rt: SimulationRuntime = Depends(get_runtime)) -> dict[str, Any]:
    return {"active": rt.config.model_dump(), "schema": SimulationConfig.model_json_schema()}


@router.put("/simulation/config", dependencies=[Depends(require_write)])
async def put_config(
    body: dict[str, Any],
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    """Validate a new plant configuration and apply it by resetting the simulation (new run)."""
    try:
        cfg = SimulationConfig.model_validate(body)
    except ValidationError as exc:
        raise ApiError(
            422,
            "invalid_config",
            "Configuration rejected.",
            [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()],
        ) from exc
    if cfg.tank.initial_level_m > cfg.tank.height_m:
        raise ApiError(422, "invalid_config", "Initial level must not exceed tank height.")
    await rt.reset(cfg)
    repo.audit(who, "simulation.config", f"run:{rt.run_id}", {"seed": cfg.seed})
    return {"active": rt.config.model_dump(), "state": rt.state()}


# ----------------------------------------------------------------------------- scenarios
@router.get("/scenarios", tags=["scenarios"])
async def list_scenarios() -> list[dict[str, Any]]:
    return [s.to_public() for s in SCENARIOS.values()]


@router.get("/scenarios/active", tags=["scenarios"])
async def active_scenario(rt: SimulationRuntime = Depends(get_runtime)) -> dict[str, Any]:
    act = rt.scenarios.active
    return {
        "active": act.to_dict(rt.engine.sim_time_s) if act else None,
        "events": [e.to_dict() for e in rt.scenarios.events[-50:]],
    }


@router.post("/scenarios/stop", tags=["scenarios"], dependencies=[Depends(require_write)])
async def stop_scenario(
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    ev = rt.scenarios.stop("stopped by user")
    rt._collect_scenario_events()
    if ev is not None:
        repo.audit(who, "scenario.stop", f"scenario:{ev.scenario_id}", {"run": rt.run_id})
    rt.publish_state()
    return rt.state()


@router.post("/scenarios/{scenario_id}/start", tags=["scenarios"], dependencies=[Depends(require_write)])
async def start_scenario(
    body: ScenarioStartRequest | None = None,
    scenario_id: str = Path(pattern=SCENARIO_ID_PATTERN),
    rt: SimulationRuntime = Depends(get_runtime),
    repo: Repository = Depends(get_repo),
    who: str = Depends(analyst),
) -> dict[str, Any]:
    try:
        definition = get_scenario(scenario_id)
    except KeyError as exc:
        raise ApiError(404, "not_found", f"Unknown scenario '{scenario_id}'.") from exc
    try:
        act = rt.scenarios.start(definition.id, (body.params if body else {}))
    except ValueError as exc:
        raise ApiError(422, "invalid_params", str(exc)) from exc
    rt._collect_scenario_events()
    repo.audit(who, "scenario.start", f"scenario:{definition.id}", {"params": act.params, "run": rt.run_id})
    rt.publish_state()
    return rt.state()
