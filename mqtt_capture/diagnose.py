"""Offline frame-mode P1.2a diagnostics: virtual backend time, never historical device health."""
import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
from backend.app.frame_acquisition import FrameAcquisition
from backend.app.acquisition_diagnostics import AcquisitionDiagnostics
from .replay import load_capture, replay, VirtualClock


def diagnose(capture):
    clock=VirtualClock()
    a=FrameAcquisition(clock_ns=clock.now_ns)
    d=AcquisitionDiagnostics(a,source='replay',clock=lambda:clock.ns/1e9,
                             time_basis='virtual_backend_monotonic')
    d.ws_configured_hz=10
    digest=hashlib.sha256();counts=Counter();tick=0; last=None
    def sample():
        nonlocal last
        last=d.snapshot();counts[last['overall']]+=1
        digest.update(json.dumps(last,sort_keys=True,separators=(',',':')).encode())
    def event(e):
        nonlocal tick
        target=e['scheduled_ns']
        # Half-open bins: tick precedes messages at the identical timestamp.
        while tick<=target:
            clock.ns=tick;d.distributed();sample();tick+=100_000_000
        clock.ns=target
        if e['record_type']=='message' and e['action']=='publish':
            d.observe(a.ingest(e['topic'],base64.b64decode(e['payload_base64'])))
    # P0 clock schedules source events; the diagnostic clock is independently injected.
    summary=replay(capture,clock=VirtualClock(),emit=event,allow_unknown_retain=True,include_invalid_frames=True)
    active=d.snapshot()
    clock.ns+=61_000_000_000;sample()
    return dict(source_sha256=capture.sha256,replay_errors=summary['errors'],
                counters=dict(a.counters),active=active,after_silence=last,
                sampled_states=dict(counts),diagnostics_sha256=digest.hexdigest())


def benchmark(capture):
    """Local CPU comparison; excludes JSON serialization, network and physical latency."""
    import statistics
    import time
    from backend.app.main import StateHub
    from backend.app.radar_bridge import prepare_frame
    from simulator.simulate_radar import load_config
    from .frames import FRAME_TOPIC, validate
    reports=[(validate(capture.payloads[r['sequence']]), capture.payloads[r['sequence']])
             for r in capture.records if r['record_type']=='message' and r['topic']==FRAME_TOPIC]
    result={}
    for enabled in (False,True):
        durations=[]
        for _ in range(3):
            clock=VirtualClock()
            a=FrameAcquisition(clock_ns=clock.now_ns)
            hub=StateHub(load_config())
            d=AcquisitionDiagnostics(a,clock=lambda:clock.ns/1e9) if enabled else None
            origin=reports[0][0]['rx_us']
            for report,payload in reports:
                clock.ns=max(clock.ns,(report['rx_us']-origin)*1000)
                start=time.perf_counter_ns()
                outcome=a.ingest(FRAME_TOPIC,payload)
                if d:d.observe(outcome)
                hub.publish(prepare_frame(a.snapshot(),hub.config['radar']['id']),notify=False)
                durations.append((time.perf_counter_ns()-start)/1e6)
        durations.sort()
        result['enabled' if enabled else 'disabled']=dict(samples=len(durations),
            mean_ms=statistics.mean(durations),p95_ms=durations[int(.95*len(durations))],
            p99_ms=durations[int(.99*len(durations))])
        if d:
            samples=[]
            for _ in range(100):
                start=time.perf_counter_ns();d.snapshot()
                samples.append((time.perf_counter_ns()-start)/1e6)
            result['snapshot_mean_ms']=statistics.mean(samples)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--benchmark',action='store_true')
    args=parser.parse_args(argv)
    capture=load_capture(args.input)
    one=diagnose(capture);two=diagnose(capture)
    result=dict(deterministic=one==two,**one)
    if args.benchmark:result['benchmark']=benchmark(capture)
    print(json.dumps(result,sort_keys=True,indent=2))
    return int(not result['deterministic'] or result['replay_errors']>0)


if __name__=='__main__':raise SystemExit(main())
