"""Record the existing LD2450 measurement topics as versioned JSONL."""

import argparse
import base64
from datetime import datetime, timezone
from importlib.metadata import version
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt
from .frames import FRAME_TOPIC, Analyzer


# Names already consumed by backend/app/mqtt_consumer.py; ESPHome adds /state.
# Deliberately excludes switches, commands, discovery, heartbeat and diagnostics.
TELEMETRY_TOPICS = (
    "smartspace/esp32/sensor/n__mero_de_objetivos/state",
    *(f"smartspace/esp32/sensor/objetivo_{slot}_{field}/state"
      for slot in range(1, 4) for field in ("x", "y", "velocidad")),
)
ALL_TELEMETRY_TOPICS = (*TELEMETRY_TOPICS, FRAME_TOPIC)
TOPIC_MODES = {"legacy": TELEMETRY_TOPICS, "frames": (FRAME_TOPIC,), "both": ALL_TELEMETRY_TOPICS}
FORMAT = "smartspace.mqtt.capture"
SCHEMA_VERSION = 1
SUBSCRIPTION_QOS = 2


class CaptureIOError(Exception):
    """Writing failed: never append a successful footer to a damaged stream."""


class JsonlWriter:
    def __init__(self, stream, *, clock_ns=time.monotonic_ns,
                 utc_now=lambda: datetime.now(timezone.utc), session_id=None):
        self.stream = stream
        self.clock_ns = clock_ns
        self.utc_now = utc_now
        self.session_id = session_id or str(uuid.uuid4())
        self.started_ns = clock_ns()
        self.sequence = 0
        self.failed = False

    def stamp(self):
        elapsed = self.clock_ns() - self.started_ns
        return {
            "timestamp_utc": self.utc_now().astimezone(timezone.utc).isoformat(
                timespec="microseconds").replace("+00:00", "Z"),
            "monotonic_ns": elapsed,
        }

    def emit(self, record_type, *, stamp=None, **fields):
        if self.failed:
            raise CaptureIOError()
        record = {
            "format": FORMAT,
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "sequence": self.sequence,
            "record_type": record_type,
            **(self.stamp() if stamp is None else stamp),
            **fields,
        }
        line = json.dumps(record, ensure_ascii=True, allow_nan=False) + "\n"
        try:
            if self.stream.write(line) != len(line):
                raise OSError("short write")
            self.stream.flush()
        except (OSError, ValueError) as error:
            self.failed = True
            raise CaptureIOError() from error
        self.sequence += 1


def reason_value(reason):
    return int(getattr(reason, "value", reason))


