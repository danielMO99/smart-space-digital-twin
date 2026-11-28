"""Launch the application against an owned P0.3 test broker.

Normalization belongs to RadarNormalizer; this module owns isolation and evidence.
"""
import argparse
import asyncio
import base64
from contextlib import suppress
from copy import deepcopy
import json
import math
from pathlib import Path
import threading
import subprocess
import time
import uuid

import paho.mqtt.client as mqtt
import uvicorn

from .isolated_broker import IsolatedBroker, MqttPublisher
from .replay import load_capture, replay, speed_ratio


class Evidence:
    """Separate derived traces; exclusive files, serialized writes, no credentials."""
    def __init__(self, directory=None):
        self.lock = threading.RLock()
        self.origin = time.monotonic_ns()
        self.streams = {}
        self.sequence = 0
        self.directory = Path(directory) if directory is not None else None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=False)
            try:
                for name in ("replay", "received", "states", "transport"):
                    self.streams[name] = (self.directory / f"{name}.jsonl").open(
                        "x", encoding="utf-8", newline="\n")
            except BaseException:
                self.close()
                raise

    def write(self, channel, **data):
        with self.lock:
            record = dict(format="smartspace.replay.diagnostic", schema_version=1,
                          evidence="derived", sequence=self.sequence,
                          elapsed_ns=time.monotonic_ns() - self.origin, **data)
            self.sequence += 1
            if channel in self.streams:
                stream = self.streams[channel]
                stream.write(json.dumps(record, ensure_ascii=True, allow_nan=False) + "\n")
                stream.flush()

    def finish(self, summary):
        if self.directory:
            with (self.directory / "summary.json").open("x", encoding="utf-8") as stream:
                json.dump(summary, stream, indent=2, ensure_ascii=True, allow_nan=False)
                stream.write("\n")

    def close(self):
        for stream in self.streams.values():
            stream.close()


