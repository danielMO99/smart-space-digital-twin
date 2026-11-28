"""P1.2a synthetic diagnostics, virtual time, no broker or radar."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from backend.app.acquisition_diagnostics import AcquisitionDiagnostics, DiagnosticPolicy
from backend.app.frame_acquisition import FrameAcquisition
from backend.app.main import create_app
from backend.app.radar_normalizer import RadarNormalizer
from mqtt_capture.frames import FRAME_TOPIC

pytestmark = pytest.mark.unit
EXAMPLES = json.loads((Path(__file__).parents[1]/'docs/contracts/ld2450-frame-v1.examples.json').read_text())


def rig(policy=None):
    clock=SimpleNamespace(t=0.)
    a=FrameAcquisition(clock_ns=lambda:int(clock.t*1e9), utc_now=lambda:datetime(2000,1,1,tzinfo=timezone.utc))
    d=AcquisitionDiagnostics(a, clock=lambda:clock.t, policy=policy, time_basis='virtual_backend_monotonic')
    def send(seq, count=1, **changes):
        r=copy.deepcopy(EXAMPLES[count]['payload'])
        r.update(seq=seq, selected_seq=seq, rx_us=round(clock.t*1e6));r.update(changes)
        with a.lock:
            outcome=a.ingest(FRAME_TOPIC,json.dumps(r).encode())
            d.observe(outcome)
        return outcome
    return clock,a,d,send


def normal_run(d,clock,send):
    for n in range(226):
        clock.t=n/11.25;send(n+1,count=0);d.distributed()
    return d.snapshot()


def test_normal_empty_rate_and_silence_without_new_reports():
    c,a,d,send=rig()
    assert d.snapshot()['overall']=='initializing'
    assert d.snapshot()['freshness']['last_received_age_s'] is None
    r=normal_run(d,c,send)
    assert r['overall']=='normal' and r['current_targets']==0
    assert r['frequency']['accepted_hz']==pytest.approx(11.3,abs=.1)
    assert r['frequency']['esp_processing_hz']==pytest.approx(11.25,abs=.001)
    assert r['frequency']['interval_p95_s']==pytest.approx(1/11.25)
    c.t+=2.001
    assert d.snapshot()['overall']=='stale'
    assert d.snapshot()['current_targets'] is None
    c.t+=61
    r=d.snapshot()
    assert r['frequency']['received_hz']==0
    assert r['frequency']['esp_processing_hz'] is None
    assert r['frequency']['interval_p95_s'] is None
    assert r['memory']['events']==0
    assert len(r['history'])==1


def test_frequency_degradation_and_reconnection():
    c,a,d,send=rig();normal_run(d,c,send)
    for seq in range(227,239):c.t+=1;send(seq)
    assert d.snapshot()['overall']=='frequency_degraded'
    a.transport(False);d.connection_changed()
    assert d.snapshot()['overall']=='disconnected'
    a.transport(True);d.connection_changed()
    assert d.snapshot()['overall']=='initializing'
    c.t+=.1;send(239)
    assert d.snapshot()['overall']=='observing'
    assert d.snapshot()['mqtt']['connected']


def test_rejections_gaps_and_valid_age():
    c,a,d,send=rig();send(10)
    c.t=1
    assert send(10,rx_us=0)=='duplicate'
    assert send(10,count=3,rx_us=0)=='conflicting_duplicate'
    assert send(9)=='out_of_order'
    assert send(12)=='accepted'
    assert send(13,rx_us=0)=='clock_regression'
    with a.lock:
        d.observe(a.ingest(FRAME_TOPIC,b'\xff'))
        d.observe(a.ingest(FRAME_TOPIC,b'{}',True))
    r=d.snapshot()
    assert r['integrity']['state']=='issues'
    for k in ('duplicate','conflicting_duplicate','out_of_order','missing_sequences','clock_regression','invalid','retained'):
        assert r['integrity']['counters'][k]==1
    c.t=2;d.observe(a.ingest(FRAME_TOPIC,b'bad'))
    r=d.snapshot()
    assert r['freshness']['last_received_age_s']==0
    assert r['freshness']['last_valid_age_s']==1


def test_source_baseline_boot_and_counter_reset():
    c,a,d,send=rig()
    diag=copy.deepcopy(EXAMPLES[1]['payload']['diagnostics']);diag['offline_reports']=63
    send(1,diagnostics=diag)
    assert d.snapshot()['esp32']['observed_increments']['offline_reports']==0
    assert d.snapshot()['integrity']['state']=='clear'
    diag['offline_reports']=65;c.t=1;send(2,diagnostics=diag)
    assert d.snapshot()['esp32']['observed_increments']['offline_reports']==2
    diag['offline_reports']=1;c.t=2;send(3,diagnostics=diag)
    assert d.snapshot()['esp32']['counter_resets']==1
    diag['offline_reports']=2;c.t=3;send(4,diagnostics=diag)
    assert d.snapshot()['esp32']['observed_increments']['offline_reports']==3
    c.t=4;send(1,boot_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',diagnostics=diag)
    r=d.snapshot()
    assert r['esp32']['observed_increments']['offline_reports']==0
    assert r['esp32']['counter_resets']==0
    assert r['integrity']['counters']['boot_changes']==1
    assert 'previous_callback_max_us' not in r['esp32']['observed_increments']


def test_memory_capacity_and_concurrent_snapshot():
    c,a,d,send=rig(DiagnosticPolicy(capacity=32))
    def writer():
        for seq in range(1,2001):send(seq)
    def reader():
        for _ in range(200):
            r=d.snapshot();json.dumps(r,allow_nan=False)
            assert r['memory']['events']<=32
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks=[pool.submit(writer),pool.submit(reader),pool.submit(reader)]
        for t in tasks:t.result(timeout=15)
    assert len(d.events)==32 and len(d.history)<=32
    assert d.snapshot()['memory']['window_complete'] is False
    assert a.counters['accepted']==2000


def test_legacy_metrics_and_reconnect():
    c=SimpleNamespace(t=0.)
    a=RadarNormalizer(clock=lambda:c.t)
    d=AcquisitionDiagnostics(a,mode='legacy',clock=lambda:c.t,source='replay')
    topic='smartspace/esp32/sensor/objetivo_1_x/state'
    d.observe(a.ingest(topic,b'10'));r=d.snapshot()
    assert r['source']=='replay' and r['esp32'] is None
    assert r['session']['boot_id'] is None
    assert r['frequency']['state']=='unavailable'
    assert r['current_targets'] is None
    a.transport(False);d.connection_changed();a.transport(True);d.connection_changed()
    assert d.snapshot()['freshness']['state']=='waiting'


def test_endpoint_simulation_and_health_compatibility(monkeypatch):
    monkeypatch.setenv('SMARTSPACE_SOURCE','simulator')
    with TestClient(create_app()) as client:
        old=client.get('/health')
        assert old.status_code==200 and set(old.json())=={'status','simulation_enabled'}
        r=client.get('/api/diagnostics').json()
        assert r['schema_version']==1
        assert r['acquisition']['source']=='simulation'
        assert r['acquisition']['mqtt'] is None
        c,a,d,send=rig();client.app.state.hub.diagnostics=d
        send(1);c.t=3
        assert client.get('/api/diagnostics').json()['acquisition']['overall']=='stale'
        assert client.get('/health').status_code==200


@pytest.mark.parametrize('changes',[{'capacity':0},{'minimum_hz':float('nan')},{'frequency_window_s':70},{'warmup_s':0}])
def test_policy_rejects_invalid(changes):
    with pytest.raises(ValueError):DiagnosticPolicy(**changes)


def test_virtual_replay_diagnostic_determinism(tmp_path):
    from mqtt_capture.import_frames import import_file
    from mqtt_capture.replay import load_capture
    from mqtt_capture.diagnose import diagnose
    source=Path(__file__).parent/'fixtures/frame_reports/scenarios.synthetic.jsonl'
    output=tmp_path/'synthetic.import.jsonl'
    import_file(source,output,evidence_kind='synthetic')
    capture=load_capture(output)
    one=diagnose(capture)
    assert one==diagnose(capture)
    assert one['after_silence']['overall']=='stale'
    assert one['after_silence']['frequency']['accepted_hz']==0
    assert one['active']['source_time_reference']=='recorded_esp_processing'


def test_integrity_window_recovers_without_lifetime_counter_reset():
    c,a,d,send=rig();send(1)
    d.observe(a.ingest(FRAME_TOPIC,b'bad'))
    assert d.snapshot()['integrity']['state']=='issues'
    c.t=11;send(2)
    r=d.snapshot()
    assert r['integrity']['state']=='clear'
    assert r['integrity']['counters']['invalid']==1


def test_ws_rate_counts_cycles_not_subscribers():
    c,a,d,send=rig();d.ws_configured_hz=10
    for i in range(1,101):c.t=i/10;d.distributed()
    r=d.snapshot()
    assert r['frequency']['ws_observed_hz']==10
    assert r['frequency']['ws_configured_hz']==10
    c.t=21
    assert d.snapshot()['frequency']['ws_observed_hz']==0


def test_delayed_first_report_and_new_boot_get_observation_period():
    c,a,d,send=rig();c.t=30;send(1)
    assert d.snapshot()['frequency']['state']=='observing'
    c.t=60;send(1,boot_id='aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    assert d.snapshot()['frequency']['state']=='observing'


def test_service_connection_and_health_remain_independent(monkeypatch):
    monkeypatch.setenv('SMARTSPACE_SOURCE','simulator')
    c,a,d,send=rig();send(1)
    with TestClient(create_app()) as client:
        hub=client.app.state.hub;hub.diagnostics=d
        hub.consumer=SimpleNamespace(callback_errors=0,normalizer=a)
        hub.mqtt_client=SimpleNamespace(_thread=SimpleNamespace(is_alive=lambda:False))
        response=client.get('/api/diagnostics').json()
        assert response['service']['status']=='error'
        assert client.get('/health').status_code==503
        hub.mqtt_client._thread.is_alive=lambda:True
        a.transport(False);d.connection_changed()
        response=client.get('/api/diagnostics').json()
        assert response['service']['status']=='ok'
        assert response['acquisition']['overall']=='disconnected'
        assert client.get('/health').status_code==503
        a.transport(True);d.connection_changed();c.t=.1;send(2)
        assert client.get('/health').status_code==200
        d.observe(a.ingest(FRAME_TOPIC,b'bad'))
        assert client.get('/health').status_code==200
        assert client.get('/api/diagnostics').json()['acquisition']['integrity']['state']=='issues'


def test_history_capacity_also_signals_incomplete_window():
    c,a,d,send=rig(DiagnosticPolicy(capacity=2));send(1)
    d.snapshot();c.t=1;d.snapshot();c.t=2
    r=d.snapshot()
    assert len(r['history'])==2
    assert not r['memory']['window_complete']
    assert 'diagnostic_window_truncated' in r['reasons']
