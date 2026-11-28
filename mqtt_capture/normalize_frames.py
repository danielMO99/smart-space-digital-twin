"""Deterministic backend validation; virtual receipt times are test times, not physical evidence."""
import argparse
import base64
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from backend.app.frame_acquisition import FrameAcquisition
from backend.app.main import StateHub
from backend.app.radar_bridge import prepare_frame
from simulator.simulate_radar import load_config
from .replay import load_capture, replay, VirtualClock


def states(capture):
    clock = VirtualClock()
    acquisition = FrameAcquisition(clock_ns=clock.now_ns,
        utc_now=lambda: datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=clock.ns // 1000))
    hub = StateHub(load_config())
    result = []
    def emit(event):
        if event['record_type'] == 'message' and event['action'] == 'publish':
            outcome = acquisition.ingest(event['topic'], base64.b64decode(event['payload_base64']))
            if outcome == 'accepted':
                hub.publish(prepare_frame(acquisition.snapshot(), hub.config['radar']['id']), notify=False)
                result.append(hub.latest)
    replay(capture, clock=clock, emit=emit, allow_unknown_retain=True, include_invalid_frames=True)
    return result, dict(acquisition.counters)


def summarize(capture):
    first, counters = states(capture)
    second, repeated = states(capture)
    encoded = json.dumps(first, sort_keys=True, separators=(',', ':')).encode()
    return dict(source_sha256=capture.sha256, states=len(first), counters=counters,
        targets_distribution=dict(Counter(len(s['targets']) for s in first)),
        deterministic=first == second and counters == repeated,
        states_sha256=hashlib.sha256(encoded).hexdigest(),
        time_basis='virtual backend receipt, epoch 2000; source ESP rx_us preserved separately')


def benchmark(capture):
    """Controlled in-memory legacy projection; NOT captured legacy sensor timing."""
    import statistics
    import time
    from backend.app.radar_normalizer import RadarNormalizer
    from .frames import FRAME_TOPIC, validate
    reports = [validate(capture.payloads[r['sequence']]) for r in capture.records
               if r['record_type'] == 'message' and r['topic'] == FRAME_TOPIC]
    result = {}
    for mode in ('frames', 'legacy'):
        now = [0.0]
        acquisition = (FrameAcquisition(clock_ns=lambda: int(now[0]*1e9)) if mode == 'frames'
                       else RadarNormalizer(clock=lambda: now[0]))
        hub = StateHub(load_config())
        durations, messages = [], 0
        for report in reports:
            now[0] = report['rx_us'] / 1e6
            if mode == 'frames':
                batch = [(FRAME_TOPIC, json.dumps(report).encode())]
            else:
                batch = [('smartspace/esp32/sensor/n__mero_de_objetivos/state', str(len(report['targets'])).encode())]
                for slot in report['slots']:
                    for field, suffix in [('x_mm','x'), ('y_mm','y'), ('speed_mm_s','velocidad')]:
                        value = slot[field]
                        batch.append((f"smartspace/esp32/sensor/objetivo_{slot['slot']}_{suffix}/state",
                                      str(value if value is not None else 'nan').encode()))
            start = time.perf_counter_ns()
            for topic, payload in batch:
                acquisition.ingest(topic, payload)
            hub.publish(prepare_frame(acquisition.snapshot(), hub.config['radar']['id']), notify=False)
            durations.append((time.perf_counter_ns() - start)/1e6)
            messages += len(batch)
        durations.sort()
        result[mode] = dict(reports=len(reports), messages=messages, mean_ms=statistics.mean(durations),
                            p95_ms=durations[int(.95*len(durations))], p99_ms=durations[int(.99*len(durations))],
                            max_ms=max(durations))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--benchmark', action='store_true')
    args = parser.parse_args(argv)
    result = summarize(load_capture(args.input))
    if args.benchmark:
        result['controlled_projection_benchmark'] = benchmark(load_capture(args.input))
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result['deterministic'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
