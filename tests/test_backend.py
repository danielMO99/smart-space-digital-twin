import asyncio
from copy import deepcopy
import json
import time

from fastapi.testclient import TestClient
import pytest

from backend.app.main import StateHub, create_app, process_frame
from simulator.simulate_radar import load_config, make_frame, trajectory


@pytest.mark.parametrize("rotation", [0, 90, -45, 180])
def test_round_trip(rotation):
    config = load_config()
    config["radar"]["rotation_deg"] = rotation
    state = process_frame(make_frame(config, 12), config)
    for target in state["targets"]:
        x, y, *_ = trajectory(config["room"], target["slot"], 12)
        assert target["x_m"] == pytest.approx(x, abs=0.001)
        assert target["y_m"] == pytest.approx(y, abs=0.001)
        assert target["inside_room"]


def test_boundaries_and_units():
    config = load_config()
    raw = make_frame(config, 0)
    raw["targets"] = [{"slot": 1, "x_mm": -2000, "y_mm": -600, "speed_cm_s": -35},
                      {"slot": 2, "x_mm": 2000, "y_mm": 4400, "speed_cm_s": 0},
                      {"slot": 3, "x_mm": 2001, "y_mm": 4400, "speed_cm_s": 0}]
    targets = process_frame(raw, config)["targets"]
    assert [t["inside_room"] for t in targets] == [True, True, False]
    assert targets[0]["speed_m_s"] == -0.35
    assert targets[2]["x_m"] == 4.001


@pytest.mark.parametrize("change", [
    {"schema_version": 2}, {"schema_version": True}, {"radar_id": "unknown"},
    {"timestamp": "2026-01-01T00:00:00"}, {"targets": [{"slot": 1}]},
    {"targets": [{"slot": 1, "x_mm": 0, "y_mm": 0, "speed_cm_s": float("nan")}]},
    {"targets": [{"slot": 1, "x_mm": True, "y_mm": 0, "speed_cm_s": 0}]},
])
def test_invalid_does_not_replace_state(change):
    hub = StateHub(load_config())
    raw = make_frame(hub.config, 0)
    hub.publish(raw)
    previous = hub.latest
    with pytest.raises(ValueError):
        hub.publish({**raw, **change})
    assert hub.latest is previous


def test_duplicate_and_empty_targets():
    config = load_config()
    raw = make_frame(config, 0)
    raw["targets"] = [raw["targets"][0]] * 2
    with pytest.raises(ValueError):
        process_frame(raw, config)
    raw["targets"] = []
    assert process_frame(raw, config)["targets"] == []


def test_slow_subscriber_keeps_only_latest():
    hub = StateHub(load_config())
    queue = asyncio.Queue(maxsize=1)
    hub.subscribers.add(queue)
    for elapsed in range(10):
        hub.publish(make_frame(hub.config, elapsed))
    assert queue.qsize() == 1
    assert queue.get_nowait() is hub.latest


def test_http_websocket_fanout_and_shutdown():
    app = create_app()
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert client.get("/api/room").json() == load_config()
        assert len(client.get("/api/state").json()["targets"]) == 3
        with client.websocket_connect("/ws") as first, client.websocket_connect("/ws") as second:
            first.receive_json()
            second.receive_json()
            start = time.monotonic()
            for _ in range(5):
                a, b = first.receive_json(), second.receive_json()
                assert a == b
            assert 0.25 < time.monotonic() - start < 2
        # Allow disconnect handlers to run before checking cleanup.
        for _ in range(100):
            if not app.state.hub.subscribers:
                break
            time.sleep(0.01)
        assert not app.state.hub.subscribers
    assert app.state.producer.cancelled()


def test_disabled_simulation(tmp_path):
    config = deepcopy(load_config())
    config["simulation"]["enabled"] = False
    path = tmp_path / "room.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    app = create_app(path)
    with TestClient(app) as client:
        assert client.get("/api/state").json() is None
        assert client.get("/health").json()["simulation_enabled"] is False
        with client.websocket_connect("/ws"):
            pass
    assert app.state.producer is None
