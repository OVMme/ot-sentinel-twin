"""Live simulation runtime: paces the deterministic engine in wall-clock time, runs detection and
correlation on every sample, persists results in batches and broadcasts them over WebSocket.

Single instance per process. All engine mutation happens on the asyncio event-loop thread;
database writes run in a worker thread on immutable snapshots.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import secrets
import threading
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.detection.base import Alert, ProcessModel, RuleConfig
from app.detection.correlation import IncidentCorrelator
from app.detection.engine import DetectionEngine
from app.evaluation.harness import run_evaluation
from app.repositories.sql import Repository
from app.scenarios.manager import ScenarioManager
from app.simulation.engine import SimulationEngine, _iso
from app.simulation.params import SimulationConfig

from .hub import Hub

log = logging.getLogger("otst.runtime")

BUFFER_SAMPLES = 1200  # recent samples kept in memory for new clients (10 min at 2 Hz)
FLUSH_EVERY_S = 1.0
STATE_EVERY_S = 2.0

# Reproducible demo storyline (used when OTST_DEMO_MODE=true): (seconds, scenario or None).
DEMO_SCRIPT: list[tuple[float, tuple[str, dict[str, Any]] | None]] = [
    (90.0, None),
    (180.0, ("sensor-manipulation", {})),
    (90.0, None),
    (120.0, ("stuck-inlet-valve", {})),
    (90.0, None),
    (120.0, ("pump-fault", {})),
    (90.0, None),
    (120.0, ("blocked-outlet", {})),
    (90.0, None),
    (150.0, ("sensor-drift", {})),
]


class SimulationRuntime:
    def __init__(self, settings: Settings, repo: Repository, data_dir: Path) -> None:
        self.settings = settings
        self.repo = repo
        self.data_dir = data_dir
        self.hub = Hub(settings.ws_max_clients)
        self.status = "paused"
        self.speed = 1.0
        self.buffer: deque[dict[str, Any]] = deque(maxlen=BUFFER_SAMPLES)
        self.recent_alerts: dict[str, dict[str, Any]] = {}
        self._task: asyncio.Task | None = None
        self._flush_lock = threading.Lock()
        self._pending_lock = threading.Lock()  # guards the _pending_* buffers (API threads + loop)
        self._pending_samples: list[dict[str, Any]] = []
        self._pending_alerts: dict[str, dict[str, Any]] = {}
        self._pending_incidents: dict[str, dict[str, Any]] = {}
        self._pending_scenarios: list[dict[str, Any]] = []
        self._last_flush = 0.0
        self._last_state = 0.0
        self.loop_lag_ms = 0.0
        self.eval_status: dict[str, Any] = {"running": False, "started_at": None, "error": None}
        self._eval_thread: threading.Thread | None = None
        self._demo_index = 0
        self._demo_phase_started = 0.0

        stored = repo.latest_config()
        if stored is None:
            self.config = SimulationConfig()
            self.config_id = repo.save_config(self.config, label="default")
        else:
            self.config_id, self.config = stored
        model = ProcessModel.from_config(self.config)
        descriptions = DetectionEngine(model).status()
        self.rule_configs = repo.sync_rules(descriptions)
        repo.mark_stale_runs()
        self._build()

    # ------------------------------------------------------------------ construction
    def _build(self) -> None:
        epoch = datetime.now(UTC).replace(microsecond=0)
        self.epoch = epoch
        self.engine = SimulationEngine(self.config, epoch=epoch)
        self.scenarios = ScenarioManager(self.engine)
        model = ProcessModel.from_config(self.config)
        configs = {}
        for rid, cfg in self.rule_configs.items():
            try:
                configs[rid] = RuleConfig.model_validate(cfg)
            except ValueError:
                log.warning("ignoring invalid stored config for %s", rid)
        self.detector = DetectionEngine(model, configs, id_start=self.repo.max_counter("alert"))
        self.correlator = IncidentCorrelator(model, id_start=self.repo.max_counter("incident"))
        self.run_id = f"run-{epoch:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
        self.repo.create_run(
            self.run_id,
            self.config_id,
            _iso(epoch),
            self.config.seed,
            self.config.sample_interval_s,
            "demo" if self.settings.demo_mode else "live",
        )
        self.repo.enforce_retention(self.settings.retention_runs, protect=self.run_id)
        self.buffer.clear()
        self.recent_alerts.clear()
        self._demo_index = 0
        self._demo_phase_started = 0.0

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if self.status == "running":
            return
        self.status = "running"
        self.repo.set_run_status(self.run_id, "running")
        self._task = asyncio.create_task(self._loop(), name="otst-sim-loop")
        self._publish_state()

    async def pause(self) -> None:
        if self.status != "running":
            return
        self.status = "paused"
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.flush()
        self.repo.set_run_status(self.run_id, "paused")
        self._publish_state()

    async def reset(self, new_config: SimulationConfig | None = None) -> None:
        was_running = self.status == "running"
        await self.pause()
        self.scenarios.stop("simulation reset")
        self._collect_scenario_events()
        await self.flush()
        self.repo.finish_run(self.run_id, "stopped")
        if new_config is not None:
            self.config = new_config
            self.config_id = self.repo.save_config(new_config, label="user")
        self._build()
        self.hub.publish({"type": "reset", "data": {"run_id": self.run_id}})
        if was_running:
            await self.start()
        self._publish_state()

    async def shutdown(self) -> None:
        await self.pause()
        await self.flush()
        self.repo.finish_run(self.run_id, "stopped")

    def set_speed(self, speed: float) -> None:
        self.speed = float(min(max(speed, 0.25), self.settings.max_speed))
        self._publish_state()

    # ------------------------------------------------------------------ main loop
    async def _loop(self) -> None:
        interval = self.config.sample_interval_s
        next_t = time.monotonic()
        try:
            while self.status == "running":
                self.tick()
                now = time.monotonic()
                if now - self._last_flush >= FLUSH_EVERY_S:
                    self._last_flush = now
                    await self.flush()
                if now - self._last_state >= STATE_EVERY_S:
                    self._last_state = now
                    self._publish_state()
                next_t += interval / self.speed
                delay = next_t - time.monotonic()
                self.loop_lag_ms = round(max(-delay, 0.0) * 1000.0, 1)
                if delay < -2.0:  # fell far behind (e.g. machine suspended): resynchronise
                    next_t = time.monotonic()
                    delay = 0.0
                await asyncio.sleep(max(delay, 0.0))
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive: never kill the app silently
            log.exception("simulation loop crashed")
            self.status = "error"
            self._publish_state()

    def tick(self) -> dict[str, Any]:
        if self.settings.demo_mode:
            self._demo_step()
        sample = self.engine.step()
        result = self.detector.process(sample)
        inc_changes = self.correlator.process(result.changes, sample)
        payload = sample.to_dict(self.epoch)
        active = self.scenarios.active
        payload.update(
            run_id=self.run_id,
            truth=self.engine.truth_dict(),
            derived=result.analytics,
            validity=result.validity,
            scenario_id=active.definition.id if active else None,
        )
        self.buffer.append(payload)
        alert_dicts = [(ch.change, _snapshot_alert(ch.alert)) for ch in result.changes]
        inc_dicts = [(ic.change, copy.deepcopy(ic.incident.to_dict())) for ic in inc_changes]
        with self._pending_lock:
            self._pending_samples.append(payload)
            for _, d in alert_dicts:
                self._pending_alerts[d["id"]] = d
            for _, d in inc_dicts:
                self._pending_incidents[d["id"]] = d
        self.hub.publish({"type": "telemetry", "data": payload})
        for change, d in alert_dicts:
            self.recent_alerts[d["id"]] = d
            self.hub.publish({"type": "alert", "change": change, "data": d})
        if len(self.recent_alerts) > 300:
            for k in list(self.recent_alerts)[: len(self.recent_alerts) - 300]:
                if self.recent_alerts[k]["status"] != "active":
                    del self.recent_alerts[k]
        for inc_change, inc_d in inc_dicts:
            self.hub.publish({"type": "incident", "change": inc_change, "data": inc_d})
        self._collect_scenario_events()
        return payload

    def _collect_scenario_events(self) -> None:
        for ev in self.scenarios.drain_events():
            d = ev.to_dict()
            with self._pending_lock:
                self._pending_scenarios.append(d)
            self.hub.publish({"type": "scenario_event", "data": d})

    def _take_batch(self) -> tuple[list, list, list, list]:
        """Atomically swap out pending writes (callable from any thread)."""
        with self._pending_lock:
            batch = (
                self._pending_samples,
                self._pending_scenarios,
                list(self._pending_alerts.values()),
                list(self._pending_incidents.values()),
            )
            self._pending_samples, self._pending_scenarios = [], []
            self._pending_alerts, self._pending_incidents = {}, {}
        return batch

    def _write(self, batch: tuple[list, list, list, list]) -> None:
        samples, scen, alerts, incidents = batch
        if not (samples or scen or alerts or incidents):
            return
        with self._flush_lock:
            try:
                self.repo.write_batch(
                    self.run_id, samples, scen, alerts, incidents, self.settings.max_samples_per_run
                )
            except Exception:  # pragma: no cover - keep running, report via health
                log.exception("persistence batch failed (%d samples)", len(samples))

    async def flush(self) -> None:
        await asyncio.to_thread(self._write, self._take_batch())

    def flush_sync(self) -> None:
        self._write(self._take_batch())

    # ------------------------------------------------------------------ demo mode
    def _demo_step(self) -> None:
        t = self.engine.sim_time_s
        dur, scen = DEMO_SCRIPT[self._demo_index]
        if t - self._demo_phase_started >= dur:
            if self.scenarios.active is not None:
                self.scenarios.stop("demo storyline")
            self._demo_index = (self._demo_index + 1) % len(DEMO_SCRIPT)
            self._demo_phase_started = t
            _, scen = DEMO_SCRIPT[self._demo_index]
            if scen is not None:
                self.scenarios.start(scen[0], scen[1])

    # ------------------------------------------------------------------ state
    def state(self) -> dict[str, Any]:
        e = self.engine
        last = self.buffer[-1] if self.buffer else None
        act = self.scenarios.active
        return {
            "run_id": self.run_id,
            "status": self.status,
            "speed": self.speed,
            "max_speed": self.settings.max_speed,
            "sim_time_s": e.sim_time_s,
            "seq": e.seq,
            "epoch": _iso(self.epoch),
            "sim_timestamp": last["ts"] if last else _iso(self.epoch),
            "mode": e.controller.state.mode,
            "setpoint_pct": e.controller.state.setpoint_pct,
            "manual_commands": {
                "inlet_valve_pct": e.controller.state.manual_commands.inlet_valve_pct,
                "outlet_valve_pct": e.controller.state.manual_commands.outlet_valve_pct,
                "pump_on": e.controller.state.manual_commands.pump_on,
            },
            "interlocks": {
                "high": e.controller.state.interlock_high,
                "low": e.controller.state.interlock_low,
            },
            "controller_health": e.controller.state.health,
            "scenario": act.to_dict(e.sim_time_s) if act else None,
            "detection": {
                "status": "running" if self.status == "running" else "idle",
                "samples_processed": self.detector.samples_processed,
                "active_alerts": len(self.detector.active_alerts()),
                "rules_enabled": sum(1 for r in self.detector.rules if r.config.enabled),
                "rules_total": len(self.detector.rules),
                "anomaly_score": self.detector.last_analytics.get("anomaly_score", 0.0),
                "warmup_complete": self.detector.samples_processed * self.config.sample_interval_s >= 60.0,
            },
            "health": {
                "loop_lag_ms": self.loop_lag_ms,
                "ws_clients": len(self.hub.clients),
                "pending_samples": len(self._pending_samples),
            },
            "read_only": self.settings.read_only,
            "demo_mode": self.settings.demo_mode,
            "config": {
                "seed": self.config.seed,
                "sample_interval_s": self.config.sample_interval_s,
                "tank_area_m2": self.config.tank.area_m2,
                "tank_height_m": self.config.tank.height_m,
            },
        }

    def _publish_state(self) -> None:
        self.hub.publish({"type": "state", "data": self.state()})

    def publish_state(self) -> None:
        self._publish_state()

    def active_alerts(self) -> list[dict[str, Any]]:
        return [_snapshot_alert(a) for a in self.detector.active_alerts()]

    # ------------------------------------------------------------------ rule configuration
    def update_rule(self, rule_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        cfg = self.detector.update_config(rule_id, **changes)
        self.rule_configs[rule_id] = cfg.model_dump()
        self.repo.save_rule_config(rule_id, cfg.model_dump())
        return cfg.model_dump()

    # ------------------------------------------------------------------ evaluation
    @property
    def eval_path(self) -> Path:
        return self.data_dir / "evaluation_latest.json"

    def latest_evaluation(self) -> dict[str, Any] | None:
        candidates = [self.eval_path]
        ref = os.environ.get("OTST_REFERENCE_EVALUATION")
        if ref:
            candidates.append(Path(ref))
        candidates.append(
            Path(__file__).resolve().parents[3] / "datasets" / "synthetic" / "evaluation_results.json"
        )
        for p in candidates:
            if p.exists():
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
        return None

    def start_evaluation(self, seeds: tuple[int, ...]) -> bool:
        if self._eval_thread is not None and self._eval_thread.is_alive():
            return False

        def work() -> None:
            try:
                result = run_evaluation(seeds, self.config)
                self.data_dir.mkdir(parents=True, exist_ok=True)
                self.eval_path.write_text(json.dumps(result, indent=1), encoding="utf-8")
                self.eval_status = {
                    "running": False,
                    "started_at": self.eval_status["started_at"],
                    "error": None,
                    "finished_at": result["generated_at"],
                }
            except Exception as exc:  # pragma: no cover
                log.exception("evaluation failed")
                self.eval_status = {
                    "running": False,
                    "started_at": self.eval_status["started_at"],
                    "error": type(exc).__name__,
                }

        self.eval_status = {"running": True, "started_at": _iso(datetime.now(UTC)), "error": None}
        self._eval_thread = threading.Thread(target=work, name="otst-eval", daemon=True)
        self._eval_thread.start()
        return True


def _snapshot_alert(a: Alert) -> dict[str, Any]:
    return copy.deepcopy(a.to_dict())
