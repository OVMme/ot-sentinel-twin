#!/usr/bin/env python3
"""Generate labelled synthetic telemetry datasets (CSV) for offline analysis.

Each file contains reported telemetry, physical ground truth, detector analytics and a ground-truth
label column. Data is fully synthetic and deterministic for a given seed.

Usage:
    python scripts/generate_dataset.py --seed 1337 --out datasets/synthetic
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402
from app.detection.base import ProcessModel  # noqa: E402
from app.detection.engine import DetectionEngine  # noqa: E402
from app.scenarios.catalog import SCENARIOS  # noqa: E402
from app.scenarios.manager import ScenarioManager  # noqa: E402
from app.simulation.engine import SimulationEngine  # noqa: E402
from app.simulation.params import SimulationConfig  # noqa: E402

WARMUP_S, ACTIVE_S, COOLDOWN_S = 120.0, 240.0, 60.0


def generate(scenario_id: str, seed: int) -> pd.DataFrame:
    cfg = SimulationConfig(seed=seed)
    eng = SimulationEngine(cfg)
    mgr = ScenarioManager(eng)
    det = DetectionEngine(ProcessModel.from_config(cfg))
    rows = []
    label = "normal"
    phase_end = {
        "warmup": WARMUP_S,
        "active": WARMUP_S + ACTIVE_S,
        "cooldown": WARMUP_S + ACTIVE_S + COOLDOWN_S,
    }
    started = stopped = False
    while eng.sim_time_s < phase_end["cooldown"] - 1e-9:
        if not started and eng.sim_time_s >= phase_end["warmup"] - 1e-9:
            mgr.start(scenario_id)
            started = True
        if started and not stopped and eng.sim_time_s >= phase_end["active"] - 1e-9:
            mgr.stop("dataset window complete")
            stopped = True
        s = eng.step()
        r = det.process(s)
        act = mgr.active
        label = act.definition.id if act is not None and act.phase == "active" else "normal"
        truth = eng.truth_dict()
        row = {"seq": s.seq, "t_s": s.sim_time_s, "timestamp": s.to_dict()["ts"], "label": label}
        for name, rd in s.signals.items():
            row[name] = rd.value
            if name.startswith(("sensor.", "flow.", "pressure.")):
                row[f"{name}.quality"] = rd.quality
                row[f"{name}.age_s"] = round(s.sim_time_s - rd.source_time_s, 3)
        for k in ("level_m", "qin_lps", "qout_lps", "overflow_lps", "line_pressure_bar", "inlet_pos_pct"):
            row[f"truth.{k}"] = truth[k]
        a = r.analytics
        res = a.get("mass_residual_m3") or {}
        row["derived.mass_residual_lt101_m3"] = res.get("LT-101")
        row["derived.mass_residual_lt102_m3"] = res.get("LT-102")
        row["derived.disagreement_m"] = a.get("disagreement_m")
        row["derived.anomaly_score"] = a.get("anomaly_score")
        row["alerts_raised"] = ";".join(c.alert.rule_id for c in r.changes if c.change == "raised")
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--out", type=Path, default=ROOT / "datasets" / "synthetic")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for sid, d in SCENARIOS.items():
        df = generate(sid, args.seed)
        path = args.out / f"{d.code}_{sid}_seed{args.seed}.csv"
        df.to_csv(path, index=False, float_format="%.5g")
        alerts = int((df["alerts_raised"] != "").sum())
        print(f"{path.name}: {len(df)} rows, {alerts} samples with alert raises")


if __name__ == "__main__":
    main()
