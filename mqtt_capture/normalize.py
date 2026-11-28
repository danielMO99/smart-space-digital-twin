"""Offline deterministic P1.1b state reference; no sockets or file writes."""
import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from types import SimpleNamespace

from backend.app.radar_normalizer import RadarNormalizer, Policy
from backend.app.radar_bridge import prepare_frame
from backend.app.main import process_frame
from simulator.simulate_radar import load_config
from .replay import load_capture


def states(capture, policy=None):
    clock = SimpleNamespace(ns=0)
    first = capture.records[0]
    origin = datetime.fromisoformat(first['timestamp_utc'].replace('Z', '+00:00')) - timedelta(microseconds=first['monotonic_ns']/1000)
    normalizer = RadarNormalizer(policy, clock=lambda: clock.ns/1e9,
        utc_now=lambda: origin+timedelta(microseconds=clock.ns/1000))
    config = load_config()
    records = iter(capture.records)
    record = next(records, None)
    for tick in range(1, math.ceil(capture.records[-1]['monotonic_ns']/1e9)+4):
        deadline = tick*1_000_000_000
        while record is not None and record['monotonic_ns'] <= deadline:
            clock.ns = record['monotonic_ns']
            if record['record_type'] == 'message' and not record['retain']:
                normalizer.ingest(record['topic'], capture.payloads[record['sequence']])
            record = next(records, None)
        clock.ns = deadline
        yield process_frame(prepare_frame(normalizer.snapshot(), config['radar']['id']), config)


def summarize(result):
    encoded = json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    return dict(states=len(result), with_targets=sum(bool(s['targets']) for s in result),
        empty=sum(not s['targets'] for s in result),
        temporal_mismatch=sum('temporal_mismatch' in s['observation']['rejected_slots'].values() for s in result),
        expired=sum('expired' in s['observation']['rejected_slots'].values() for s in result),
        unknown_speed=sum(t['speed_m_s'] is None for s in result for t in s['targets']),
        counters=result[-1]['observation']['counters'], sha256=hashlib.sha256(encoded).hexdigest())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',required=True)
    parser.add_argument('--field-ttl',type=float,default=2.)
    parser.add_argument('--xy-skew',type=float,default=.25)
    parser.add_argument('--allow-incomplete',action='store_true')
    args=parser.parse_args()
    capture=load_capture(args.input,allow_incomplete=args.allow_incomplete)
    policy=Policy(args.field_ttl,args.xy_skew)
    one=list(states(capture,policy));two=list(states(capture,policy))
    assert one==two
    print(json.dumps(dict(source_sha256=capture.sha256,deterministic=True,**summarize(one)),indent=2))


if __name__=='__main__': main()
