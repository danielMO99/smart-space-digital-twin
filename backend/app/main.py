"""Phase 2.2: one simulator producer, HTTP snapshots and live subscribers."""

import asyncio
import anyio
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
import math
import json
import threading
from pathlib import Path
import os
from backend.app.radar_bridge import run_radar

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictInt, field_validator
from typing import Literal

from simulator.simulate_radar import load_config, make_frame


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    slot: StrictInt = Field(ge=1, le=3)
    x_mm: StrictInt
    y_mm: StrictInt
    speed_cm_s: float | None = Field(strict=True)
    resolution_mm: StrictInt | None = Field(default=None, ge=0)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    reported_count: StrictInt | None = Field(ge=0, le=3)
    observed_slots: StrictInt = Field(ge=0, le=3)
    count_inconsistent: bool = Field(strict=True)
    occupancy: Literal["unknown"]
    association: Literal["temporal_not_synchronized", "decoded_report"]
    connected: bool = Field(strict=True)
    ttl_seconds: float = Field(gt=0)
    xy_skew_seconds: float = Field(ge=0)
    rejected_slots: dict[str, Literal["disconnected", "partial_or_invalid", "expired", "temporal_mismatch"]]
    counters: dict[str, StrictInt]


class Acquisition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["frames"]
    telemetry_status: Literal["fresh", "stale", "waiting", "disconnected"]
    backend_received_ns: StrictInt | None = Field(ge=0)
    backend_received_utc: AwareDatetime | None
    report: dict | None

    @field_validator("report")
    @classmethod
    def valid_report(cls, value):
        if value is not None:
            from mqtt_capture.frames import validate
            validate(json.dumps(value, allow_nan=False).encode())
        return value


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: StrictInt = Field(ge=1, le=1)
    source: Literal["simulator", "ld2450"]
    radar_id: str
    timestamp: AwareDatetime
    targets: list[Target] = Field(max_length=3)

    observation: Observation | None = None
    acquisition: Acquisition | None = None

    @field_validator("targets")
    @classmethod
    def unique_slots(cls, targets):
        if len({target.slot for target in targets}) != len(targets):
            raise ValueError("Duplicate target slots")
        return targets

class TargetCountRequest(BaseModel):
    count: StrictInt = Field(ge=0, le=3)

class SpeedFactorRequest(BaseModel):
    speed_factor: float = Field(gt=0, le=3)

def process_frame(raw, config):
    """Validate local measurements and rotate counterclockwise, then translate."""
    frame = Frame.model_validate(raw)
    if frame.observation is not None:
        observation = frame.observation
        if observation.observed_slots != len(frame.targets):
            raise ValueError("Observed slot count does not match targets")
        if observation.count_inconsistent != (observation.reported_count is not None
                and observation.reported_count != len(frame.targets)):
            raise ValueError("Invalid count consistency flag")
    if frame.acquisition is not None:
        a = frame.acquisition
        expected = [] if a.report is None or a.telemetry_status != "fresh" else [
            dict(slot=s["slot"], x_mm=s["x_mm"], y_mm=s["y_mm"],
                 speed_cm_s=s["speed_mm_s"] / 10, resolution_mm=s["resolution_mm"])
            for s in a.report["slots"] if s["x_mm"] is not None]
        actual = [dict(slot=t.slot, x_mm=t.x_mm, y_mm=t.y_mm,
                       speed_cm_s=t.speed_cm_s,
                       resolution_mm=t.resolution_mm) for t in frame.targets]
        if actual != expected:
            raise ValueError("Targets do not match the atomic report")
    radar, room = config["radar"], config["room"]
    if frame.radar_id != radar["id"]:
        raise ValueError("Unknown radar_id")
    if len(frame.targets) > config["simulation"]["max_targets"]:
        raise ValueError("Too many targets for configuration")
    angle = math.radians(radar["rotation_deg"])
    c, s = math.cos(angle), math.sin(angle)
    targets = []
    for target in frame.targets:
        x, y = target.x_mm / 1000, target.y_mm / 1000
        gx = radar["position"]["x_m"] + c * x - s * y
        gy = radar["position"]["y_m"] + s * x + c * y
        if not math.isfinite(gx) or not math.isfinite(gy):
            raise ValueError("Non-finite transformed position")
        targets.append({"slot": target.slot, "x_m": round(gx, 6),
                        "y_m": round(gy, 6), "speed_m_s": None if target.speed_cm_s is None else target.speed_cm_s / 100,
                        "inside_room": (-1e-9 <= gx <= room["width_m"] + 1e-9 and
                                        -1e-9 <= gy <= room["length_m"] + 1e-9)})
        if target.resolution_mm is not None:
            targets[-1]["resolution_mm"] = target.resolution_mm
    result = frame.model_dump(mode="json")
    if frame.acquisition is None:
        result.pop("acquisition")
    if frame.observation is None:
        result.pop("observation")
    result["targets"] = targets
    return result


