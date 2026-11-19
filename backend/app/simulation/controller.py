"""Simulated basic process control system (BPCS) for the tank.

* AUTO: PI level controller on LT-101 manipulating the inlet valve, with outlet-flow
  feed-forward (FT-102). Outlet valve follows a deterministic, seeded demand profile.
  Pump runs unless the independent level sensor LT-102 reports a low-low level.
  A high-level interlock on LT-102 closes the inlet valve.
* MANUAL: the operator sets valve commands and pump command directly. Interlocks stay active.

The controller only uses *reported* measurements, exactly like a real controller, which is
why sensor manipulation can drive the physical process away from its setpoint.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .params import ControllerParams, SimulationConfig
from .plant import Commands

Mode = Literal["auto", "manual"]


@dataclass
class ControllerState:
    mode: Mode = "auto"
    setpoint_pct: float = 60.0
    integral: float = 0.0
    commands: Commands = field(default_factory=Commands)
    manual_commands: Commands = field(default_factory=Commands)
    interlock_high: bool = False
    interlock_low: bool = False
    health: Literal["ok", "degraded"] = "ok"
    pv_filtered: float | None = None
    last_ff: float = 0.0


class DemandProfile:
    """Deterministic outlet demand: slow sinusoid plus seeded step changes."""

    def __init__(self, params: ControllerParams, seed: int) -> None:
        self.p = params
        rng = np.random.default_rng(seed + 7919)
        horizon_steps = 2000
        self._steps = rng.uniform(-1.0, 1.0, size=horizon_steps) * params.demand_step_pct

    def value(self, t: float) -> float:
        p = self.p
        idx = int(t // p.demand_step_interval_s) % len(self._steps)
        step = self._steps[idx] if t >= p.demand_step_interval_s else 0.0
        v = p.demand_base_pct + p.demand_amplitude_pct * math.sin(2 * math.pi * t / p.demand_period_s) + step
        return min(max(v, 5.0), 95.0)


class LevelController:
    def __init__(self, cfg: SimulationConfig) -> None:
        self.cfg = cfg
        self.p = cfg.controller
        self.demand = DemandProfile(cfg.controller, cfg.seed)
        self.state = ControllerState(setpoint_pct=cfg.controller.setpoint_pct)
        # initial commands consistent with a steady state at the initial level
        demand0 = self.demand.value(0.0)
        self.state.commands = Commands(inlet_valve_pct=demand0, outlet_valve_pct=demand0, pump_on=True)
        self.state.manual_commands = Commands(demand0, demand0, True)

    def initialise_steady_state(self, outlet_flow_lps: float) -> None:
        """Pre-load the integrator so the loop starts balanced (no start-up transient)."""
        ff = self.p.feedforward_gain * outlet_flow_lps / self.cfg.inlet.max_flow_lps * 100.0
        balanced = outlet_flow_lps / self.cfg.inlet.max_flow_lps * 100.0
        self.state.integral = balanced - ff
        self.state.last_ff = ff
        self.state.commands.inlet_valve_pct = balanced

    def update(
        self,
        t: float,
        dt: float,
        level_primary_m: float | None,
        level_secondary_m: float | None,
        outlet_flow_lps: float | None,
    ) -> Commands:
        st = self.state
        h = self.cfg.tank.height_m
        pv = None if level_primary_m is None else level_primary_m / h * 100.0
        sis = None if level_secondary_m is None else level_secondary_m / h * 100.0

        st.health = "ok" if pv is not None else "degraded"

        # Interlocks use the independent sensor LT-102 (separation of control and protection).
        if sis is not None:
            if sis >= self.p.high_interlock_pct:
                st.interlock_high = True
            elif sis < self.p.high_interlock_pct - 5.0:
                st.interlock_high = False
            if sis <= self.p.pump_low_trip_pct:
                st.interlock_low = True
            elif sis >= self.p.pump_restart_pct:
                st.interlock_low = False

        if st.mode == "auto":
            demand = self.demand.value(t)
            inlet = st.commands.inlet_valve_pct
            if pv is not None:
                # light PV filter (tau = 2 s) to keep valve chatter low with noisy level
                alpha = min(dt / 2.0, 1.0)
                st.pv_filtered = (
                    pv if st.pv_filtered is None else st.pv_filtered + alpha * (pv - st.pv_filtered)
                )
                err = st.setpoint_pct - st.pv_filtered
                ff = st.last_ff
                if outlet_flow_lps is not None:
                    ff = self.p.feedforward_gain * outlet_flow_lps / self.cfg.inlet.max_flow_lps * 100.0
                    st.last_ff = ff
                unclamped = ff + self.p.kp * err + st.integral + self.p.ki * err * dt
                # conditional integration anti-windup
                if (
                    0.0 < unclamped < 100.0
                    or (unclamped >= 100.0 and err < 0)
                    or (unclamped <= 0 and err > 0)
                ):
                    st.integral += self.p.ki * err * dt
                st.integral = min(max(st.integral, -100.0), 100.0)
                inlet = min(max(ff + self.p.kp * err + st.integral, 0.0), 100.0)
            st.commands = Commands(inlet_valve_pct=inlet, outlet_valve_pct=demand, pump_on=True)
        else:
            m = st.manual_commands
            st.commands = Commands(m.inlet_valve_pct, m.outlet_valve_pct, m.pump_on)

        if st.interlock_high:
            st.commands.inlet_valve_pct = 0.0
        if st.interlock_low:
            st.commands.pump_on = False
        return st.commands

    def set_mode(self, mode: Mode) -> None:
        if mode == self.state.mode:
            return
        if mode == "manual":
            c = self.state.commands
            self.state.manual_commands = Commands(c.inlet_valve_pct, c.outlet_valve_pct, c.pump_on)
        else:
            # bumpless transfer: back-calculate the integral so the first AUTO output equals
            # the last MANUAL output (given the last known PV and feed-forward term).
            st = self.state
            err = 0.0 if st.pv_filtered is None else st.setpoint_pct - st.pv_filtered
            st.integral = st.commands.inlet_valve_pct - st.last_ff - self.p.kp * err
        self.state.mode = mode
