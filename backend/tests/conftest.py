from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.detection.base import ProcessModel
from app.detection.engine import DetectionEngine
from app.main import create_app
from app.simulation.engine import SimulationEngine
from app.simulation.params import SimulationConfig


@pytest.fixture
def cfg() -> SimulationConfig:
    return SimulationConfig()


@pytest.fixture
def engine(cfg: SimulationConfig) -> SimulationEngine:
    return SimulationEngine(cfg)


@pytest.fixture
def detector(cfg: SimulationConfig) -> DetectionEngine:
    return DetectionEngine(ProcessModel.from_config(cfg))


def make_client(tmp_path: Path, **overrides: object) -> TestClient:
    os.environ["OTST_DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["OTST_AUTOSTART"] = "false"
    settings = Settings()
    if overrides:
        settings = Settings(**{**settings.__dict__, **overrides})
    return TestClient(create_app(settings, data_dir=tmp_path))


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(tmp_path) as c:
        yield c


def ticks(client: TestClient, n: int) -> None:
    """Advance the live runtime deterministically without wall-clock pacing."""
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    for _ in range(n):
        rt.tick()
    rt.flush_sync()
