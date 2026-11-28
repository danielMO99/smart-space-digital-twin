"""Offline deterministic state replay; synthetic fixtures remain synthetic."""
import os
from pathlib import Path
import pytest
from mqtt_capture.replay import load_capture
from mqtt_capture.normalize import states, summarize
from backend.app.radar_normalizer import Policy

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).parent / 'fixtures' / 'mqtt_replay'


@pytest.mark.parametrize('name', ['multi_target.synthetic.mqtt.jsonl',
    'display_hold.synthetic.mqtt.jsonl', 'reconnection.synthetic.mqtt.jsonl'])
def test_repeated_virtual_states(name):
    capture = load_capture(FIXTURES / name, allow_incomplete=True)
    one = list(states(capture))
    assert one == list(states(capture))
    assert all(s['observation']['occupancy'] == 'unknown' for s in one)
    assert not one[-1]['targets']
    if name.startswith('display_hold'):
        counts = [len(s['targets']) for s in one]
        assert set(counts) == {0, 1, 2, 3}
        assert any([t['slot'] for t in s['targets']] == [1, 3] for s in one)
    if name.startswith('multi_target'):
        assert one[-1]['observation']['counters']['received'] == 24
        assert one[-1]['observation']['counters']['invalid'] > 0


def test_local_real_capture_deterministic_acceptance():
    path = os.environ.get('SMARTSPACE_REPLAY_CAPTURE')
    if not path:
        pytest.skip('Physical capture is local and never committed')
    capture = load_capture(path)
    one = list(states(capture, Policy()))
    assert one == list(states(capture, Policy()))
    report = summarize(one)
    assert report['with_targets'] > 0
    assert report['counters']['received'] == 767
    assert report['counters']['invalid'] == 0
    assert all(s['observation']['reported_count'] is None for s in one)
