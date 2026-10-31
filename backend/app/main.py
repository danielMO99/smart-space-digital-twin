"""Phase 2.2: one simulator producer, HTTP snapshots and live subscribers."""

import asyncio
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
import math
from pathlib import Path

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
    speed_cm_s: float = Field(strict=True)


class Frame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: StrictInt = Field(ge=1, le=1)
    source: Literal["simulator"]
    radar_id: str
    timestamp: AwareDatetime
    targets: list[Target] = Field(max_length=3)

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
                        "y_m": round(gy, 6), "speed_m_s": target.speed_cm_s / 100,
                        "inside_room": (-1e-9 <= gx <= room["width_m"] + 1e-9 and
                                        -1e-9 <= gy <= room["length_m"] + 1e-9)})
    result = frame.model_dump(mode="json")
    result["targets"] = targets
    return result


class StateHub:
    def __init__(self, config):
        self.config = config
        self.latest = None
        self.subscribers = set()
        self.paused = False
        # Número actual de objetivos simulados
        self.target_count = config["simulation"]["max_targets"]
        # Factor de velocidad
        self.speed_factor = 1.0

    def publish(self, raw):
        # Validate before replacing the last known good state.
        state = process_frame(raw, self.config)
        self.latest = state
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


def create_app(config_path=None):
    @asynccontextmanager
    async def lifespan(app):
        config = load_config() if config_path is None else load_config(config_path)
        hub = StateHub(config)
        app.state.hub = hub
        task = None
        if config["simulation"]["enabled"]:
            hub.publish(make_frame(config, 0))
            task = asyncio.create_task(simulate(hub))
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
        return JSONResponse(status_code=503 if failed else 200, content={
            "status": "error" if failed else "ok",
            "simulation_enabled": app.state.hub.config["simulation"]["enabled"]})

    @app.get("/api/room")
    async def room():
        return deepcopy(app.state.hub.config)

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

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, OSError):
            pass
        finally:
            hub.subscribers.discard(queue)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    return app


app = create_app()
