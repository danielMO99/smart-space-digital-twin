"""Atomic decoded reports; source slots are not persistent person identities."""
from copy import deepcopy
from datetime import datetime, timezone
import math
import threading
import time
from mqtt_capture.frames import FRAME_TOPIC, FrameError, validate


class FrameAcquisition:
    def __init__(self, ttl=2.0, *, clock_ns=time.monotonic_ns,
                 utc_now=lambda: datetime.now(timezone.utc)):
        if not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("TTL must be positive and finite")
        self.ttl = ttl
        self.clock_ns, self.utc_now = clock_ns, utc_now
        self.lock = threading.RLock()
        self.connected = True
        self.report = None
        self.retired_boots = set()
        self.received_ns = None
        self.received_utc = None
        self.awaiting_fresh = True
        self.counters = dict(received=0, accepted=0, invalid=0, retained=0, unexpected=0,
                             duplicate=0, conflicting_duplicate=0, out_of_order=0,
                             clock_regression=0, retired_boot=0, boot_changes=0,
                             sequence_gaps=0, missing_sequences=0)

    def transport(self, connected):
        with self.lock:
            self.connected = connected
            if not connected:
                self.awaiting_fresh = True

    def ingest(self, topic, payload, retain=False):
        with self.lock:
            self.counters["received"] += 1
            if topic != FRAME_TOPIC:
                return self.reject("unexpected")
            if retain:
                return self.reject("retained")
            try:
                report = validate(payload)
            except FrameError:
                return self.reject("invalid")
            previous = self.report
            if previous is not None:
                if report["boot_id"] == previous["boot_id"]:
                    if report["seq"] == previous["seq"]:
                        return self.reject("duplicate" if report == previous else "conflicting_duplicate")
                    if report["seq"] < previous["seq"]:
                        return self.reject("out_of_order")
                    if report["rx_us"] < previous["rx_us"]:
                        return self.reject("clock_regression")
                    gap = report["seq"] - previous["seq"] - 1
                    if gap:
                        self.counters["sequence_gaps"] += 1
                        self.counters["missing_sequences"] += gap
                else:
                    if report["boot_id"] in self.retired_boots:
                        return self.reject("retired_boot")
                    self.retired_boots.add(previous["boot_id"])
                    self.counters["boot_changes"] += 1
            self.report = report
            self.received_ns = self.clock_ns()
            self.received_utc = self.utc_now().isoformat()
            self.awaiting_fresh = False
            self.counters["accepted"] += 1
            return "accepted"

    def reject(self, reason):
        self.counters[reason] += 1
        return reason

    def snapshot(self):
        with self.lock:
            now = self.clock_ns()
            if not self.connected:
                status = "disconnected"
            elif self.report is None or self.awaiting_fresh:
                status = "waiting"
            elif now - self.received_ns > self.ttl * 1e9:
                status = "stale"
            else:
                status = "fresh"
            targets = []
            if status == "fresh":
                targets = [dict(slot=s["slot"], x_mm=s["x_mm"], y_mm=s["y_mm"],
                                speed_mm_s=s["speed_mm_s"], resolution_mm=s["resolution_mm"])
                           for s in self.report["slots"] if s["x_mm"] is not None]
            return dict(source="ld2450", radar_id="radar_01",
                timestamp=self.received_utc or self.utc_now().isoformat(), targets=targets,
                acquisition=dict(mode="frames", telemetry_status=status,
                    backend_received_ns=self.received_ns, backend_received_utc=self.received_utc,
                    report=deepcopy(self.report)),
                observation=dict(reported_count=None, observed_slots=len(targets), count_inconsistent=False,
                    occupancy="unknown", association="decoded_report", connected=self.connected,
                    ttl_seconds=self.ttl, xy_skew_seconds=0, rejected_slots={}, counters=dict(self.counters)))
