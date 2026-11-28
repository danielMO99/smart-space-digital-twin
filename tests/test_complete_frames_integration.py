"""Frame replay uses only the owned local broker; no physical radar."""
import base64
import io
import json
import threading
from pathlib import Path
import pytest
from mqtt_capture.frames import FRAME_TOPIC
from mqtt_capture.record import JsonlWriter, Recorder, TOPIC_MODES, TELEMETRY_TOPICS
from mqtt_capture.import_frames import import_file
from mqtt_capture.isolated_broker import MqttPublisher
from mqtt_capture.replay import load_capture, replay, VirtualClock
from test_mqtt_replay_integration import broker, Subscriber

pytestmark = pytest.mark.mqtt


def frame_subscriber(broker, expected=0):
    sub = Subscriber(broker, expected)
    sub.client.on_connect = lambda client, *args: client.subscribe(FRAME_TOPIC, 2)
    return sub


def test_complete_frame_bytes_order_qos_and_no_retained_state(broker, tmp_path):
    source = Path(__file__).parent/'fixtures/frame_reports/scenarios.synthetic.jsonl'
    target = tmp_path/'import.jsonl'
    import_file(source, target, evidence_kind='synthetic')
    capture = load_capture(target)
    events=[]
    replay(capture, clock=VirtualClock(), emit=events.append, allow_unknown_retain=True)
    expected=[(e['topic'],base64.b64decode(e['payload_base64']),1,False)
              for e in events if e['action']=='publish']
    with frame_subscriber(broker,len(expected)) as sub, MqttPublisher(broker) as publisher:
        result=replay(capture,clock=VirtualClock(),publish=publisher.publish,
                      check=publisher.check,allow_unknown_retain=True)
        assert result['published']==9 and result['omitted_invalid_frames']==1 and result['errors']==0
        assert sub.received.wait(5) and sub.rows==expected
    with frame_subscriber(broker) as late:
        assert not late.any_message.wait(.5)


def test_frame_publisher_still_rejects_commands_and_retain(broker):
    with MqttPublisher(broker) as publisher:
        with pytest.raises(ValueError):
            publisher.publish('smartspace/esp32/switch/multi_target_tracking/command',b'ON',qos=1)
        with pytest.raises(ValueError):
            publisher.publish(FRAME_TOPIC,b'{}',qos=1,retain=True)


def test_record_frames_and_legacy_simultaneously(broker, tmp_path):
    import paho.mqtt.client as mqtt
    stream=io.StringIO();writer=JsonlWriter(stream)
    topics=TOPIC_MODES['both']
    writer.emit('session_start',metadata=dict(topics=list(topics),payload_encoding='base64',time_origin='session_start'))
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(broker.username,broker.password)
    recorder=Recorder(writer,client,topics)
    ready,received=threading.Event(),threading.Event()
    def subscribed(*args):
        recorder.on_subscribe(*args)
        if recorder.ready: ready.set()
    def message(*args):
        recorder.on_message(*args)
        if recorder.written==2: received.set()
    client.on_subscribe=subscribed;client.on_message=message
    payload=(Path(__file__).parent/'fixtures/frame_reports/scenarios.synthetic.jsonl').read_bytes().splitlines()[1]
    try:
        client.connect(broker.host,broker.port);client.loop_start()
        assert ready.wait(5)
        with MqttPublisher(broker) as publisher:
            publisher.publish(FRAME_TOPIC,payload,qos=1)
            publisher.publish(TELEMETRY_TOPICS[1],b'123',qos=1)
        assert received.wait(5)
    finally:
        recorder.stopping=True;client.disconnect();client.loop_stop()
    writer.emit('session_end',finalized=True,status='complete',reason='duration',messages_received=2,
                messages_written=2,ignored_messages=0,errors=0,unexpected_disconnects=0,connections=1)
    path=tmp_path/'both.jsonl';path.write_text(stream.getvalue())
    capture=load_capture(path)
    assert list(capture.payloads.values())==[payload,b'123']
    assert capture.frame_analysis['valid']==1 and capture.frame_analysis['invalid']==0
    assert recorder.errors==0
