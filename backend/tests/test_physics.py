"""Physical consistency of the digital twin."""

from __future__ import annotations

import itertools
import math

import pytest

from app.simulation.engine import SimulationEngine
from app.simulation.params import ControllerParams, SimulationConfig, static_head_bar
from app.simulation.plant import Commands, Plant
from app.simulation.sensors import SensorFault


def _conservation_error(plant: Plant, v0: float) -> float:
    st = plant.state
    return (plant.volume_m3 - v0) - (st.cum_in_m3 - st.cum_out_m3 - st.cum_overflow_m3)


def test_mass_is_conserved_in_normal_operation(engine: SimulationEngine) -> None:
    v0 = engine.plant.volume_m3
    for _ in range(3600):  # 30 simulated minutes
        engine.step()
    assert abs(_conservation_error(engine.plant, v0)) < 1e-9


def test_mass_is_conserved_through_overflow_and_dry_running() -> None:
    cfg = SimulationConfig(controller=ControllerParams(high_interlock_pct=100.0, pump_low_trip_pct=0.0))
    plant = Plant(cfg, Commands(100.0, 0.0, False))
    v0 = plant.volume_m3
    for _ in range(20000):  # fill well past the weir with outlet closed
        plant.step(Commands(100.0, 0.0, False), 0.1)
    assert plant.state.level_m == pytest.approx(cfg.tank.height_m)
    assert plant.state.cum_overflow_m3 > 1.0
    assert plant.state.overflow_lps == pytest.approx(cfg.inlet.max_flow_lps, rel=1e-6)
    dry = False
    for _ in range(40000):  # drain completely with the pump running
        plant.step(Commands(0.0, 100.0, True), 0.1)
        dry = dry or plant.state.dry_running
        assert plant.state.level_m >= 0.0
    assert plant.state.level_m == pytest.approx(0.0, abs=1e-9)
    assert dry
    assert abs(_conservation_error(plant, v0)) < 1e-8


def test_level_change_matches_flow_unit_conversion(cfg: SimulationConfig) -> None:
    plant = Plant(cfg, Commands(50.0, 0.0, False))
    plant.state.pump_speed = 0.0
    h0 = plant.state.level_m
    for _ in range(100):  # 10 s, inlet 50 % -> 30 L/s, outlet closed
        plant.step(Commands(50.0, 0.0, False), 0.1)
    expected = (cfg.inlet.max_flow_lps * 0.5 / 1000.0) * 10.0 / cfg.tank.area_m2
    assert plant.state.level_m - h0 == pytest.approx(expected, rel=1e-9)


def test_stopped_pump_produces_no_outflow_and_static_pressure(cfg: SimulationConfig) -> None:
    plant = Plant(cfg, Commands(0.0, 100.0, False))
    plant.state.pump_speed = 0.0
    for _ in range(50):
        plant.step(Commands(0.0, 100.0, False), 0.1)
    assert plant.state.qout_lps == 0.0
    assert plant.state.line_pressure_bar == pytest.approx(static_head_bar(plant.state.level_m))


def test_deadheaded_pump_reaches_shutoff_pressure(cfg: SimulationConfig) -> None:
    plant = Plant(cfg, Commands(0.0, 0.0, True))
    for _ in range(100):
        plant.step(Commands(0.0, 0.0, True), 0.1)
    st = plant.state
    assert st.qout_lps == 0.0
    assert st.line_pressure_bar == pytest.approx(static_head_bar(st.level_m) + cfg.pump.shutoff_bar)


def test_outlet_flow_satisfies_pump_and_valve_equations(cfg: SimulationConfig) -> None:
    plant = Plant(cfg, Commands(0.0, 60.0, True))
    for _ in range(100):
        plant.step(Commands(0.0, 60.0, True), 0.1)
    st = plant.state
    q = st.qout_lps
    # valve equation evaluated at the computed line pressure must return the same flow
    q_valve = (
        cfg.outlet.valve_kv_lps_per_sqrt_bar
        * 0.6
        * math.sqrt(st.line_pressure_bar - cfg.outlet.back_pressure_bar)
    )
    assert q == pytest.approx(q_valve, rel=1e-3)
    assert 0 < q <= cfg.max_outlet_flow_lps()


