"""Keep the default suite independent of the developer's radar environment."""

import paho.mqtt.client as mqtt
import pytest


@pytest.fixture(autouse=True)
def isolate_local_tests(request, monkeypatch):
    if request.node.get_closest_marker("mqtt") or request.node.get_closest_marker("hardware"):
        return

    # An exported SMARTSPACE_SOURCE=ld2450 must not connect local tests to a radar.
    monkeypatch.setenv("SMARTSPACE_SOURCE", "simulator")

    def reject_mqtt_connection(*args, **kwargs):
        pytest.fail("Local tests must not connect to MQTT; mark external tests with mqtt/hardware.")

    for method in ("connect", "connect_async", "reconnect"):
        monkeypatch.setattr(mqtt.Client, method, reject_mqtt_connection)