class Recorder:
    """One network loop and synchronous writes: no queue or latest-state discard."""

    def __init__(self, writer, client, topics=TELEMETRY_TOPICS):
        self.topics = tuple(topics)
        if self.topics not in TOPIC_MODES.values():
            raise ValueError("Topics no permitidos")
        self.frames = Analyzer()
        self.writer = writer
        self.client = client
        self.connected = False
        self.ready = False
        self.stopping = False
        self.connections = 0
        self.disconnects = 0
        self.errors = 0
        self.received = 0
        self.written = 0
        self.ignored = 0
        self.subscription_mid = None
        self.subscriptions = 0
        self.retry_requested = False
        self.fatal_reason = None
        client.on_connect = self.on_connect
        client.on_disconnect = self.on_disconnect
        client.on_subscribe = self.on_subscribe
        client.on_message = self.on_message

    def event(self, event, **fields):
        self.writer.emit("event", event=event, **fields)

    def error(self, stage, **fields):
        self.errors += 1
        self.event("error", stage=stage, **fields)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        code = reason_value(reason_code)
        if code != 0:
            self.error("connack", reason_code=code)
            return
        self.connections += 1
        self.connected = True
        self.ready = False
        self.event("connected" if self.connections == 1 else "reconnected",
                   connection=self.connections,
                   session_present=bool(flags.session_present))
        rc, self.subscription_mid = client.subscribe(
            [(topic, SUBSCRIPTION_QOS) for topic in self.topics])
        if rc != mqtt.MQTT_ERR_SUCCESS:
            self.error("subscribe", reason_code=int(rc))
            self.fatal_reason = "subscription_error"
        else:
            self.event("subscription_requested", mid=self.subscription_mid)

    def on_subscribe(self, client, userdata, mid, reason_codes, properties):
        codes = [reason_value(code) for code in reason_codes]
        if (mid != self.subscription_mid or len(codes) != len(self.topics)
                or any(code not in (0, 1, 2) for code in codes)):
            self.error("suback", mid=mid, reason_codes=codes)
            self.fatal_reason = "subscription_error"
            return
        self.ready = True
        self.subscriptions += 1
        self.event("subscribed", mid=mid, granted_qos=codes)

    def on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        self.ready = False
        self.event("disconnected", reason_code=reason_value(reason_code),
                   expected=self.stopping)
        if not self.stopping:
            self.retry_requested = True
            self.disconnects += 1
            self.event("possible_loss", cause="disconnect", lost_messages=None)

    def on_message(self, client, userdata, message):
        if message.topic not in self.topics:
            self.ignored += 1
            return
        stamp = self.writer.stamp()
        self.received += 1
        validation = ({"frame_validation": self.frames.feed(message.payload, retain=bool(message.retain))}
                      if message.topic == FRAME_TOPIC else {})
        self.writer.emit(
            "message", stamp=stamp, topic=message.topic,
            payload_base64=base64.b64encode(message.payload).decode("ascii"),
            qos=int(message.qos), retain=bool(message.retain),
            dup=bool(message.dup), mid=int(message.mid), connection=self.connections, **validation,
        )
        self.written += 1

    def run(self, broker, port, duration, stop, sleep):
        clock = self.writer.clock_ns
        deadline = self.writer.started_ns + int(duration * 1_000_000_000)
        retry_at = self.writer.started_ns
        attempt = 0
        active = False
        handshake_deadline = 0
        while clock() < deadline and not stop.is_set():
            if self.fatal_reason:
                return self.fatal_reason
            now = clock()
            remaining = (deadline - now) / 1_000_000_000
            if not active:
                if now < retry_at:
                    sleep(min(0.1, remaining, (retry_at - now) / 1_000_000_000))
                    continue
                attempt += 1
                self.event("connection_attempt" if attempt == 1 else "reconnection_attempt",
                           attempt=attempt)
                self.client.connect_timeout = min(2.0, remaining)
                try:
                    rc = self.client.connect(broker, port, keepalive=60)
                except OSError as error:
                    # Never log exception text, which may contain connection secrets.
                    self.error("connect", error_type=type(error).__name__)
                    retry_at = clock() + 1_000_000_000
                    continue
                if rc != mqtt.MQTT_ERR_SUCCESS:
                    self.error("connect", reason_code=int(rc))
                    retry_at = clock() + 1_000_000_000
                    continue
                active = True
                handshake_deadline = clock() + 5_000_000_000
            remaining = (deadline - clock()) / 1_000_000_000
            if remaining <= 0 or stop.is_set():
                break
            try:
                rc = self.client.loop(timeout=min(0.1, remaining))
            except OSError as error:
                self.error("network_loop", error_type=type(error).__name__)
                rc = mqtt.MQTT_ERR_CONN_LOST
            if rc != mqtt.MQTT_ERR_SUCCESS or self.retry_requested:
                if rc != mqtt.MQTT_ERR_SUCCESS:
                    self.error("network_loop", reason_code=int(rc))
                if not self.retry_requested:
                    self.event("possible_loss", cause="network_loop", lost_messages=None)
                self.retry_requested = False
                self.connected = self.ready = False
                active = False
                retry_at = clock() + 1_000_000_000
            elif not self.ready and clock() >= handshake_deadline:
                self.error("handshake_timeout")
                return "handshake_timeout"
        return self.fatal_reason or ("ctrl_c" if stop.is_set() else "duration")

    def close(self):
        self.stopping = True
        try:
            if not self.writer.failed:
                self.event("disconnect_requested")
        finally:
            if self.writer.failed:
                # Never append to a partially written JSON line.
                self.client.on_disconnect = None
            try:
                rc = self.client.disconnect()
                if rc not in (mqtt.MQTT_ERR_SUCCESS, mqtt.MQTT_ERR_NO_CONN):
                    if not self.writer.failed:
                        self.error("disconnect", reason_code=int(rc))
            except OSError as error:
                if not self.writer.failed:
                    self.error("disconnect", error_type=type(error).__name__)
            finally:
                # Also release the socket if a disk error interrupted a callback.
                connection = self.client.socket()
                if connection is not None:
                    connection.close()