class StateHub:
    def __init__(self, config):
        self.config = config
        self.latest = None
        self.lock = threading.RLock()
        self.publications = 0
        self.diagnostics = None
        self.subscribers = set()
        self.paused = False
        # Número actual de objetivos simulados
        self.target_count = config["simulation"]["max_targets"]
        # Factor de velocidad
        self.speed_factor = 1.0

    def publish(self, raw, *, notify=True):
        # Frames callbacks use notify=False; asyncio queues are touched only by the event loop.
        state = process_frame(raw, self.config)
        with self.lock:
            self.latest = state
            self.publications += 1
        if notify:
            self.broadcast()

    def broadcast(self):
        with self.lock:
            state = self.latest
        if state is None:
            return
        if self.diagnostics is not None:
            self.diagnostics.distributed()
        for queue in self.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(state)


async def simulate(hub):
    loop = asyncio.get_running_loop()

    interval = (
        hub.config["simulation"]["update_interval_ms"] / 1000
    )

    deadline = loop.time()
    elapsed = 0.0

    while True:
        deadline += interval

        await asyncio.sleep(
            max(0, deadline - loop.time())
        )

        if not hub.paused:
            elapsed += interval * hub.speed_factor

        hub.publish(
            make_frame(
                hub.config,
                elapsed,
                targets=hub.target_count
            )
        )

        now = loop.time()

        if deadline < now:
            deadline += (
                math.floor((now - deadline) / interval)
                * interval
            )


