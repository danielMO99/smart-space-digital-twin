"""Analyze complete reports in captured/imported files without a broker."""
import argparse
import json
from .frames import FRAME_TOPIC, FrameError, validate
from .replay import load_capture


def analyze(capture):
    reports = []
    for row in capture.records:
        if row["record_type"] != "message" or row["topic"] != FRAME_TOPIC or row["retain"] is True:
            continue
        try:
            reports.append(validate(capture.payloads[row["sequence"]]))
        except FrameError:
            pass
    groups = {}
    for r in reports:
        groups.setdefault(r["boot_id"], []).append(r)
    sessions = []
    for boot, group in groups.items():
        span = (group[-1]["rx_us"] - group[0]["rx_us"]) / 1e6
        runs = {}
        start = previous = None
        for r in group:
            count = len(r["targets"])
            if (previous is None or len(previous["targets"]) != count
                    or r["seq"] != previous["seq"]+1 or r["rx_us"] < previous["rx_us"]
                    or r["rx_us"]-previous["rx_us"] > 500_000):
                start = r["rx_us"]
            runs[str(count)] = max(runs.get(str(count), 0), (r["rx_us"]-start)/1e6)
            previous = r
        sessions.append(dict(boot_id=boot, reports=len(group), first_seq=group[0]["seq"],
            last_seq=group[-1]["seq"], esp_first_to_last_seconds=span,
            interval_rate_hz=(len(group)-1)/span if span > 0 else None,
            longest_same_count_first_to_last_seconds=runs,
            diagnostics_ranges={k: [min(r["diagnostics"][k] for r in group),
                                    max(r["diagnostics"][k] for r in group)] for k in group[0]["diagnostics"]}))
    return dict(source_sha256=capture.sha256, timing_basis=capture.time_basis,
                validation=capture.frame_analysis, sessions=sessions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    result = analyze(load_capture(args.input, allow_incomplete=args.allow_incomplete))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