def test_valve_actuator_is_rate_limited(cfg: SimulationConfig) -> None:
    plant = Plant(cfg, Commands(0.0, 50.0, True))
    plant.state.inlet_pos_pct = 0.0
    positions = []
    for _ in range(120):
        plant.step(Commands(100.0, 50.0, True), 0.1)
        positions.append(plant.state.inlet_pos_pct)
    # 10 %/s -> 5 s reach 50 %, 10 s reach 100 %
    assert positions[49] == pytest.approx(50.0, abs=1e-6)
    assert positions[99] == pytest.approx(100.0, abs=1e-6)
    assert max(b - a for a, b in itertools.pairwise(positions)) <= cfg.valve.travel_rate_pct_s * 0.1 + 1e-9


def test_pump_speed_follows_first_order_dynamics(cfg: SimulationConfig) -> None:
    plant = Plant(cfg, Commands(0.0, 50.0, False))
    plant.state.pump_speed = 0.0
    for _ in range(round(cfg.pump.spin_tau_s / 0.1)):
        plant.step(Commands(0.0, 50.0, True), 0.1)
    assert plant.state.pump_speed == pytest.approx(1 - math.exp(-1), abs=0.01)


def test_seeded_runs_are_reproducible() -> None:
    a, b = SimulationEngine(SimulationConfig(seed=7)), SimulationEngine(SimulationConfig(seed=7))
    c = SimulationEngine(SimulationConfig(seed=8))
    sa = [a.step().to_dict() for _ in range(300)]
    sb = [b.step().to_dict() for _ in range(300)]
    sc = [c.step().to_dict() for _ in range(300)]
    assert sa == sb
    assert sa != sc


def test_normal_operation_holds_setpoint(engine: SimulationEngine) -> None:
    levels = []
    for _ in range(3600):
        engine.step()
        levels.append(engine.truth_dict()["level_pct"])
    assert max(abs(v - 60.0) for v in levels) < 2.0


def test_reported_values_are_separate_from_truth(engine: SimulationEngine) -> None:
    for _ in range(20):
        engine.step()
    truth = engine.plant.state.level_m
    lt = engine.sensors.lt101
    lt.fault = SensorFault(offset_target=-1.0, onset_time_s=engine.sim_time_s)
    s = engine.step()
    reported = float(s.value("sensor.primary_level"))  # type: ignore[arg-type]
    assert engine.plant.state.level_m == pytest.approx(truth, abs=0.01)  # physics untouched
    assert reported == pytest.approx(engine.plant.state.level_m - 1.0, abs=0.03)


def test_stale_sensor_keeps_old_source_timestamp(engine: SimulationEngine) -> None:
    for _ in range(10):
        engine.step()
    engine.sensors.lt102.fault = SensorFault(freeze="stale", onset_time_s=engine.sim_time_s)
    held = engine.last_sample.signals["sensor.secondary_level"]  # type: ignore[union-attr]
    for _ in range(10):
        s = engine.step()
    r = s.signals["sensor.secondary_level"]
    assert r.value == held.value
    assert r.source_time_s == held.source_time_s
    assert s.sim_time_s - r.source_time_s == pytest.approx(5.0)


def test_high_level_interlock_protects_tank() -> None:
    eng = SimulationEngine(SimulationConfig())
    eng.set_mode("manual")
    eng.set_manual_commands(inlet_pct=100.0, outlet_pct=0.0)
    for _ in range(4000):
        eng.step()
    assert eng.controller.state.interlock_high
    assert eng.truth_dict()["level_pct"] < 97.0
    assert eng.plant.state.cum_overflow_m3 == 0.0
