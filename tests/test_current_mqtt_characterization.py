"""P1.1b intended changes to the P1.1a baseline (see normalization-p11b.md)."""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
from backend.app.radar_normalizer import RadarNormalizer, Policy
from backend.app.mqtt_consumer import MQTTConsumer
from backend.app.main import StateHub
from backend.app.radar_bridge import prepare_frame
from simulator.simulate_radar import load_config
pytestmark=pytest.mark.unit
PREFIX='smartspace/esp32/sensor/'
@pytest.fixture
def setup():
    clock=SimpleNamespace(now=0.)
    n=RadarNormalizer(clock=lambda:clock.now,utc_now=lambda:datetime(2020,1,1,tzinfo=timezone.utc)+timedelta(seconds=clock.now))
    def send(name,value,retain=False): return n.ingest(PREFIX+name+'/state',value if isinstance(value,bytes) else str(value).encode(),retain)
    return clock,n,send
def positions(n): return n.snapshot()['targets']
def xy(send,slot=1):
    send(f'objetivo_{slot}_x',100)
    send(f'objetivo_{slot}_y',1000)
def test_coordinates_without_counter_and_unknown_speed(setup):
    _,n,send=setup
    xy(send)
    hub=StateHub(load_config());hub.publish(prepare_frame(n.snapshot(),'radar_01'))
    assert hub.latest['targets'][0]['speed_m_s'] is None
    assert hub.latest['targets'][0]['x_m']==2.1
    assert hub.latest['observation']['reported_count'] is None
    send('objetivo_1_velocidad',0)
    assert positions(n)[0]['speed_mm_s']==0
@pytest.mark.parametrize('age,present',[(1.999,True),(2,True),(2.001,False)])
def test_ttl(setup,age,present):
    clock,n,send=setup;xy(send);clock.now=age
    assert bool(positions(n)) is present
@pytest.mark.parametrize('skew,present',[(.249,True),(.25,True),(.251,False)])
def test_xy_coherence(setup,skew,present):
    clock,n,send=setup;send('objetivo_1_x',100);clock.now=skew;send('objetivo_1_y',1000)
    assert bool(positions(n)) is present
    assert n.snapshot()['observation']['association']=='temporal_not_synchronized'
@pytest.mark.parametrize('value',[b'nan',b'inf',b'-inf',b'bad',b'\xff',b''])
def test_invalid_invalidates_only_affected_field_and_recovers(setup,value):
    _,n,send=setup;xy(send)
    assert send('objetivo_1_x',value)=='invalid'
    assert not positions(n)
    send('objetivo_1_x',200)
    assert positions(n)[0]['x_mm']==200
    assert n.counters['invalid']==1
def test_nonconsecutive_slots_counter_contradictions_and_expiry(setup):
    clock,n,send=setup;xy(send,1);xy(send,3);send('n__mero_de_objetivos',0)
    obs=n.snapshot()['observation']
    assert obs['reported_count']==0 and obs['observed_slots']==2 and obs['count_inconsistent']
    assert [t['slot'] for t in positions(n)]==[1,3]
    clock.now=3;xy(send,1)
    assert n.snapshot()['observation']['reported_count'] is None
def test_retained_partial_disconnect_and_unknown_occupancy(setup):
    clock,n,send=setup
    send('objetivo_1_x',100,True);send('objetivo_1_y',1000)
    assert not positions(n)
    xy(send);n.transport(False)
    assert not positions(n) and n.snapshot()['observation']['occupancy']=='unknown'
    n.transport(True);send('objetivo_1_x',100)
    assert not positions(n)
    send('objetivo_1_y',1000);assert positions(n)
def test_unknown_speed_expiration_and_nan(setup):
    clock,n,send=setup;xy(send);send('objetivo_1_velocidad',80)
    send('objetivo_1_velocidad','nan');assert positions(n)[0]['speed_mm_s'] is None
    send('objetivo_1_velocidad',80);clock.now=3;xy(send)
    assert positions(n)[0]['speed_mm_s'] is None
def test_instances_and_adapter_exception_containment(setup):
    _,n,send=setup;xy(send)
    assert not positions(RadarNormalizer())
    adapter=MQTTConsumer(n);n.transport(True)
    for payload in (b'\xff',b'nan',b'123'):
        adapter.on_message(None,None,SimpleNamespace(topic=PREFIX+'objetivo_1_x/state',payload=payload,retain=False))
    assert adapter.callback_errors==0
    adapter.on_message(None,None,None)
    assert adapter.callback_errors==1 and not n.connected
@pytest.mark.parametrize('ttl,skew',[(0,.1),(2,3),(float('nan'),.1),(2,-1)])
def test_invalid_policy(ttl,skew):
    with pytest.raises(ValueError): Policy(ttl,skew)


def test_replay_cannot_be_enabled_by_environment_alone(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    monkeypatch.setenv("SMARTSPACE_SOURCE", "replay")
    with pytest.raises(ValueError, match="lanzador aislado"):
        with TestClient(create_app()):
            pass


def test_ordinary_application_runtime_does_not_enable_replay(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    monkeypatch.setenv("SMARTSPACE_SOURCE", "simulator")
    with TestClient(create_app()) as client:
        assert client.get("/api/runtime").json() == {"mode": "simulator"}
        assert client.post("/api/replay/start").status_code == 409


@pytest.mark.parametrize("field,value", [("observed_slots", 3), ("count_inconsistent", True)])
def test_invalid_observation_does_not_replace_state(setup, field, value):
    _, normalizer, send = setup
    xy(send)
    hub = StateHub(load_config())
    frame = prepare_frame(normalizer.snapshot(), "radar_01")
    hub.publish(frame)
    previous = hub.latest
    frame["observation"][field] = value
    with pytest.raises(ValueError):
        hub.publish(frame)
    assert hub.latest is previous
