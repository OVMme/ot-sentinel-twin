"""Simulation engine: controller -> actuators -> physics -> instruments -> telemetry.

The engine is a pure, deterministic state machine. Wall-clock pacing, persistence and
broadcasting live in ``app.services.runtime``; the engine itself never sleeps, never does I/O
and produces identical output for an identical (config, seed, scenario timeline).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np

from .controller import LevelController, Mode
from .params import SimulationConfig
from .plant import Commands, Plant, PlantFaults
from .sensors import Reading, SensorSuite, build_sensors

DEFAULT_EPOCH = datetime(2026, 1, 1, tzinfo=UTC)

# Signal catalogue: name -> (asset id, tag, unit). Shared with the API and the frontend.
SIGNALS: dict[str, tuple[str, str, str]] = {
    "tank.level_percent": ("TANK-001", "LT-101", "%"),
    "tank.level_meters": ("TANK-001", "LT-101", "m"),
    "sensor.primary_level": ("TANK-001", "LT-101", "m"),
    "sensor.secondary_level": ("TANK-001", "LT-102", "m"),
    "valve.inlet_command": ("XV-101", "XC-101", "%"),
    "valve.inlet_position": ("XV-101", "ZT-101", "%"),
    "valve.outlet_command": ("XV-102", "XC-102", "%"),
    "valve.outlet_position": ("XV-102", "ZT-102", "%"),
    "pump.command": ("P-101", "HS-101", "bool"),
    "pump.running": ("P-101", "YS-101", "bool"),
    "pump.power_kw": ("P-101", "JT-101", "kW"),
    "flow.inlet_lps": ("FT-101", "FT-101", "L/s"),
    "flow.outlet_lps": ("FT-102", "FT-102", "L/s"),
    "pressure.line_bar": ("PT-101", "PT-101", "bar"),
    "controller.mode": ("PLC-001", "PLC-001", "enum"),
    "controller.health": ("PLC-001", "PLC-001", "enum"),
    "controller.setpoint_percent": ("PLC-001", "LIC-101.SP", "%"),
}


@dataclass
class TelemetrySample:
    """One scan of *reported* plant data. This is everything the detection engine may see."""

    seq: int
    sim_time_s: float
    timestamp: datetime
    signals: dict[str, Reading]

    def value(self, name: str) -> float | bool | str | None:
        r = self.signals.get(name)
        return None if r is None else r.value

    def to_dict(self, epoch: datetime | None = None) -> dict:
        return {
            "seq": self.seq,
            "t": round(self.sim_time_s, 3),
            "ts": _iso(self.timestamp),
            "signals": {
                name: {
                    "v": r.value,
                    "u": r.unit,
                    "t_src": round(r.source_time_s, 3),  # source timestamp, seconds since run epoch
                    "q": r.quality,
                    "valid": r.valid,
                    "tag": r.tag,
                }
                for name, r in self.signals.items()
            },
        }


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


StepHook = Callable[["SimulationEngine"], None]


class SimulationEngine:
    def __init__(self, config: SimulationConfig, epoch: datetime | None = None) -> None:
        self.cfg = config
        self.epoch = epoch or DEFAULT_EPOCH
        root = np.random.default_rng(config.seed)
        self._rng_bias = np.random.default_rng(root.integers(0, 2**31))
        self._rng_noise = np.random.default_rng(root.integers(0, 2**31))
        self.controller = LevelController(config)
        c0 = self.controller.state.commands
        self.plant = Plant(config, Commands(c0.inlet_valve_pct, c0.outlet_valve_pct, c0.pump_on))
        # Start balanced: inlet valve matches outlet flow at the initial level.
        self.controller.initialise_steady_state(self.plant.state.qout_lps)
        self.plant.state.inlet_pos_pct = self.controller.state.commands.inlet_valve_pct
        self.plant._update_algebraic()
        self.sensors: SensorSuite = build_sensors(config, self._rng_bias)
        self.seq = 0
        self.sim_time_s = 0.0
        self.pre_sample_hooks: list[StepHook] = []
        self.last_sample: TelemetrySample | None = None
        self._substeps = max(1, round(config.sample_interval_s / config.physics_dt_s))
        self._dt = config.sample_interval_s / self._substeps
        self.last_sample = self._read_instruments()

    # ------------------------------------------------------------------ faults / operator
    @property
    def faults(self) -> PlantFaults:
        return self.plant.state.faults

    def set_mode(self, mode: Mode) -> None:
        self.controller.set_mode(mode)

    def set_setpoint(self, pct: float) -> None:
        self.controller.state.setpoint_pct = min(max(pct, 5.0), 95.0)

    def set_manual_commands(
        self, inlet_pct: float | None = None, outlet_pct: float | None = None, pump_on: bool | None = None
    ) -> None:
        m = self.controller.state.manual_commands
        if inlet_pct is not None:
            m.inlet_valve_pct = min(max(inlet_pct, 0.0), 100.0)
        if outlet_pct is not None:
            m.outlet_valve_pct = min(max(outlet_pct, 0.0), 100.0)
        if pump_on is not None:
            m.pump_on = pump_on

    # ------------------------------------------------------------------ stepping
    def step(self) -> TelemetrySample:
        """Advance one sample interval and return the reported telemetry for it."""
        for hook in list(self.pre_sample_hooks):
            hook(self)
        prev = self.last_sample
        lvl1 = _num(prev.value("sensor.primary_level")) if prev else None
        lvl2 = _num(prev.value("sensor.secondary_level")) if prev else None
        qout = _num(prev.value("flow.outlet_lps")) if prev else None
        commands = self.controller.update(self.sim_time_s, self.cfg.sample_interval_s, lvl1, lvl2, qout)
        for _ in range(self._substeps):
            self.plant.step(commands, self._dt)
        self.sim_time_s = round(self.sim_time_s + self.cfg.sample_interval_s, 9)
        self.seq += 1
        sample = self._read_instruments()
        self.last_sample = sample
        return sample

    def _read_instruments(self) -> TelemetrySample:
        st = self.plant.state
        t = self.sim_time_s
        rng = self._rng_noise
        s = self.sensors
        ctl = self.controller.state
        h = self.cfg.tank.height_m

        lt101 = s.lt101.read(st.level_m, t, rng)
        lt102 = s.lt102.read(st.level_m, t, rng)
        ft101 = s.ft101.read(st.qin_lps, t, rng)
        ft102 = s.ft102.read(st.qout_lps, t, rng)
        pt101 = s.pt101.read(st.line_pressure_bar, t, rng)
        zt101 = s.zt101.read(st.inlet_pos_pct, t, rng)
        zt102 = s.zt102.read(st.outlet_pos_pct, t, rng)
        jt101 = s.jt101.read(st.pump_power_kw, t, rng)

        pct_value = None if lt101.value is None else round(float(lt101.value) / h * 100.0, 4)
        signals: dict[str, Reading] = {
            "tank.level_percent": Reading(
                pct_value, "%", lt101.source_time_s, lt101.quality, lt101.valid, "LT-101"
            ),
            "tank.level_meters": lt101,
            "sensor.primary_level": lt101,
            "sensor.secondary_level": lt102,
            "valve.inlet_command": Reading(round(ctl.commands.inlet_valve_pct, 3), "%", t, tag="XC-101"),
            "valve.inlet_position": zt101,
            "valve.outlet_command": Reading(round(ctl.commands.outlet_valve_pct, 3), "%", t, tag="XC-102"),
            "valve.outlet_position": zt102,
            "pump.command": Reading(bool(ctl.commands.pump_on), "bool", t, tag="HS-101"),
            "pump.running": Reading(bool(st.pump_speed > 0.5), "bool", t, tag="YS-101"),
            "pump.power_kw": jt101,
            "flow.inlet_lps": ft101,
            "flow.outlet_lps": ft102,
            "pressure.line_bar": pt101,
            "controller.mode": Reading(ctl.mode, "enum", t, tag="PLC-001"),
            "controller.health": Reading(ctl.health, "enum", t, tag="PLC-001"),
            "controller.setpoint_percent": Reading(round(ctl.setpoint_pct, 3), "%", t, tag="LIC-101.SP"),
        }
        return TelemetrySample(self.seq, t, self.epoch + timedelta(seconds=t), signals)

    def truth_dict(self) -> dict:
        """Physical ground truth (simulator only; never given to the detection engine)."""
        st = self.plant.state
        return {
            "level_m": round(st.level_m, 6),
            "level_pct": round(st.level_m / self.cfg.tank.height_m * 100.0, 4),
            "volume_m3": round(st.level_m * self.cfg.tank.area_m2, 6),
            "qin_lps": round(st.qin_lps, 4),
            "qout_lps": round(st.qout_lps, 4),
            "overflow_lps": round(st.overflow_lps, 4),
            "inlet_pos_pct": round(st.inlet_pos_pct, 3),
            "outlet_pos_pct": round(st.outlet_pos_pct, 3),
            "pump_speed": round(st.pump_speed, 4),
            "line_pressure_bar": round(st.line_pressure_bar, 5),
            "pump_power_kw": round(st.pump_power_kw, 4),
            "dry_running": st.dry_running,
            "interlock_high": self.controller.state.interlock_high,
            "interlock_low": self.controller.state.interlock_low,
            "faults": st.faults.active()
            + [
                f"{tag}:{_describe_sensor_fault(sen.fault)}"
                for tag, sen in self.sensors.by_tag().items()
                if sen.fault
            ],
        }


def _describe_sensor_fault(f) -> str:
    if f is None:
        return "none"
    if f.freeze != "none":
        return f"freeze-{f.freeze}"
    if f.drift_per_s:
        return f"drift={f.drift_per_s:+.4f}/s"
    return f"offset={f.offset_target:+.3f}"


def _num(v: object) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None
