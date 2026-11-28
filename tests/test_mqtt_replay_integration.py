"""Explicit opt-in: starts an owned loopback broker, never uses production."""
import os
from pathlib import Path
import threading
import uuid

import paho.mqtt.client as mqtt
import pytest

from mqtt_capture.isolated_broker import IsolatedBroker, MqttPublisher
from mqtt_capture.record import TELEMETRY_TOPICS
from mqtt_capture.replay import load_capture, replay, VirtualClock

pytestmark = pytest.mark.mqtt
FIXTURE = Path(__file__).parent / "fixtures" / "mqtt_replay" / "multi_target.synthetic.mqtt.jsonl"


@pytest.fixture
def broker():
    executable = os.environ.get("SMARTSPACE_TEST_MOSQUITTO")
    if not executable:
        pytest.fail("Set SMARTSPACE_TEST_MOSQUITTO to a local mosquitto executable; no external broker allowed")
    with IsolatedBroker(executable) as instance:
        yield instance
    assert instance.process.poll() is not None


class Subscriber:
    def __init__(self, broker, expected=0):
        self.rows = []
        self.ready, self.received, self.any_message = threading.Event(), threading.Event(), threading.Event()
        self.expected = expected
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                                  client_id="replay-test-" + uuid.uuid4().hex,
                                  protocol=mqtt.MQTTv311, reconnect_on_failure=False)
        self.client.username_pw_set(broker.username, broker.password)
        self.client.on_connect = lambda client, *args: client.subscribe([(t, 2) for t in TELEMETRY_TOPICS])
        self.client.on_subscribe = lambda *args: self.ready.set()
        self.client.on_message = self.message
        self.broker = broker

    def message(self, client, userdata, message):
        self.rows.append((message.topic, message.payload, message.qos, message.retain))
        self.any_message.set()
        if len(self.rows) >= self.expected:
            self.received.set()

    def __enter__(self):
        self.client.connect(self.broker.host, self.broker.port)
        self.client.loop_start()
        if not self.ready.wait(5):
            self.__exit__(None, None, None)
            pytest.fail("Subscriber did not receive SUBACK")
        return self

    def __exit__(self, *exc):
        self.client.disconnect()
        self.client.loop_stop()


@pytest.mark.parametrize("source", ["synthetic", "real"])
def test_order_payload_qos_no_retain_and_late_subscriber(broker, source):
    path = FIXTURE
    if source == "real":
        path = os.environ.get("SMARTSPACE_REPLAY_CAPTURE")
        if not path:
            pytest.skip("Optional physical capture is local and is not versioned")
    capture = load_capture(path)
    first, second = [], []
    one = replay(capture, clock=VirtualClock(), emit=first.append)
    two = replay(capture, clock=VirtualClock(), emit=second.append)
    assert first == second and one == two
    assert [e["source_monotonic_ns"] for e in first] == [r["monotonic_ns"] for r in capture.records]
    expected = [(r["topic"], capture.payloads[r["sequence"]], 1, False)
                for r in capture.records if r["record_type"] == "message" and not r["retain"]]
    with Subscriber(broker, len(expected)) as subscriber, MqttPublisher(broker) as publisher:
        # Real broker/network, virtual schedule: this test checks transport, not wall-clock accuracy.
        summary = replay(capture, clock=VirtualClock(), publish=publisher.publish, check=publisher.check)
        assert summary["errors"] == 0 and summary["published"] == len(expected)
        assert subscriber.received.wait(10)
        assert subscriber.rows == expected
    # retain=False on a live subscriber alone would NOT prove the broker stored nothing.
    with Subscriber(broker) as late:
        assert not late.any_message.wait(0.5)
        assert late.rows == []


def test_actual_broker_failure_stops_replay_without_reconnecting(broker):
    capture = load_capture(FIXTURE)
    with MqttPublisher(broker) as publisher:
        def emit(event):
            if event["action"] == "publish":
                broker._stop()
        summary = replay(capture, clock=VirtualClock(), publish=publisher.publish, emit=emit,
                         check=publisher.check)
    assert summary["published"] == 1
    assert summary["errors"] == 1 and summary["not_replayed"] > 0