def create_app(config_path=None, *, replay_session=None):
    @asynccontextmanager
    async def lifespan(app):
        config = load_config() if config_path is None else load_config(config_path)
        hub = StateHub(config)
        app.state.hub = hub
        task = None

        mode = "replay" if replay_session is not None else os.getenv("SMARTSPACE_SOURCE", "simulator").lower()
        app.state.source_mode = mode

        if mode == "simulator":
            if config["simulation"]["enabled"]:
                hub.publish(make_frame(config, 0))
                task = asyncio.create_task(simulate(hub))

        elif mode == "ld2450":
            task = asyncio.create_task(run_radar(hub))

        elif mode == "replay":
            if replay_session is None:
                raise ValueError("Replay requiere el lanzador aislado: python -m mqtt_capture.replay_app")
            task = asyncio.create_task(replay_session.run(hub))

        else:
            raise ValueError(
                f"Modo desconocido: {mode}. "
                "Usa 'simulator' o 'ld2450'."
            )
        app.state.producer = task
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="Smart Space Digital Twin", lifespan=lifespan)
    frontend = Path(__file__).resolve().parents[2] / "frontend"
    app.mount("/static", StaticFiles(directory=frontend), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(frontend / "index.html")

    @app.get("/health")
    async def health():
        task = app.state.producer
        failed = task is not None and task.done()
        consumer = getattr(app.state.hub, "consumer", None)
        client = getattr(app.state.hub, "mqtt_client", None)
        if consumer is not None:
            thread = getattr(client, "_thread", None)
            failed = failed or consumer.callback_errors > 0 or not consumer.normalizer.connected or thread is None or not thread.is_alive()
        return JSONResponse(status_code=503 if failed else 200, content={
            "status": "error" if failed else "ok",
            "simulation_enabled": app.state.hub.config["simulation"]["enabled"]})

    @app.get("/api/diagnostics")
    async def diagnostics():
        hub = app.state.hub
        consumer = getattr(hub, "consumer", None)
        client = getattr(hub, "mqtt_client", None)
        task = app.state.producer
        thread = getattr(client, "_thread", None)
        service = dict(producer_failed=task is not None and task.done(),
                       mqtt_thread_alive=None if consumer is None else thread is not None and thread.is_alive(),
                       callback_errors=0 if consumer is None else consumer.callback_errors,
                       health_http_status=(await health()).status_code)
        service['status'] = 'error' if (service['producer_failed'] or service['callback_errors']
            or service['mqtt_thread_alive'] is False) else 'ok'
        if hub.diagnostics is None:
            acquisition = dict(schema_version=1, mode='simulator' if app.state.source_mode == 'simulator' else 'pending',
                source='simulation' if app.state.source_mode == 'simulator' else 'replay' if replay_session else 'live',
                overall='unavailable', reasons=['no_mqtt_diagnostic_engine'], mqtt=None, freshness=None,
                integrity=None, frequency=None, esp32=None, session=None, history=[], current_targets=None)
        else:
            acquisition = hub.diagnostics.snapshot()
        return dict(schema_version=1, service=service, acquisition=acquisition)

    @app.get("/api/room")
    async def room():
        return deepcopy(app.state.hub.config)

    @app.get("/api/runtime")
    async def runtime():
        if replay_session is not None:
            return replay_session.snapshot()
        return {"mode": app.state.source_mode}

    @app.post("/api/replay/start")
    async def start_replay():
        if replay_session is None:
            return JSONResponse(status_code=409, content={"detail": "No es una sesión de replay"})
        replay_session.start_requested.set()
        return replay_session.snapshot()

    @app.get("/api/state")
    async def state():
        return app.state.hub.latest

    @app.get("/api/simulation/status")
    async def simulation_status():
        paused = app.state.hub.paused
        return {"status": "paused" if paused else "running", "paused": paused}

    @app.get("/api/simulation")
    async def get_simulation_status():
        hub = app.state.hub

        return {
            "paused": hub.paused,
            "status": "paused" if hub.paused else "running",
            "simulation_enabled": hub.config["simulation"]["enabled"],
            "target_count": hub.target_count,
            "speed_factor": hub.speed_factor,
        }

    @app.post("/api/simulation/pause")
    async def pause_simulation():
        hub = app.state.hub
        hub.paused = True

        return {
            "status": "paused",
            "paused": hub.paused
        }

    @app.post("/api/simulation/resume")
    async def resume_simulation():
        hub = app.state.hub
        hub.paused = False

        return {
            "status": "running",
            "paused": hub.paused
        }

    @app.post("/api/simulation/targets")
    async def set_target_count(request: TargetCountRequest):
        hub = app.state.hub

        if request.count > hub.config["simulation"]["max_targets"]:
            return JSONResponse(
                status_code=422,
                content={"detail": "Número superior al máximo configurado"}
            )

        hub.target_count = request.count

        return {
            "status": "updated",
            "target_count": hub.target_count
        }

    @app.post("/api/simulation/speed")
    async def set_simulation_speed(request: SpeedFactorRequest):
        hub = app.state.hub

        hub.speed_factor = request.speed_factor

        return {
            "status": "updated",
            "speed_factor": hub.speed_factor
        }
    
    @app.websocket("/ws")
    async def live(websocket: WebSocket):
        await websocket.accept()
        hub = app.state.hub
        queue = asyncio.Queue(maxsize=1)
        hub.subscribers.add(queue)
        if hub.latest is not None:
            queue.put_nowait(hub.latest)

        async def send():
            while True:
                await websocket.send_json(await queue.get())

        async def receive():
            # This endpoint distributes state; acquisition uses hub.publish.
            while True:
                await websocket.receive_text()

        try:
            async with anyio.create_task_group() as group:
                async def supervise(operation):
                    try:
                        await operation()
                    except (WebSocketDisconnect, OSError):
                        pass
                    finally:
                        group.cancel_scope.cancel()
                group.start_soon(supervise, send)
                await supervise(receive)
        finally:
            hub.subscribers.discard(queue)

    return app


app = create_app()
