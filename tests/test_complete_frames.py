"""P1.1c.3 synthetic reports; never physical detection evidence."""
import base64
import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from mqtt_capture.frames import Analyzer, FrameError, FRAME_TOPIC, validate
from mqtt_capture.import_frames import import_file, load_import
from mqtt_capture.record import JsonlWriter, Recorder, TOPIC_MODES
from mqtt_capture.replay import load_capture, replay, VirtualClock, CaptureValidationError

pytestmark = pytest.mark.unit
FIXTURE = Path(__file__).parent/'fixtures/frame_reports/scenarios.synthetic.jsonl'
EXAMPLES = [json.loads(line) for line in FIXTURE.read_text().splitlines()[:5]]


@pytest.mark.parametrize('row', EXAMPLES)
def test_frame_contract(row):
    assert validate(json.dumps(row).encode()) == row


@pytest.mark.parametrize('field,value', [('version',True),('seq',0),('seq',1.5),('rx_us',-1),
    ('targets',[True]),('targets',[]),('boot_id','bad'),('selected_seq',1000)])
def test_invalid_frame(field,value):
    row = copy.deepcopy(EXAMPLES[1]); row[field] = value
    with pytest.raises(FrameError): validate(json.dumps(row).encode())


@pytest.mark.parametrize('payload',[b'\xff',b'',b'[]',b'{"seq":1,"seq":2}',b'{"seq":NaN}'])
def test_invalid_payloads(payload):
    with pytest.raises(FrameError): validate(payload)


def test_partial_unknown_and_infinite():
    for value in (None,float('inf'),1.5):
        row=copy.deepcopy(EXAMPLES[1]);row['slots'][0]['speed_mm_s']=value
        with pytest.raises(FrameError): validate(json.dumps(row).encode())


def imported(tmp_path, source=FIXTURE):
    path=tmp_path/'import.jsonl'
    import_file(source,path,evidence_kind='synthetic')
    return path,load_capture(path)


def test_lossless_import_determinism_and_discontinuities(tmp_path):
    path,capture=imported(tmp_path)
    archive=[json.loads(line) for line in path.read_text().splitlines()]
    assert b''.join(base64.b64decode(r['source_line_base64']) for r in archive[1:-1]) == FIXTURE.read_bytes()
    assert capture.frame_analysis['invalid']==1
    assert capture.frame_analysis['issues']=={'boot_change':1,'clock_regression':1,'duplicate':1,'sequence_gap':1,'telemetry_gap':1}
    one,two=[],[]
    a=replay(capture,clock=VirtualClock(),emit=one.append,allow_unknown_retain=True)
    b=replay(capture,clock=VirtualClock(),emit=two.append,allow_unknown_retain=True)
    assert a==b and one==two
    assert a['planned']==9 and a['omitted_invalid_frames']==1
    assert all(e['source_timestamp_utc'] is None and e['source_monotonic_ns'] is None for e in one)
    msgs=[e for e in one if e['record_type']=='message']
    assert all(e['original_qos'] is None and e['original_retain'] is None for e in msgs)
    assert msgs[6]['scheduled_ns']-msgs[5]['scheduled_ns']==1_600_000_000
    assert msgs[7]['timing_boundary']=='collapsed_unknown_boundary'
    assert msgs[7]['scheduled_ns']==msgs[6]['scheduled_ns']
    assert [e['frame']['targets'] for e in msgs[:5]]==[[],[1],[1,3],[1,2,3],[]]
    assert replay(capture,clock=VirtualClock())['omitted_unknown_retain']==10
    assert replay(capture,clock=VirtualClock(),allow_unknown_retain=True,include_invalid_frames=True)['planned']==10


def test_archive_tamper_truncation_and_no_overwrite(tmp_path):
    path,_=imported(tmp_path)
    with pytest.raises(FileExistsError): import_file(FIXTURE,path)
    rows=path.read_text().splitlines()
    path.write_text('\n'.join(rows[:-1]))
    with pytest.raises(CaptureValidationError): load_capture(path)
    first=json.loads(rows[1]);first['source_line_base64']=base64.b64encode(b'{}\n').decode()
    rows[1]=json.dumps(first);path.write_text('\n'.join(rows))
    with pytest.raises(CaptureValidationError): load_capture(path)


def test_bom_crlf_and_unterminated_line_are_archived_exactly(tmp_path):
    source=tmp_path/'direct.jsonl'
    payload=json.dumps(EXAMPLES[1]).encode()
    raw=b'\xef\xbb\xbf'+payload+b'\r\n'+payload
    source.write_bytes(raw)
    path,capture=imported(tmp_path,source)
    assert list(capture.payloads.values())==[payload,payload]
    assert capture.records[0]['metadata']['source_completeness']=='unknown'
    assert b''.join(base64.b64decode(json.loads(r)['source_line_base64'])
                    for r in path.read_text().splitlines()[1:-1])==raw


def test_retained_does_not_seed_continuity_and_conflicting_duplicates():
    a=Analyzer();r=copy.deepcopy(EXAMPLES[1]);r['seq']=100
    a.feed(json.dumps(r).encode(),retain=True)
    r['seq']=2;a.feed(json.dumps(r).encode())
    assert 'sequence_regression' not in a.summary()['issues']
    r['rx_us']+=1
    assert a.feed(json.dumps(r).encode())['issues']==['conflicting_duplicate']


@pytest.mark.parametrize('mode',['frames','both'])
def test_recorder_keeps_bad_bytes_and_receive_time_separate(tmp_path,mode):
    output=io.StringIO();clock=SimpleNamespace(ns=0)
    writer=JsonlWriter(output,clock_ns=lambda:clock.ns)
    topics=TOPIC_MODES[mode]
    writer.emit('session_start',metadata=dict(topics=list(topics),payload_encoding='base64',time_origin='session_start'))
    client=SimpleNamespace(subscribe=lambda pairs:(0,42))
    rec=Recorder(writer,client,topics)
    rec.on_connect(client,None,SimpleNamespace(session_present=False),0,None)
    rec.on_subscribe(client,None,42,[0]*len(topics),None)
    payloads=[json.dumps(EXAMPLES[1]).encode(),b'\xff']
    for payload in payloads:
        clock.ns+=1_000_000
        rec.on_message(client,None,SimpleNamespace(topic=FRAME_TOPIC,payload=payload,qos=0,retain=False,dup=False,mid=0))
    writer.emit('session_end',finalized=True,status='complete',reason='duration',messages_received=2,
                messages_written=2,ignored_messages=0,errors=0,unexpected_disconnects=0,connections=1)
    path=tmp_path/'recorded.jsonl';path.write_text(output.getvalue())
    capture=load_capture(path)
    assert list(capture.payloads.values())==payloads
    assert capture.time_basis=='mqtt_receive' and capture.frame_analysis['invalid']==1
    events=[]
    summary=replay(capture,clock=VirtualClock(),emit=events.append)
    assert summary['planned']==1 and summary['omitted_invalid_frames']==1
    msg=next(e for e in events if e['action']=='publish')
    assert msg['source_monotonic_ns']==1_000_000
    assert msg['frame']['rx_us']==100_000
    assert rec.errors==0 and rec.written==2  # data rejection is not a capture I/O failure
