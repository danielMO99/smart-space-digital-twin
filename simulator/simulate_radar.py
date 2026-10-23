"""Standalone, deterministic radar simulator; emits one JSON object per line."""

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time

DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "room.json"


def load_config(path=DEFAULT_CONFIG):
    with open(path, encoding="utf-8") as stream:
        config = json.load(stream)
    try:
        room, radar, simulation = config["room"], config["radar"], config["simulation"]
        for value in (room["width_m"], room["length_m"],
                      radar["position"]["x_m"], radar["position"]["y_m"],
                      radar["rotation_deg"], simulation["update_interval_ms"]):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Geometry and interval must be finite numbers")
        if min(room["width_m"], room["length_m"], simulation["update_interval_ms"]) <= 0:
            raise ValueError("Room dimensions and interval must be positive")
        if not (0 <= radar["position"]["x_m"] <= room["width_m"] and
                0 <= radar["position"]["y_m"] <= room["length_m"]):
            raise ValueError("Radar must be inside the room")
        count = simulation["max_targets"]
        if type(count) is not int or not 0 <= count <= 3:
            raise ValueError("max_targets must be an integer from 0 to 3")
        if type(simulation["enabled"]) is not bool:
            raise ValueError("simulation.enabled must be a boolean")
        if not isinstance(radar["id"], str) or not radar["id"].strip():
            raise ValueError("radar.id must be a nonempty string")
    except (KeyError, TypeError) as error:
        raise ValueError("Invalid room/radar/simulation configuration") from error
    return config


def trajectory(room, slot, elapsed):
    """Return world position and analytic velocity in metres and metres/second."""
    phase = (slot - 1) * 2 * math.pi / 3
    wx, wy = 0.23 + slot * 0.025, 0.17 + slot * 0.02
    ax, ay = room["width_m"] * 0.4, room["length_m"] * 0.4
    px, py = wx * elapsed + phase, wy * elapsed + phase
    return (room["width_m"] / 2 + ax * math.sin(px),
            room["length_m"] / 2 + ay * math.sin(py),
            ax * wx * math.cos(px), ay * wy * math.cos(py))


def local_measurement(radar, x, y, vx, vy):
    """Inverse rigid transform; positive radial speed means moving away."""
    dx, dy = x - radar["position"]["x_m"], y - radar["position"]["y_m"]
    angle = math.radians(radar["rotation_deg"])
    c, s = math.cos(angle), math.sin(angle)
    distance = math.hypot(dx, dy)
    speed = (dx * vx + dy * vy) / distance if distance > 1e-12 else 0.0
    return {"x_mm": round((c * dx + s * dy) * 1000),
            "y_mm": round((-s * dx + c * dy) * 1000),
            "speed_cm_s": round(speed * 100, 3)}


def make_frame(config, elapsed, targets=None, timestamp=None):
    count = config["simulation"]["max_targets"] if targets is None else targets
    if type(count) is not int or not 0 <= count <= config["simulation"]["max_targets"]:
        raise ValueError("Requested targets exceed the configured limit")
    stamp = timestamp if timestamp is not None else datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware")
    return {"schema_version": 1, "source": "simulator", "radar_id": config["radar"]["id"],
            "timestamp": stamp.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "targets": [{"slot": slot, **local_measurement(config["radar"],
                        *trajectory(config["room"], slot, elapsed))}
                        for slot in range(1, count + 1)]}


def run(config, targets=None, frames=None, clock=time.monotonic, sleep=time.sleep, emit=print):
    interval = config["simulation"]["update_interval_ms"] / 1000
    start = deadline = clock()
    emitted = 0
    while frames is None or emitted < frames:
        sleep(max(0, deadline - clock()))
        now = clock()
        emit(json.dumps(make_frame(config, now - start, targets), allow_nan=False), flush=True)
        emitted += 1
        deadline += interval
        # Skip missed deadlines instead of emitting a burst after a slow consumer.
        after = clock()
        if deadline < after:
            deadline += (math.floor((after - deadline) / interval) + 1) * interval


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--targets", type=int, choices=range(4), default=None)
    parser.add_argument("--frames", type=int, help="Stop after this many frames")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if not config["simulation"]["enabled"]:
            raise ValueError("Simulation is disabled in configuration")
        if args.frames is not None and args.frames <= 0:
            raise ValueError("--frames must be positive")
        make_frame(config, 0, args.targets)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    try:
        run(config, args.targets, args.frames)
    except (KeyboardInterrupt, BrokenPipeError):
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