def validate_options(broker, port, duration):
    try:
        ipaddress.ip_address(broker)
    except ValueError:
        if (len(broker) > 253 or not re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", broker)):
            raise ValueError("Broker: usa un host o IP, sin URL ni credenciales.") from None
    if not 1 <= port <= 65535:
        raise ValueError("El puerto debe estar entre 1 y 65535.")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("La duración debe ser positiva y finita.")


def capture(output, *, broker="192.168.1.200", port=1883, duration=60.0,
            client_factory=mqtt.Client, clock_ns=time.monotonic_ns,
            utc_now=lambda: datetime.now(timezone.utc), sleep=time.sleep,
            stop=None, stderr=None, topics_mode="legacy"):
    """Return 0 for an orderly capture with messages and no known gaps, else 1."""
    validate_options(broker, port, duration)
    if topics_mode not in TOPIC_MODES:
        raise ValueError("Modo de topics inválido")
    topics = TOPIC_MODES[topics_mode]
    stop = stop if stop is not None else threading.Event()
    stderr = stderr if stderr is not None else sys.stderr
    output = Path(output)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never overwrite or append to an earlier session.
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            writer = JsonlWriter(stream, clock_ns=clock_ns, utc_now=utc_now)
            writer.emit("session_start", metadata={
                "broker": broker, "port": port, "duration_seconds": duration,
                "topics": list(topics), "subscription_qos": SUBSCRIPTION_QOS,
                "mqtt_protocol": "3.1.1", "clean_session": True,
                "paho_mqtt_version": version("paho-mqtt"),
                "payload_encoding": "base64", "time_origin": "session_start",
                "lost_messages": None,
                "loss_detection": "unknown_without_source_sequence" if topics_mode == "legacy" else "frame_sequence_diagnostics",
                "timing_basis": "mqtt_receive",
            })
            try:
                client = client_factory(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"smartspace-recorder-{writer.session_id}",
                    clean_session=True, protocol=mqtt.MQTTv311,
                    reconnect_on_failure=False,
                )
            except Exception as error:
                writer.emit("event", event="error", stage="client_init",
                            error_type=type(error).__name__)
                print("Error al crear el cliente; captura incompleta.", file=stderr)
                return 1
            recorder = Recorder(writer, client, topics)
            try:
                reason = recorder.run(broker, port, duration, stop, sleep)
            except KeyboardInterrupt:
                reason = "ctrl_c"
            except CaptureIOError:
                raise
            except Exception as error:
                recorder.error("runtime", error_type=type(error).__name__)
                reason = "error"
            finally:
                recorder.close()
            if recorder.written == 0:
                recorder.error("no_telemetry")
            if recorder.subscriptions == 0:
                recorder.error("subscription_unconfirmed")
            complete = (reason in ("duration", "ctrl_c") and recorder.errors == 0
                        and recorder.disconnects == 0 and recorder.written > 0)
            # Sync the evidence before writing an orderly-termination marker.
            os.fsync(stream.fileno())
            writer.emit("session_end", finalized=True,
                        status="complete" if complete else "incomplete", reason=reason,
                        messages_received=recorder.received, messages_written=recorder.written,
                        ignored_messages=recorder.ignored, errors=recorder.errors,
                        unexpected_disconnects=recorder.disconnects,
                        connections=recorder.connections, lost_messages=None,
                        frame_analysis=recorder.frames.summary())
            os.fsync(stream.fileno())
        if not complete:
            print("Captura incompleta: consulta los eventos y el cierre del JSONL.", file=stderr)
        return 0 if complete else 1
    except (OSError, CaptureIOError) as error:
        # The file may be unwritable; report out of band and never leak raw errors.
        print(f"Error de archivo ({type(error).__name__}); captura incompleta. "
              "No se sobrescriben archivos existentes.", file=stderr)
        return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", default="192.168.1.200", help="Host/IP, sin credenciales")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--duration", type=float, default=60, help="Segundos, incluyendo reconexiones")
    parser.add_argument("--output", type=Path, required=True, help="JSONL nuevo; no sobrescribe")
    parser.add_argument("--topics", choices=tuple(TOPIC_MODES), default="legacy",
                        help="legacy: anteriores; frames: informes completos; both: ambos")
    args = parser.parse_args(argv)
    try:
        validate_options(args.broker, args.port, args.duration)
    except ValueError as error:
        parser.error(str(error))
    stop = threading.Event()
    # Do not interrupt a JSON write halfway through a line on Ctrl+C.
    previous = signal.signal(signal.SIGINT, lambda signum, frame: stop.set())
    try:
        return capture(args.output, broker=args.broker, port=args.port,
                       duration=args.duration, stop=stop, topics_mode=args.topics)
    finally:
        signal.signal(signal.SIGINT, previous)


if __name__ == "__main__":
    sys.exit(main())
