"""Atomic frame acquisition with injected backend clocks, no broker."""
import copy
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from backend.app.frame_acquisition import FrameAcquisition
from mqtt_capture.frames import FRAME_TOPIC

pytestmark = pytest.mark.unit
EXAMPLES = json.loads((Path(__file__).parents[1]/'docs/contracts/ld2450-frame-v1.examples.json').read_text())


@pytest.fixture
def setup():
    clock=SimpleNamespace(ns=0)
    acquisition=FrameAcquisition(clock_ns=lambda:clock.ns,
        utc_now=lambda:datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(microseconds=clock.ns/1000))
    def send(count,seq,**overrides):
        r=copy.deepcopy(EXAMPLES[count]['payload'])
        r.update(seq=seq,selected_seq=seq,rx_us=seq*100000)
        r.update(overrides)
        return acquisition.ingest(FRAME_TOPIC,json.dumps(r).encode())
    return clock,acquisition,send


def test_atomic_transitions_and_resolution(setup):
    _,a,send=setup
    for seq,count in enumerate([0,1,2,3,0],1):
        assert send(count,seq)=='accepted'
        state=a.snapshot()
        assert len(state['targets'])==count
        assert state['acquisition']['telemetry_status']=='fresh'
        assert [s['slot'] for s in state['targets']]==EXAMPLES[count]['payload']['targets']
        assert all(s['resolution_mm']==320 for s in state['targets'])
    assert a.snapshot()['acquisition']['report']['targets']==[]


def test_silence_invalid_and_retained_do_not_refresh(setup):
    clock,a,send=setup
    send(3,1);clock.ns=2_000_000_000
    assert a.snapshot()['acquisition']['telemetry_status']=='fresh'
    assert a.ingest(FRAME_TOPIC,b'\xff')=='invalid'
    assert a.ingest(FRAME_TOPIC,json.dumps(EXAMPLES[0]['payload']).encode(),True)=='retained'
    clock.ns+=1
    state=a.snapshot()
    assert not state['targets'] and state['acquisition']['telemetry_status']=='stale'
    assert state['acquisition']['report']['targets']==[1,2,3]
    assert state['observation']['occupancy']=='unknown'


def test_integrity_and_boot_retirement(setup):
    _,a,send=setup
    send(1,10)
    assert send(1,10)=='duplicate'
    assert send(3,10)=='conflicting_duplicate'
    assert send(0,9)=='out_of_order'
    assert send(0,11,rx_us=1)=='clock_regression'
    assert send(3,12)=='accepted'
    assert a.counters['missing_sequences']==1
    assert send(0,1,boot_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')=='accepted'
    assert send(3,13)=='retired_boot'
    assert not a.snapshot()['targets']


def test_disconnect_requires_new_report_and_source_exclusion(setup):
    _,a,send=setup
    send(1,1);a.transport(False)
    assert a.snapshot()['acquisition']['telemetry_status']=='disconnected'
    a.transport(True)
    assert send(1,1)=='duplicate'
    assert not a.snapshot()['targets']
    assert send(1,2)=='accepted'
    assert a.ingest('smartspace/esp32/sensor/objetivo_1_x/state',b'123')=='unexpected'
    assert a.snapshot()['targets'][0]['x_mm']==-782


def test_hub_atomic_validation_and_queue_bound(setup):
    import asyncio
    from backend.app.main import StateHub
    from backend.app.radar_bridge import prepare_frame
    from simulator.simulate_radar import load_config
    _, a, send = setup
    hub = StateHub(load_config())
    queue = asyncio.Queue(maxsize=1)
    hub.subscribers.add(queue)
    for seq, count in enumerate([3, 1, 0, 2], 1):
        send(count, seq)
        raw = prepare_frame(a.snapshot(), hub.config['radar']['id'])
        hub.publish(raw)
        assert queue.qsize() == 1
        assert len(hub.latest['targets']) == count
    before = hub.latest
    raw['targets'][0]['x_mm'] += 1
    with pytest.raises(ValueError):
        hub.publish(raw)
    assert hub.latest is before
    assert hub.publications == 4


def test_websocket_concurrent_close_without_initial_state(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    from simulator.simulate_radar import load_config
    config = load_config()
    config['simulation']['enabled'] = False
    path = tmp_path / 'room.json'
    path.write_text(json.dumps(config))
    monkeypatch.setenv('SMARTSPACE_SOURCE', 'simulator')
    with TestClient(create_app(path)) as client:
        for _ in range(100):
            with client.websocket_connect('/ws'), client.websocket_connect('/ws'):
                assert len(client.app.state.hub.subscribers) == 2
            # Barrier on the app event loop after connection cleanup.
            client.get('/api/state')
            assert not client.app.state.hub.subscribers


def test_virtual_complete_replay_preserves_atomic_reports(tmp_path):
    from mqtt_capture.import_frames import import_file
    from mqtt_capture.replay import load_capture
    from mqtt_capture.normalize_frames import states
    source = Path(__file__).parent / 'fixtures/frame_reports/scenarios.synthetic.jsonl'
    output = tmp_path / 'import.jsonl'
    import_file(source, output, evidence_kind='synthetic')
    capture = load_capture(output)
    one, counters = states(capture)
    assert (one, counters) == states(capture)
    assert set(len(s['targets']) for s in one) == {0, 1, 2, 3}
    assert counters['invalid'] > 0
    for state in one:
        report = state['acquisition']['report']
        assert [t['slot'] for t in state['targets']] == report['targets']
        for target in state['targets']:
            source = report['slots'][target['slot'] - 1]
            assert target['speed_m_s'] == pytest.approx(source['speed_mm_s'] / 1000)
            assert target['resolution_mm'] == source['resolution_mm']
