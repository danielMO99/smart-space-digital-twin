"""P1.1b updates to P1.1a: ingestion survives invalid data; absence is unknown."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
import time

from fastapi.testclient import TestClient
import pytest

from backend.app import mqtt_consumer as consumer
from backend.app.main import create_app
from mqtt_capture.isolated_broker import IsolatedBroker, MqttPublisher
from mqtt_capture.replay import load_capture
from mqtt_capture.replay_app import Evidence, ReplaySession

pytestmark = pytest.mark.mqtt
FIXTURES = Path(__file__).parent / "fixtures" / "mqtt_replay"


@contextmanager
def application(path, tmp_path, *, speed="1", allow_incomplete=False, manual_start=False):
    executable = os.environ.get("SMARTSPACE_TEST_MOSQUITTO")
    if not executable:
        pytest.fail("SMARTSPACE_TEST_MOSQUITTO must select a local executable")
    capture = load_capture(path, allow_incomplete=allow_incomplete)
    evidence = Evidence(tmp_path / "evidence")
    try:
        with IsolatedBroker(executable) as broker:
            session = ReplaySession(capture, broker, capture_name=path.name, speed=speed,
                                    evidence=evidence, start_delay=0, manual_start=manual_start)
            with TestClient(create_app(replay_session=session)) as client:
                yield client, session, broker
    finally:
        evidence.close()


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_real_capture_generates_observed_positions_without_counter(tmp_path):
    source = os.environ.get("SMARTSPACE_REPLAY_CAPTURE")
    if not source:
        pytest.skip("Physical capture is local, not a versioned fixture")
    with application(Path(source), tmp_path, speed="100") as (client, session, broker):
        frames = []
        with client.websocket_connect("/ws") as ws:
            for _ in range(6):
                frames.append(ws.receive_json())
                if session.summary is not None and session.state["consumer_received"] == 767:
                    break
        assert session.summary["status"] == "complete"
        assert session.summary["omitted_retained"] == 10
        assert session.state["consumer_received"] == 767
        assert session.state["consumer_errors"] == 0
        assert frames and any(frame["targets"] for frame in frames)
        assert session.consumer.normalizer.count is None
        assert client.get("/api/state").json()["observation"]["reported_count"] is None
        assert client.get("/api/runtime").json()["mode"] == "replay"
        assert client.get("/health").status_code == 200
        assert 'id="replay-banner"' in client.get("/").text
    received = rows(tmp_path / "evidence" / "received.jsonl")
    capture = load_capture(source)
    expected = [(r["topic"], capture.payloads[r["sequence"]]) for r in capture.records
                if r["record_type"] == "message" and not r["retain"]]
    assert [(r["topic"], base64.b64decode(r["payload_base64"])) for r in received] == expected
    assert all(r["qos"] == 0 and not r["retain"] for r in received)  # existing subscribe QoS=0
    states = rows(tmp_path / "evidence" / "states.jsonl")
    assert all(frame in [r["state"] for r in states] for frame in frames)


def test_existing_fixture_invalid_payloads_do_not_stop_reception(tmp_path):
    with application(FIXTURES / "multi_target.synthetic.mqtt.jsonl", tmp_path,
                     speed="0.5") as (client, session, broker):
        counts = []
        with client.websocket_connect("/ws") as ws:
            for _ in range(14):
                counts.append(len(ws.receive_json()["targets"]))
                if session.summary is not None:
                    break
        assert any(count > 0 for count in counts) and counts[-1] == 0
        assert session.state["consumer_errors"] > 0
        assert session.state["consumer_received"] == 24  # all deliveries survive invalid payloads
        assert session.summary["published"] == 24
        assert client.get("/health").status_code == 200  # invalid payloads do not kill reception
        assert session.client._thread.is_alive()
    received = rows(tmp_path / "evidence" / "received.jsonl")
    assert any(r["error_type"] == "invalid" for r in received)
    states = rows(tmp_path / "evidence" / "states.jsonl")
    assert all(r["state"]["observation"]["occupancy"] == "unknown" for r in states)


def test_source_disconnect_event_does_not_disconnect_backend(tmp_path):
    with application(FIXTURES / "reconnection.synthetic.mqtt.jsonl", tmp_path,
                     allow_incomplete=True, speed="10") as (client, session, broker):
        with client.websocket_connect("/ws") as ws:
            ws.receive_json()
        assert session.summary["events_observed"] == 6
        assert session.state["consumer_connected"]
        assert session.state["consumer_received"] == 2
        assert client.get("/api/state").json()["targets"] == []  # only X, never Y
        transport = rows(tmp_path / "evidence" / "transport.jsonl")
        assert not any(r["event"] == "backend_disconnected" for r in transport)


def test_actual_consumer_disconnect_expiry_and_recovery(tmp_path):
    with application(FIXTURES / "reconnection.synthetic.mqtt.jsonl", tmp_path,
                     allow_incomplete=True, manual_start=True) as (client, session, broker):
        assert session.ready.wait(5)
        topic = "smartspace/esp32/sensor/"
        with MqttPublisher(broker) as publisher, client.websocket_connect("/ws") as ws:
            def send(sensor, value):
                publisher.publish(topic + sensor + "/state", value.encode(), qos=1)
            send("n__mero_de_objetivos", "1")
            send("objetivo_1_x", "100")
            send("objetivo_1_y", "1000")
            for _ in range(3):
                if ws.receive_json()["targets"]:
                    break
            else:
                pytest.fail("Expected a visible target before disconnect")
            session.client.disconnect()
            session.client.loop_stop()
            for _ in range(4):
                if not ws.receive_json()["targets"]:
                    break
            else:
                pytest.fail("Position did not expire")
            assert client.get("/health").status_code == 503
            session.ready.clear()
            session.client.reconnect()
            session.client.loop_start()
            assert session.ready.wait(5)
            # Recovery depends on fresh X/Y, not on a cached counter.
            send("objetivo_1_x", "200")
            send("objetivo_1_y", "1100")
            for _ in range(3):
                frame = ws.receive_json()
                if frame["targets"]:
                    assert frame["targets"][0]["x_m"] == 2.2
                    break
            else:
                pytest.fail("No recovery after refreshing X/Y")
