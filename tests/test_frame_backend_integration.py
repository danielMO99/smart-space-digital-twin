"""Complete-frame MQTT integration: explicitly owned isolated broker only."""
import copy
import json
import os
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from backend.app.main import create_app
from mqtt_capture.frames import FRAME_TOPIC
from mqtt_capture.import_frames import import_file
from mqtt_capture.isolated_broker import IsolatedBroker, MqttPublisher
from mqtt_capture.replay import load_capture
from mqtt_capture.replay_app import ReplaySession

pytestmark = pytest.mark.mqtt
EXAMPLES = json.loads((Path(__file__).parents[1] / 'docs/contracts/ld2450-frame-v1.examples.json').read_text())


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            pytest.fail('Condition timed out')
        time.sleep(.01)


def test_atomic_mqtt_websocket_invalid_silence_recovery_and_load(tmp_path):
    imported = tmp_path / 'capture.jsonl'
    import_file(Path(__file__).parent / 'fixtures/frame_reports/scenarios.synthetic.jsonl', imported,
                evidence_kind='synthetic')
    executable = os.environ['SMARTSPACE_TEST_MOSQUITTO']
    with IsolatedBroker(executable) as broker:
        session = ReplaySession(load_capture(imported), broker, capture_name='synthetic',
            acquisition='frames', manual_start=True)
        with TestClient(create_app(replay_session=session)) as client, MqttPublisher(broker) as publisher:
            assert session.ready.wait(5)
            hub = client.app.state.hub
            seq = 0
            def send(count):
                nonlocal seq
                seq += 1
                report = copy.deepcopy(EXAMPLES[count]['payload'])
                report.update(seq=seq, selected_seq=seq, rx_us=seq*100000)
                publisher.publish(FRAME_TOPIC, json.dumps(report).encode(), qos=1)
                wait_until(lambda: session.consumer.normalizer.counters['accepted'] == seq)
                assert hub.latest['acquisition']['report'] == report
                return report
            with client.websocket_connect('/ws') as first, client.websocket_connect('/ws') as second:
                for count in (0, 1, 2, 3, 0):
                    report = send(count)
                    for ws in (first, second):
                        for _ in range(5):
                            state = ws.receive_json()
                            if state['acquisition']['report'] == report:
                                break
                        else:
                            pytest.fail('WebSocket did not deliver atomic state')
                        assert len(state['targets']) == count
                    diagnostic = client.get('/api/diagnostics').json()
                    assert diagnostic['service']['health_http_status'] == 200
                    assert diagnostic['acquisition']['source'] == 'replay'
                    assert diagnostic['acquisition']['current_targets'] == count
                before = hub.latest
                publisher.publish(FRAME_TOPIC, b'\xff', qos=1)
                wait_until(lambda: session.consumer.normalizer.counters['invalid'] == 1)
                assert hub.latest is before
                publisher.publish('smartspace/esp32/sensor/objetivo_1_x/state', b'999', qos=1)
                send(3)  # proves recovery and no legacy mixing
                wait_until(lambda: hub.latest['acquisition']['telemetry_status'] == 'stale', 4)
                assert not hub.latest['targets']
                assert hub.latest['observation']['occupancy'] == 'unknown'
                assert client.get('/health').status_code == 200
                diagnostic = client.get('/api/diagnostics').json()
                assert diagnostic['acquisition']['overall'] == 'stale'
                assert diagnostic['acquisition']['integrity']['state'] == 'issues'
                assert diagnostic['service']['status'] == 'ok'
                send(1)
            client.get('/api/state')
            assert not hub.subscribers
            with client.websocket_connect('/ws'):
                # Native rate for 5 seconds plus 100 Hz margin; queues remain bounded.
                for rate, count in ((11.25, 57), (100, 100)):
                    start = time.monotonic()
                    for index in range(count):
                        time.sleep(max(0, start + index / rate - time.monotonic()))
                        send(index % 4)
                    elapsed = time.monotonic() - start
                    achieved = (count - 1) / elapsed
                    print(f"Load target={rate} Hz, achieved={achieved:.2f} Hz, reports={count}")
                    assert elapsed < count / rate + 3
                    if rate == 100:
                        assert achieved > 50
                assert session.consumer.callback_errors == 0
                assert session.client._thread.is_alive()
                assert session.consumer.normalizer.counters['accepted'] == seq
                assert len(hub.subscribers) == 1
                assert all(q.qsize() <= 1 and q.maxsize == 1 for q in hub.subscribers)
        assert not session.client._thread


def test_all_local_physical_frames_reach_backend(tmp_path):
    directory = os.environ.get('SMARTSPACE_FRAME_CAPTURES')
    if not directory:
        pytest.skip('Local physical captures are not versioned')
    total = 0
    for name, expected in [('frequency',675), ('two-persons',674), ('controlled-test',1180)]:
        source = Path(directory) / f'ld2450-{name}-v1.jsonl'
        imported = tmp_path / f'{name}.jsonl'
        import_file(source, imported, evidence_kind='physical_capture')
        with IsolatedBroker(os.environ['SMARTSPACE_TEST_MOSQUITTO']) as broker:
            session = ReplaySession(load_capture(imported), broker, capture_name=source.name,
                acquisition='frames', speed='10', start_delay=0, allow_unknown_retain=True)
            with TestClient(create_app(replay_session=session)) as client:
                wait_until(lambda: session.summary is not None, 35)
                wait_until(lambda: session.consumer.normalizer.counters['accepted'] == expected)
                assert session.summary['published'] == expected
                diagnostic = client.get('/api/diagnostics').json()['acquisition']
                assert diagnostic['integrity']['counters']['accepted'] == expected
                assert diagnostic['esp32']['observed_increments']['offline_reports'] == 0
                assert session.state['consumer_errors'] == 0
                assert session.consumer.callback_errors == 0
                assert client.app.state.hub.publications >= expected
                assert client.get('/health').status_code == 200
                total += expected
    assert total == 2529
