"""Strict frame-v1 validation and source continuity, independent of FastAPI."""
import json
import uuid
from collections import Counter

FRAME_TOPIC = "smartspace/esp32/radar/frame/v1"
FIELDS = ("x_mm", "y_mm", "speed_mm_s", "resolution_mm")
DIAGNOSTICS = ("invalid_reports", "offline_reports", "decimated_reports",
               "enqueue_failures", "previous_callback_max_us")


class FrameError(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise FrameError(code)


def integer(value, low=0, high=2**64-1):
    return type(value) is int and low <= value <= high


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def constant(_):
    raise FrameError("nonfinite_json")


def validate(payload):
    """Return parsed data without changing any original bytes; safe error codes only."""
    try:
        r = json.loads(payload.decode("utf-8"), object_pairs_hook=unique, parse_constant=constant)
        require(type(r) is dict, "report_object")
        require(set(r) == {"schema", "version", "device", "boot_id", "seq", "rx_us",
                          "time_reference", "selected_seq", "min_interval_us", "targets",
                          "slots", "diagnostics"}, "report_fields")
        require(r["schema"] == "smartspace.ld2450.frame" and type(r["version"]) is int
                and r["version"] == 1, "report_version")
        require(r["device"] == "smartspace-esp32", "device")
        require(type(r["boot_id"]) is str and str(uuid.UUID(r["boot_id"])) == r["boot_id"], "boot_id")
        require(integer(r["seq"], 1) and integer(r["selected_seq"], 1, r["seq"]), "sequence")
        require(integer(r["rx_us"], 0, 2**63-1) and integer(r["min_interval_us"]), "clock")
        require(r["time_reference"] == "esp_processing_monotonic", "time_reference")
        require(type(r["slots"]) is list and len(r["slots"]) == 3, "slots")
        present = []
        for index, slot in enumerate(r["slots"], 1):
            require(type(slot) is dict and set(slot) == {"slot", *FIELDS}, "slot_fields")
            require(type(slot["slot"]) is int and slot["slot"] == index, "slot_order")
            values = [slot[key] for key in FIELDS]
            if all(v is None for v in values):
                continue
            require(all(v is not None for v in values), "partial_slot")
            require(integer(values[0], -32767, 32767) and integer(values[1], -32767, 32767)
                    and integer(values[2], -32768, 32767) and integer(values[3], 0, 32767), "slot_value")
            require(values[0] != 0 or values[1] != 0, "slot_origin")
            present.append(index)
        require(type(r["targets"]) is list and all(type(v) is int for v in r["targets"])
                and r["targets"] == present, "target_references")
        d = r["diagnostics"]
        require(type(d) is dict and set(d) == set(DIAGNOSTICS)
                and all(integer(v) for v in d.values()), "diagnostics")
        return r
    except FrameError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError, OverflowError, RecursionError):
        raise FrameError("invalid_json_or_fields") from None


class Analyzer:
    """Source sequence gaps are not automatically MQTT losses or physical absence."""
    def __init__(self, silence_us=500_000):
        self.silence_us = silence_us
        self.previous = None
        self.seen = {}
        self.boots = set()
        self.counts = Counter()
        self.issues = Counter()
        self.invalid = self.valid = 0

    def feed(self, payload, *, retain=False):
        try:
            r = validate(payload)
        except FrameError as error:
            self.invalid += 1
            return {"valid": False, "error": str(error), "issues": ["invalid_report"]}
        self.valid += 1
        self.counts[len(r["targets"])] += 1
        issues = []
        if retain is True:
            issues.append("retained_not_current")
        else:
            key = (r["device"], r["boot_id"], r["seq"])
            if key in self.seen:
                issues.append("duplicate" if self.seen[key] == r else "conflicting_duplicate")
            else:
                p = self.previous
                if p is not None:
                    if r["boot_id"] != p["boot_id"]:
                        issues.append("boot_return" if r["boot_id"] in self.boots else "boot_change")
                    else:
                        delta = r["seq"] - p["seq"]
                        if delta > 1: issues.append("sequence_gap")
                        if delta < 1: issues.append("sequence_regression")
                        elapsed = r["rx_us"] - p["rx_us"]
                        if elapsed < 0: issues.append("clock_regression")
                        if elapsed == 0: issues.append("clock_equal")
                        if elapsed > self.silence_us: issues.append("telemetry_gap")
                        if r["selected_seq"] <= p["selected_seq"]: issues.append("selected_sequence_regression")
                        if any(r["diagnostics"][k] < p["diagnostics"][k] for k in DIAGNOSTICS):
                            issues.append("diagnostics_regression")
                self.seen[key] = r
                self.previous = r
                self.boots.add(r["boot_id"])
        self.issues.update(issues)
        return {"valid": True, "issues": issues}

    def summary(self):
        return dict(valid=self.valid, invalid=self.invalid, sessions=len(self.boots),
                    target_counts={str(k): v for k, v in sorted(self.counts.items())},
                    issues=dict(sorted(self.issues.items())), silence_threshold_us=self.silence_us)
