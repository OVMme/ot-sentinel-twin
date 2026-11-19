"""Physical truth of the synthetic plant: tank, valves, pump and hydraulics.

The model is intentionally simple but *closed*: every litre that enters or leaves the tank is
accounted for in the cumulative counters, including overflow and dry-running, so conservation
of mass can be verified exactly in tests (see tests/test_physics.py).

Hydraulics (all pressures gauge, bar; flows L/s):

* Inlet:  Qin = Qin_max * x_in                       (constant supply head, linear trim)
* Pump:   dP_pump(Q) = hf * s^2 * P0 - k_p * Q^2       (s = speed fraction, hf = head factor)
* Line:   P_line = P_static(h) + dP_pump(Qout)         (pressure at PT-101, pump discharge)
* Outlet: Qout = K * sqrt(P_line - P_back - P_restriction-free)  with K = Kv * x_out * (1 - r)

Solving the last two simultaneously gives the closed form used in ``_outlet_flow``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from .params import SimulationConfig, static_head_bar


@dataclass
class PlantFaults:
    """Physical faults that can be injected by the scenario manager (ground truth only)."""

    inlet_valve_stuck: bool = False
    outlet_valve_stuck: bool = False
    pump_head_factor: float = 1.0  # 1.0 = healthy impeller, <1 = degraded hydraulic output
    outlet_restriction: float = 0.0  # 0 = clear, 1 = fully blocked (downstream of PT-101)

    def active(self) -> list[str]:
        labels: list[str] = []
        if self.inlet_valve_stuck:
            labels.append("inlet_valve_stuck")
        if self.outlet_valve_stuck:
            labels.append("outlet_valve_stuck")
        if self.pump_head_factor < 0.999:
            labels.append(f"pump_head_factor={self.pump_head_factor:.2f}")
        if self.outlet_restriction > 0.001:
            labels.append(f"outlet_restriction={self.outlet_restriction:.2f}")
        return labels


@dataclass
class Commands:
    """Actuator commands issued by the controller (or the operator in manual mode)."""

    inlet_valve_pct: float = 50.0
    outlet_valve_pct: float = 50.0
    pump_on: bool = True


@dataclass
class PlantState:
    """Physical truth. Never exposed to the detection engine."""

    level_m: float
    inlet_pos_pct: float
    outlet_pos_pct: float
    pump_speed: float  # 0..1
    qin_lps: float = 0.0
    qout_lps: float = 0.0
    overflow_lps: float = 0.0
    line_pressure_bar: float = 0.0
    pump_power_kw: float = 0.0
    dry_running: bool = False
    # cumulative volumes (m3) for conservation checks
    cum_in_m3: float = 0.0
    cum_out_m3: float = 0.0
    cum_overflow_m3: float = 0.0
    sim_time_s: float = 0.0
    faults: PlantFaults = field(default_factory=PlantFaults)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["faults"] = self.faults.active()
        return d


def _approach(current: float, target: float, max_step: float) -> float:
    """Move ``current`` towards ``target`` by at most ``max_step`` (rate-limited actuator)."""
    delta = target - current
    if abs(delta) <= max_step:
        return target
    return current + math.copysign(max_step, delta)


class Plant:
    """Integrates the physical state forward in time with a fixed step."""

    def __init__(self, config: SimulationConfig, initial_commands: Commands | None = None) -> None:
        self.cfg = config
        cmds = initial_commands or Commands()
        level0 = min(max(config.tank.initial_level_m, 0.0), config.tank.height_m)
        self.state = PlantState(
            level_m=level0,
            inlet_pos_pct=cmds.inlet_valve_pct,
            outlet_pos_pct=cmds.outlet_valve_pct,
            pump_speed=1.0 if cmds.pump_on else 0.0,
        )
        self._update_algebraic()

    # ------------------------------------------------------------------ hydraulics
    @property
    def volume_m3(self) -> float:
        return self.cfg.tank.area_m2 * self.state.level_m

    def _inlet_flow(self) -> float:
        return self.cfg.inlet.max_flow_lps * self.state.inlet_pos_pct / 100.0

    def _pump_dp_at_zero(self) -> float:
        s = self.state.pump_speed
        return self.state.faults.pump_head_factor * s * s * self.cfg.pump.shutoff_bar

    def _outlet_flow(self) -> float:
        st = self.state
        k_valve = (
            self.cfg.outlet.valve_kv_lps_per_sqrt_bar
            * st.outlet_pos_pct
            / 100.0
            * (1.0 - min(max(st.faults.outlet_restriction, 0.0), 1.0))
        )
        drive = static_head_bar(st.level_m) + self._pump_dp_at_zero() - self.cfg.outlet.back_pressure_bar
        if drive <= 0.0 or k_valve <= 0.0:
            return 0.0
        kp = self.cfg.pump.curve_k_bar_per_lps2
        return k_valve * math.sqrt(drive / (1.0 + k_valve * k_valve * kp))

    def _update_algebraic(self) -> None:
        """Recompute flows, pressure and power from the current dynamic state."""
        st = self.state
        st.qin_lps = self._inlet_flow()
        st.qout_lps = self._outlet_flow()
        self._update_pressure_power()

    def _update_pressure_power(self) -> None:
        st = self.state
        dp_pump = self._pump_dp_at_zero() - self.cfg.pump.curve_k_bar_per_lps2 * st.qout_lps**2
        st.line_pressure_bar = static_head_bar(st.level_m) + max(dp_pump, 0.0)
        hydraulic_kw = (st.qout_lps / 1000.0) * max(dp_pump, 0.0) * 1.0e5 / 1000.0
        s = st.pump_speed
        st.pump_power_kw = (s**3) * self.cfg.pump.idle_kw + hydraulic_kw / self.cfg.pump.efficiency

    # ------------------------------------------------------------------ integration
    def step(self, commands: Commands, dt: float) -> None:
        """Advance physics by ``dt`` seconds (explicit Euler with exact boundary bookkeeping)."""
        st = self.state
        cfg = self.cfg
        rate = cfg.valve.travel_rate_pct_s * dt

        if not st.faults.inlet_valve_stuck:
            st.inlet_pos_pct = _approach(st.inlet_pos_pct, _clamp_pct(commands.inlet_valve_pct), rate)
        if not st.faults.outlet_valve_stuck:
            st.outlet_pos_pct = _approach(st.outlet_pos_pct, _clamp_pct(commands.outlet_valve_pct), rate)

        target_speed = 1.0 if commands.pump_on else 0.0
        st.pump_speed += (target_speed - st.pump_speed) * (1.0 - math.exp(-dt / cfg.pump.spin_tau_s))
        if abs(st.pump_speed - target_speed) < 1e-4:
            st.pump_speed = target_speed

        qin = self._inlet_flow()
        qout = self._outlet_flow()

        area = cfg.tank.area_m2
        vol = area * st.level_m
        vol_in = qin / 1000.0 * dt
        vol_out = qout / 1000.0 * dt
        new_vol = vol + vol_in - vol_out

        # Boundary 1: the pump cannot remove liquid that is not there.
        st.dry_running = False
        if new_vol < 0.0:
            vol_out = vol + vol_in
            qout = vol_out * 1000.0 / dt
            new_vol = 0.0
            st.dry_running = commands.pump_on

        # Boundary 2: excess above the weir leaves through the (unmeasured) overflow line.
        vol_overflow = 0.0
        max_vol = area * cfg.tank.height_m
        if new_vol > max_vol:
            vol_overflow = new_vol - max_vol
            new_vol = max_vol

        st.level_m = new_vol / area
        st.qin_lps = qin
        st.qout_lps = qout
        st.overflow_lps = vol_overflow * 1000.0 / dt
        st.cum_in_m3 += vol_in
        st.cum_out_m3 += vol_out
        st.cum_overflow_m3 += vol_overflow
        st.sim_time_s += dt
        self._update_pressure_power()


def _clamp_pct(v: float) -> float:
    return min(max(v, 0.0), 100.0)
