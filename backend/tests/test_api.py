"""API, persistence, replay, reports, WebSocket and security controls."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import make_client, ticks


def _incident(client: TestClient) -> str:
    ticks(client, 240)
    assert client.post("/api/scenarios/sensor-manipulation/start", json={"params": {}}).status_code == 200
    ticks(client, 200)
    items = client.get("/api/incidents").json()["items"]
    assert items, "expected an incident"
    return items[0]["id"]


def test_health_assets_signals(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["synthetic_data_only"] is True
    assets = {a["id"] for a in client.get("/api/assets").json()}
    assert {"TANK-001", "XV-101", "XV-102", "P-101", "FT-101", "FT-102", "PT-101", "PLC-001"} <= assets
    names = {s["name"] for s in client.get("/api/signals").json()}
    assert "tank.level_percent" in names and "controller.health" in names


def test_simulation_lifecycle(client: TestClient) -> None:
    s = client.get("/api/simulation/state").json()
    assert s["status"] == "paused"
    run1 = s["run_id"]
    assert client.post("/api/simulation/start").json()["status"] == "running"
    assert client.post("/api/simulation/pause").json()["status"] == "paused"
    ticks(client, 20)
    r = client.post("/api/simulation/reset", json={}).json()
    assert r["run_id"] != run1 and r["sim_time_s"] == 0.0 and r["seq"] == 0
    assert client.post("/api/simulation/speed", json={"speed": 5}).json()["speed"] == 5
    assert client.post("/api/simulation/speed", json={"speed": 20}).status_code == 422  # above max_speed 10
    assert client.post("/api/simulation/speed", json={"speed": "fast"}).status_code == 422


def test_reset_restores_documented_initial_state(client: TestClient) -> None:
    ticks(client, 50)
    client.post("/api/scenarios/blocked-outlet/start", json={})
    ticks(client, 50)
    client.post("/api/simulation/reset", json={"seed": 99})
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    assert rt.scenarios.active is None
    assert rt.engine.faults.outlet_restriction == 0.0
    assert rt.engine.plant.state.level_m == rt.config.tank.initial_level_m
    assert rt.config.seed == 99


def test_operator_commands_require_manual_mode(client: TestClient) -> None:
    r = client.post("/api/simulation/operator", json={"inlet_valve_pct": 10})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_manual"
    assert client.post("/api/simulation/mode", json={"mode": "manual"}).json()["mode"] == "manual"
    r = client.post("/api/simulation/operator", json={"inlet_valve_pct": 10, "pump_on": False}).json()
    assert r["manual_commands"]["inlet_valve_pct"] == 10 and r["manual_commands"]["pump_on"] is False
    assert client.post("/api/simulation/operator", json={"inlet_valve_pct": 150}).status_code == 422
    assert client.post("/api/simulation/operator", json={"unknown": 1}).status_code == 422


def test_config_validation(client: TestClient) -> None:
    cfg = client.get("/api/simulation/config").json()["active"]
    bad = {**cfg, "tank": {**cfg["tank"], "area_m2": -1}}
    r = client.put("/api/simulation/config", json=bad)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_config"
    good = {**cfg, "seed": 4242}
    assert client.put("/api/simulation/config", json=good).json()["active"]["seed"] == 4242


def test_scenarios_list_start_stop(client: TestClient) -> None:
    sc = client.get("/api/scenarios").json()
    assert len(sc) == 8 and {s["code"] for s in sc} == set("ABCDEFGH")
    assert client.post("/api/scenarios/does-not-exist/start", json={}).status_code == 404
    r = client.post("/api/scenarios/sensor-drift/start", json={"params": {"drift_mm_s": 999}})
    assert r.status_code == 422
    r = client.post(
        "/api/scenarios/frozen-telemetry/start", json={"params": {"signal": "LT-101", "mode": "stale"}}
    )
    assert r.json()["scenario"]["params"] == {"signal": "LT-101", "mode": "stale"}
    ticks(client, 12)
    act = client.get("/api/scenarios/active").json()
    assert act["active"]["phase"] == "active"
    assert [e["kind"] for e in act["events"]][:2] == ["started", "fault_onset"]
    assert client.post("/api/scenarios/stop").json()["scenario"] is None


def test_telemetry_is_persisted_and_paginated(client: TestClient) -> None:
    ticks(client, 30)
    run = client.get("/api/simulation/state").json()["run_id"]
    page = client.get(f"/api/telemetry/history?run_id={run}&limit=10").json()
    assert len(page["items"]) == 10 and page["next_from_seq"] == 11
    full = client.get(f"/api/telemetry/history?run_id={run}&limit=1&full=true").json()["items"][0]
    sig = full["signals"]["sensor.primary_level"]
    assert {"v", "u", "t_src", "q", "valid", "tag"} <= set(sig)
    csv = client.get(f"/api/telemetry/export?run_id={run}&format=csv")
    assert csv.status_code == 200 and "attachment" in csv.headers["content-disposition"]
    assert csv.text.count("\n") == 31
    assert client.get("/api/telemetry/history?run_id=../../etc").status_code == 422


def test_incident_investigation_workflow(client: TestClient) -> None:
    iid = _incident(client)
    inc = client.get(f"/api/incidents/{iid}").json()
    assert inc["classification"] == "suspected_manipulation"
    assert inc["detections"] and inc["telemetry"] and inc["alternatives"]
    assert client.post(f"/api/incidents/{iid}/acknowledge").json()["status"] == "acknowledged"
    assert (
        client.post(f"/api/incidents/{iid}/status", json={"status": "investigating"}).json()["status"]
        == "investigating"
    )
    assert client.post(f"/api/incidents/{iid}/status", json={"status": "bogus"}).status_code == 422
    note = client.post(
        f"/api/incidents/{iid}/notes",
        json={"text": "Verified LT-102 locally"},
        headers={"X-Analyst": "analyst.one"},
    ).json()
    assert note["author"] == "analyst.one"
    assert client.post(f"/api/incidents/{iid}/notes", json={"text": ""}).status_code == 422
    ev = client.get(f"/api/incidents/{iid}/evidence")
    assert ev.headers["content-disposition"] == f'attachment; filename="otst-evidence-{iid}.json"'
    audit = client.get("/api/audit").json()["items"]
    actions = {a["action"] for a in audit}
    assert {"incident.acknowledge", "incident.status", "incident.note", "incident.export_evidence"} <= actions
    # detection updates from the runtime must not overwrite analyst status
    ticks(client, 40)
    assert client.get(f"/api/incidents/{iid}").json()["status"] == "investigating"
    assert client.get("/api/incidents/INC-9999").status_code == 404


def test_report_generation(client: TestClient) -> None:
    iid = _incident(client)
    md = client.get(f"/api/reports/{iid}?format=md").text
    for section in (
        "Executive summary",
        "Simulation identification",
        "Affected simulated assets",
        "Incident timeline",
        "Triggered detection rules",
        "Physical process discrepancies",
        "Supporting telemetry",
        "Detection methodology",
        "Evidence and limitations",
        "Recommended investigation steps",
        "Conclusions",
        "SIMULATED DATA",
    ):
        assert section in md
    js = client.get(f"/api/reports/{iid}?format=json&download=true")
    assert "attachment" in js.headers["content-disposition"]
    body = js.json()
    assert body["triggered_rules"] and body["simulator_ground_truth"]["events"]


def test_replay_is_recorded_not_regenerated(client: TestClient) -> None:
    ticks(client, 100)
    rt = client.app.state.runtime  # type: ignore[attr-defined]
    live = [s["signals"]["sensor.primary_level"]["v"] for s in list(rt.buffer)]
    run = rt.run_id
    rep1 = client.get(f"/api/replay/{run}").json()
    rep2 = client.get(f"/api/replay/{run}").json()
    assert rep1["columns"] == rep2["columns"]
    assert rep1["columns"]["lt101"] == live
    runs = client.get("/api/replay/runs").json()
    assert runs[0]["id"] == run and runs[0]["sample_count"] == 100
    seq = rep1["columns"]["seq"][10]
    assert client.get(f"/api/replay/{run}/sample/{seq}").json()["seq"] == seq


def test_detection_rules_endpoint_and_update(client: TestClient) -> None:
    rules = client.get("/api/detections/rules").json()
    assert {r["rule_id"] for r in rules} == {f"PHYS-00{i}" for i in range(1, 8)} | {"DATA-001"}
    r = client.put("/api/detections/rules/PHYS-002", json={"threshold": 0.2, "debounce_s": 6})
    assert r.json()["config"]["threshold"] == 0.2
    assert client.put("/api/detections/rules/PHYS-002", json={"threshold": -1}).status_code == 422
    assert client.put("/api/detections/rules/PHYS-999", json={"threshold": 1}).status_code == 404


def test_websocket_stream_and_origin_check(client: TestClient) -> None:
    with client.websocket_connect("/ws/telemetry") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["data"]["synthetic_data_only"] is True
        client.app.state.runtime.tick()  # type: ignore[attr-defined]
        msg = ws.receive_json()
        assert msg["type"] == "telemetry" and "signals" in msg["data"] and "truth" in msg["data"]
    with client.websocket_connect("/ws/telemetry", headers={"origin": "http://localhost:5173"}) as ws:
        assert ws.receive_json()["type"] == "hello"
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/telemetry", headers={"origin": "https://attacker.example"}) as ws,
    ):
        ws.receive_json()


def test_cors_is_restrictive(client: TestClient) -> None:
    ok = client.options(
        "/api/health", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = client.options(
        "/api/health", headers={"Origin": "https://attacker.example", "Access-Control-Request-Method": "GET"}
    )
    assert "access-control-allow-origin" not in bad.headers


def test_body_size_limit(client: TestClient) -> None:
    r = client.post(
        "/api/incidents/INC-0001/notes", content=b"x" * 70_000, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413


def test_read_only_mode(tmp_path: Path) -> None:
    with make_client(tmp_path, read_only=True) as c:
        assert c.get("/api/simulation/state").status_code == 200
        r = c.post("/api/simulation/start")
        assert r.status_code == 403 and r.json()["error"]["code"] == "read_only"
        assert c.post("/api/evaluation/run", json={"seeds": [1]}).status_code == 403


def test_api_token_and_rate_limit(tmp_path: Path) -> None:
    from app.api import deps

    deps.rate_limiter._hits.clear()
    with make_client(tmp_path, api_token="test-token-not-a-secret", rate_limit_per_minute=3) as c:
        assert c.post("/api/simulation/pause").status_code == 401
        h = {"X-API-Key": "test-token-not-a-secret"}
        codes = [c.post("/api/simulation/pause", headers=h).status_code for _ in range(4)]
        assert codes[:3] == [200, 200, 200] and codes[3] == 429
    deps.rate_limiter._hits.clear()


def test_security_headers(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"


def test_retention_bounds_runs(tmp_path: Path) -> None:
    with make_client(tmp_path, retention_runs=2) as c:
        for _ in range(4):
            ticks(c, 5)
            c.post("/api/simulation/reset", json={})
        assert len(c.get("/api/replay/runs").json()) == 2
