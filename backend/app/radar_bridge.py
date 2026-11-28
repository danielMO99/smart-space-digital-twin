
"""Puente MQTT LD2450 -> StateHub de FastAPI."""

import asyncio
import math
import os

import paho.mqtt.client as mqtt

from backend.app import mqtt_consumer


def prepare_frame(raw, radar_id):
    """Adapta las mediciones MQTT al contrato de FastAPI."""

    targets = []

    for target in raw["targets"]:
        x = float(target["x_mm"])
        y = float(target["y_mm"])
        speed = target.get("speed_mm_s")

        if not math.isfinite(x) or not math.isfinite(y):
            continue

        # ESPHome: mm/s. Backend: cm/s.
        if speed is None:
            speed_cm_s = None
        else:
            speed = float(speed)
            if not math.isfinite(speed):
                continue
            speed_cm_s = speed / 10.0

        targets.append({
            "slot": int(target["slot"]),
            "x_mm": round(x),
            "y_mm": round(y),
            "speed_cm_s": None if speed_cm_s is None else float(speed_cm_s),
        })

        if "resolution_mm" in target:
            targets[-1]["resolution_mm"] = target["resolution_mm"]

    return {
        "schema_version": 1,
        "source": "ld2450",
        "radar_id": radar_id,
        "timestamp": raw["timestamp"],
        "targets": targets,
        **({"observation": raw["observation"]} if "observation" in raw else {}),
        **({"acquisition": raw["acquisition"]} if "acquisition" in raw else {}),
    }


async def run_radar(hub, *, replay_session=None):
    """Recibe MQTT y publica el estado en FastAPI."""

    consumer = replay_session.consumer if replay_session is not None else mqtt_consumer.MQTTConsumer(
        mode=os.getenv("SMARTSPACE_ACQUISITION", "legacy"))
    ws_hz = replay_session.ws_hz if replay_session is not None else float(os.getenv("SMARTSPACE_WS_HZ", "10"))
    if not math.isfinite(ws_hz) or not 0 < ws_hz <= 100:
        raise ValueError("WebSocket frequency must be in (0, 100] Hz")
    if consumer.mode == "frames":
        def accept(raw):
            hub.publish(prepare_frame(raw, hub.config["radar"]["id"]), notify=False)
        consumer.on_frame = accept
    hub.consumer = consumer
    hub.diagnostics = consumer.diagnostics
    hub.diagnostics.source = "replay" if replay_session is not None else "live"
    hub.diagnostics.ws_configured_hz = ws_hz if consumer.mode == "frames" else 1.0
    if replay_session is not None:
        # The replay session owns the isolated endpoint and its normalizer instance.
        client = replay_session.connect_consumer()
    else:
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="smartspace-fastapi-radar",
        )
        client.on_connect = consumer.on_connect
        client.on_message = consumer.on_message
        client.on_disconnect = consumer.on_disconnect
        client.connect(mqtt_consumer.BROKER, mqtt_consumer.PORT, 60)

    hub.mqtt_client = client
    client.loop_start()

    print("Puente LD2450 iniciado")

    try:
        while True:
            await asyncio.sleep(1.0 / ws_hz if consumer.mode == "frames" else 1.0)
            consumer.diagnostics.snapshot()
            if consumer.mode == "frames":
                with consumer.normalizer.lock:
                    raw = consumer.build_frame()
                    latest = hub.latest
                    if latest is None or latest["acquisition"]["telemetry_status"] != raw["acquisition"]["telemetry_status"]:
                        consumer.on_frame(raw)
                    state = hub.latest
                hub.broadcast()
                if replay_session is not None:
                    replay_session.observe_state(raw, prepare_frame(raw, hub.config["radar"]["id"]), state)
                continue

            raw = consumer.build_frame()

            frame = prepare_frame(
                raw,
                radar_id=hub.config["radar"]["id"],
            )

            hub.publish(frame)
            if replay_session is not None:
                replay_session.observe_state(raw, frame, hub.latest)

    finally:
        with consumer.normalizer.lock:
            consumer.on_frame = None
        client.disconnect()
        client.loop_stop()
