"""Configurable parameters of the synthetic plant.

All values are documented in docs/PHYSICS_MODEL.md. They describe a *simplified, internally
consistent* model; they are not data sheets of real equipment.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

RHO_WATER = 998.0  # kg/m3
GRAVITY = 9.81  # m/s2
PA_PER_BAR = 1.0e5


def static_head_bar(level_m: float) -> float:
    """Hydrostatic pressure of a water column of ``level_m`` metres, in bar."""
    return RHO_WATER * GRAVITY * max(level_m, 0.0) / PA_PER_BAR


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TankParams(_Frozen):
    area_m2: float = Field(12.0, gt=0.5, le=500.0, description="Constant cross-sectional area A")
    height_m: float = Field(5.0, gt=0.5, le=50.0, description="Height of the overflow weir")
    initial_level_m: float = Field(3.0, ge=0.0, le=50.0)


class InletParams(_Frozen):
    max_flow_lps: float = Field(
        60.0, gt=0.0, le=2000.0, description="Inlet flow at 100 % valve opening (constant supply head)"
    )


class PumpParams(_Frozen):
    shutoff_bar: float = Field(2.5, gt=0.1, le=50.0, description="Pump differential pressure at zero flow")
    curve_k_bar_per_lps2: float = Field(
        4.0e-4, gt=0.0, le=1.0, description="Quadratic head-drop coefficient dP = P0*s^2 - k*Q^2"
    )
    spin_tau_s: float = Field(1.5, gt=0.0, le=60.0, description="First-order speed time constant")
    idle_kw: float = Field(1.5, ge=0.0, le=500.0, description="Motor no-load losses")
    efficiency: float = Field(0.65, gt=0.05, le=1.0, description="Hydraulic efficiency")


class OutletParams(_Frozen):
    valve_kv_lps_per_sqrt_bar: float = Field(
        39.0, gt=0.0, le=5000.0, description="Outlet valve flow coefficient at 100 % opening"
    )
    back_pressure_bar: float = Field(
        0.6, ge=0.0, le=50.0, description="Downstream back pressure (discharge elevation)"
    )


class ValveParams(_Frozen):
    travel_rate_pct_s: float = Field(10.0, gt=0.1, le=200.0, description="Actuator stroking speed")


class SensorNoiseParams(_Frozen):
    level_m: float = Field(0.004, ge=0.0, le=0.5)
    flow_lps: float = Field(0.15, ge=0.0, le=50.0)
    pressure_bar: float = Field(0.01, ge=0.0, le=5.0)
    position_pct: float = Field(0.3, ge=0.0, le=10.0)
    power_kw: float = Field(0.05, ge=0.0, le=10.0)
    flow_cutoff_lps: float = Field(0.2, ge=0.0, le=10.0, description="Low-flow cut-off of the flow meters")


class ControllerParams(_Frozen):
    setpoint_pct: float = Field(60.0, ge=5.0, le=95.0)
    kp: float = Field(8.0, ge=0.0, le=500.0, description="Proportional gain [% valve / % level]")
    ki: float = Field(0.016, ge=0.0, le=50.0, description="Integral gain [% valve / (% level * s)]")
    feedforward_gain: float = Field(0.9, ge=0.0, le=1.5, description="Outlet-flow feed-forward ratio")
    demand_base_pct: float = Field(50.0, ge=0.0, le=100.0)
    demand_amplitude_pct: float = Field(8.0, ge=0.0, le=50.0)
    demand_period_s: float = Field(600.0, gt=10.0, le=86400.0)
    demand_step_pct: float = Field(10.0, ge=0.0, le=40.0, description="Max magnitude of seeded demand steps")
    demand_step_interval_s: float = Field(150.0, gt=10.0, le=86400.0)
    high_interlock_pct: float = Field(95.0, ge=50.0, le=100.0, description="Inlet closes above this level")
    pump_low_trip_pct: float = Field(5.0, ge=0.0, le=50.0, description="Pump stops below this level")
    pump_restart_pct: float = Field(10.0, ge=0.0, le=60.0)


class SimulationConfig(_Frozen):
    seed: int = Field(1337, ge=0, le=2**31 - 1)
    physics_dt_s: float = Field(0.1, gt=0.001, le=1.0)
    sample_interval_s: float = Field(0.5, ge=0.1, le=10.0)
    tank: TankParams = TankParams()
    inlet: InletParams = InletParams()
    pump: PumpParams = PumpParams()
    outlet: OutletParams = OutletParams()
    valve: ValveParams = ValveParams()
    noise: SensorNoiseParams = SensorNoiseParams()
    controller: ControllerParams = ControllerParams()

    def max_outlet_flow_lps(self) -> float:
        """Upper bound of outlet flow: full valve, full pump, full tank (closed-form, see docs)."""
        k = self.outlet.valve_kv_lps_per_sqrt_bar
        drive = static_head_bar(self.tank.height_m) + self.pump.shutoff_bar - self.outlet.back_pressure_bar
        if drive <= 0:
            return 0.0
        return float(k * (drive / (1.0 + k * k * self.pump.curve_k_bar_per_lps2)) ** 0.5)