class ReplaySession:
    def __init__(self, capture, broker, *, capture_name, evidence=None, speed="1",
                 start_delay=3.0, manual_start=False, policy=None, acquisition="legacy", ws_hz=10, allow_unknown_retain=False):
        if not isinstance(broker, IsolatedBroker):
            raise ValueError("Solo se admite un broker propio de P0.3")
        broker.check()
        speed_ratio(speed)
        if not math.isfinite(start_delay) or start_delay < 0:
            raise ValueError("start_delay debe ser finito y no negativo")
        self.capture, self.broker, self.speed = capture, broker, str(speed)
        self.evidence = evidence if evidence is not None else Evidence()
        self.start_delay = start_delay
        self.start_requested, self.ready, self.stop = (threading.Event() for _ in range(3))
        if not manual_start:
            self.start_requested.set()
        from backend.app.mqtt_consumer import MQTTConsumer
        from backend.app.radar_normalizer import RadarNormalizer
        from backend.app.frame_acquisition import FrameAcquisition
        if not math.isfinite(ws_hz) or not 0 < ws_hz <= 100:
            raise ValueError("ws_hz must be in (0, 100]")
        self.ws_hz = ws_hz
        self.allow_unknown_retain = allow_unknown_retain
        self.consumer = MQTTConsumer(RadarNormalizer(policy) if acquisition == "legacy" else FrameAcquisition(ttl=policy.ttl if policy else 2.0), mode=acquisition)
        self.client = None
        self.summary = None
        self.state = dict(mode="replay", capture_name=Path(capture_name).name,
                          source_sha256=capture.sha256, speed=self.speed,
                          evidence_kind="synthetic" if capture.records[0]["metadata"].get(
                              "evidence_kind") == "synthetic" else "physical_capture",
                          phase="waiting", consumer_received=0, consumer_errors=0,
                          consumer_connected=False, states_generated=0,
                          states_with_targets=0, max_targets=0, observed_slots=[])

    def snapshot(self):
        with self.evidence.lock:
            return deepcopy({**self.state, "summary": self.summary, "acquisition_mode": self.consumer.mode,
                             "acquisition_counters": self.consumer.normalizer.counters, "ws_hz": self.ws_hz})

    def connect_consumer(self):
        consumer = self.consumer
        self.broker.check()
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id="smartspace-replay-consumer-" + uuid.uuid4().hex)
        self.client = client

        def connected(client, userdata, flags, reason, properties):
            consumer.on_connect(client, userdata, flags, reason, properties)
            with self.evidence.lock:
                self.state["consumer_connected"] = reason == 0
                self.evidence.write("transport", event="backend_connected", reason_code=reason.value)

        def subscribed(client, userdata, mid, reasons, properties):
            codes = [r.value for r in reasons]
            self.evidence.write("transport", event="backend_subscribed", granted_qos=codes)
            if codes and all(code in (0, 1, 2) for code in codes):
                self.ready.set()

        def disconnected(client, userdata, flags, reason, properties):
            consumer.on_disconnect(client, userdata, flags, reason, properties)
            with self.evidence.lock:
                self.state["consumer_connected"] = False
                self.evidence.write("transport", event="backend_disconnected", reason_code=reason.value)

        def received(client, userdata, message):
            with self.evidence.lock:
                self.state["consumer_received"] += 1
            error_type = None
            try:
                # Record invalid fields separately from unexpected callback failures.
                outcome = consumer.on_message(client, userdata, message)
                if outcome in ("invalid", "callback_error"):
                    error_type = outcome
                    with self.evidence.lock:
                        self.state["consumer_errors"] += 1
            except Exception as error:
                error_type = type(error).__name__
                with self.evidence.lock:
                    self.state["consumer_errors"] += 1
                raise
            finally:
                self.evidence.write("received", topic=message.topic,
                                    payload_base64=base64.b64encode(message.payload).decode("ascii"),
                                    qos=message.qos, retain=message.retain, error_type=error_type,
                                    normalization=consumer.build_frame()["observation"])

        client.on_connect, client.on_subscribe = connected, subscribed
        client.on_disconnect, client.on_message = disconnected, received
        client.username_pw_set(self.broker.username, self.broker.password)
        client.connect_timeout = 3
        client.connect(self.broker.host, self.broker.port, 60)
        return client

    def observe_state(self, raw, frame, state):
        with self.evidence.lock:
            self.state["states_generated"] += 1
            self.state["states_with_targets"] += bool(state["targets"])
            self.state["max_targets"] = max(self.state["max_targets"], len(state["targets"]))
            self.state["observed_slots"] = sorted(set(self.state["observed_slots"]) | {
                t["slot"] for t in state["targets"]})
            self.evidence.write("states", raw=raw, prepared=frame, state=state,
                                normalization=raw["observation"])

    def _publish(self):
        with MqttPublisher(self.broker) as publisher:
            return replay(self.capture, speed=self.speed, stop=self.stop,
                          allow_unknown_retain=self.allow_unknown_retain,
                          publish=publisher.publish, check=publisher.check,
                          emit=lambda event: self.evidence.write("replay", event=event))

    async def run(self, hub):
        from backend.app.radar_bridge import run_radar
        consumer_task = asyncio.create_task(run_radar(hub, replay_session=self))
        publication = None
        try:
            deadline = time.monotonic() + 8
            while not self.ready.is_set():
                if consumer_task.done():
                    consumer_task.result()
                    raise RuntimeError("Consumidor detenido antes de SUBACK")
                if time.monotonic() >= deadline:
                    raise RuntimeError("El consumidor no confirmó la suscripción aislada")
                await asyncio.sleep(0.05)
            while not self.start_requested.is_set():
                if consumer_task.done():
                    consumer_task.result()
                await asyncio.sleep(0.05)
            self.state["phase"] = "delay"
            await asyncio.sleep(self.start_delay)
            self.state["phase"] = "running"
            publication = asyncio.create_task(asyncio.to_thread(self._publish))
            # shield lets shutdown request stop and then join the publishing thread.
            self.summary = await asyncio.shield(publication)
            self.state["phase"] = self.summary["status"]
            # Keep the unchanged 1 Hz bridge alive to observe TTL after replay.
            await consumer_task
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.state.update(phase="error", error_type=type(error).__name__)
            self.evidence.write("transport", event="session_error", error_type=type(error).__name__)
            raise
        finally:
            self.stop.set()
            if publication is not None:
                with suppress(Exception):
                    self.summary = await asyncio.shield(publication)
            consumer_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await consumer_task


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--mosquitto", type=Path, required=True)
    parser.add_argument("--speed", default="1")
    parser.add_argument("--acquisition", choices=("legacy", "frames"), default="legacy")
    parser.add_argument("--ws-hz", type=float, default=10)
    parser.add_argument("--allow-unknown-retain", action="store_true")
    parser.add_argument("--field-ttl", type=float, default=2.)
    parser.add_argument("--xy-skew", type=float, default=.25)
    parser.add_argument("--http-port", type=int, default=8001)
    parser.add_argument("--start-delay", type=float, default=3)
    parser.add_argument("--manual-start", action="store_true")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--evidence-dir", type=Path, help="Optional diagnostic JSONL output")
    parser.add_argument("--exit-after-replay", type=float,
                        help="Cerrar tras N segundos adicionales al terminar; por defecto permanece abierto")
    args = parser.parse_args(argv)
    if not 1024 <= args.http_port <= 65535:
        parser.error("Puerto HTTP entre 1024 y 65535")
    for value in (args.start_delay, args.exit_after_replay):
        if value is not None and (not math.isfinite(value) or value < 0):
            parser.error("Las duraciones deben ser finitas y no negativas")
    try:
        from backend.app.radar_normalizer import Policy
        policy = Policy(args.field_ttl, args.xy_skew)
        speed_ratio(args.speed)
        capture = load_capture(args.input, allow_incomplete=args.allow_incomplete)
        evidence = Evidence(args.evidence_dir)
        session = None
        try:
            with IsolatedBroker(args.mosquitto) as broker:
                session = ReplaySession(capture, broker, capture_name=args.input.name,
                                        evidence=evidence, speed=args.speed,
                                        start_delay=args.start_delay, manual_start=args.manual_start, policy=policy, acquisition=args.acquisition,
                                        ws_hz=args.ws_hz, allow_unknown_retain=args.allow_unknown_retain)
                from backend.app.main import create_app
                server = uvicorn.Server(uvicorn.Config(create_app(replay_session=session),
                    host="127.0.0.1", port=args.http_port, workers=1, log_level="info"))

                async def serve():
                    async def auto_exit():
                        while session.summary is None and session.state["phase"] != "error":
                            await asyncio.sleep(0.1)
                        await asyncio.sleep(args.exit_after_replay)
                        server.should_exit = True
                    watcher = asyncio.create_task(auto_exit()) if args.exit_after_replay is not None else None
                    try:
                        await server.serve()
                    finally:
                        if watcher is not None:
                            watcher.cancel()
                            with suppress(asyncio.CancelledError):
                                await watcher
                asyncio.run(serve())
        finally:
            if session is not None:
                evidence.finish(session.snapshot())
                print(json.dumps(session.snapshot(), sort_keys=True))
            evidence.close()
        return 1 if (session.state["phase"] == "error" or session.state["consumer_errors"]
                     or (session.summary and session.summary["errors"])) else 0
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps(dict(mode="replay", phase="error", error_type=type(error).__name__)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
