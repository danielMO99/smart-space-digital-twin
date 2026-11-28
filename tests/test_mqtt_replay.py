"""P0.3 unit tests: synthetic evidence, virtual clocks, no network."""
import base64
import copy
import json
from pathlib import Path
import threading
from types import SimpleNamespace

import pytest

from mqtt_capture import replay as mod
from mqtt_capture.isolated_broker import IsolatedBroker, MqttPublisher

pytestmark = pytest.mark.unit
FIXTURES = Path(__file__).parent / "fixtures" / "mqtt_replay"
MULTI = FIXTURES / "multi_target.synthetic.mqtt.jsonl"
RECONNECT = FIXTURES / "reconnection.synthetic.mqtt.jsonl"


def write_records(tmp_path, records):
    path = tmp_path / "case.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def test_synthetic_transitions_slots_partial_coordinates_nan_and_exact_bytes():
    capture = mod.load_capture(MULTI)
    assert capture.records[0]["metadata"]["evidence_kind"] == "synthetic"
    published, events = [], []
    summary = mod.replay(capture, clock=mod.VirtualClock(), emit=events.append,
                         publish=lambda topic, payload, **kw: published.append((topic, payload, kw)))
    counts = [p for t, p, _ in published if "n__mero" in t]
    assert counts == [b"0", b"1", b"2", b"3", b"2", b"1", b"0"]
    assert summary["omitted_retained"] == 2
    assert summary["published"] == len(published) == len(capture.payloads) - 2
    assert summary["not_replayed"] == summary["errors"] == 0
    expected = [(r["topic"], capture.payloads[r["sequence"]],
                 dict(qos=1, retain=False)) for r in capture.records
                if r["record_type"] == "message" and not r["retain"]]
    assert published == expected
    assert [e["original_qos"] for e in events if e["record_type"] == "message"] == [
        r["qos"] for r in capture.records if r["record_type"] == "message"]
    assert b"nan" in [p for _, p, _ in published]
    assert b"\x00\xff\r\n" in [p for _, p, _ in published]
    assert b"" in [p for _, p, _ in published]
    # Count=2 uses slots 1 and 3, before any finite slot-2 coordinate.
    slot3 = next(i for i, (t, p, _) in enumerate(published) if "objetivo_3_x" in t)
    slot2 = next(i for i, (t, p, _) in enumerate(published) if "objetivo_2_x" in t)
    assert slot3 < slot2
    pairs = {e["topic"]: e["scheduled_ns"] for e in events if e.get("payload_base64")
             in [base64.b64encode(b"-100").decode(), base64.b64encode(b"1200").decode()]}
    assert len(set(pairs.values())) == 2  # asynchronous axes remain asynchronous


@pytest.mark.parametrize("speed", ["1", "10", "0.5", "3"])
def test_two_replays_are_identical_with_ties_gaps_and_scaled_deadlines(speed):
    capture = mod.load_capture(MULTI)
    runs = []
    for _ in range(2):
        clock, events = mod.VirtualClock(), []
        summary = mod.replay(capture, speed=speed, clock=clock, emit=events.append)
        runs.append((events, summary))
        ratio = mod.speed_ratio(speed)
        assert clock.now_ns() == 6_000_000_000 * ratio.denominator // ratio.numerator
        assert [e["sequence"] for e in events] == list(range(len(capture.records)))
        assert [e["scheduled_ns"] for e in events] == [
            r["monotonic_ns"] * ratio.denominator // ratio.numerator for r in capture.records]
    assert runs[0] == runs[1]
    assert runs[0][1]["published"] == 0  # dry-run must not claim delivery


def test_retained_never_becomes_fresh_even_after_reconnection():
    capture = mod.load_capture(RECONNECT, allow_incomplete=True)
    events, publications = [], []
    summary = mod.replay(capture, clock=mod.VirtualClock(), emit=events.append,
                         publish=lambda *a, **k: publications.append(a))
    retained = [e for e in events if e.get("original_retain")]
    assert len(retained) == 1 and retained[0]["action"] == "omit_retained"
    assert summary["published"] == 2 and summary["source_incomplete"]
    assert [e["event"] for e in events if e["record_type"] == "event"] == [
        "connected", "disconnected", "possible_loss", "reconnection_attempt", "reconnected", "disconnected"]
    assert all(e["scope"] == "recorder_to_broker" for e in events if e["record_type"] == "event")


def test_incomplete_requires_opt_in_and_does_not_repair(tmp_path):
    with pytest.raises(mod.CaptureValidationError, match="incompleta"):
        mod.load_capture(RECONNECT)
    records = list(mod.load_capture(MULTI).records)[:-1]
    path = write_records(tmp_path, records)
    with pytest.raises(mod.CaptureValidationError, match="incompleta"):
        mod.load_capture(path)
    capture = mod.load_capture(path, allow_incomplete=True)
    assert capture.incomplete and capture.records[-1]["record_type"] == "event"


@pytest.mark.parametrize("allow", [False, True])
def test_truncated_json_is_always_rejected(allow):
    with pytest.raises(mod.CaptureValidationError):
        mod.load_capture(FIXTURES / "truncated.synthetic.mqtt.jsonl", allow_incomplete=allow)


@pytest.mark.parametrize("index,key,value", [
    (0, "schema_version", 2), (0, "schema_version", True), (0, "format", "other"),
    (1, "session_id", "00000000-0000-4000-8000-000000000099"),
    (1, "sequence", 0), (1, "sequence", 99), (1, "sequence", True),
    (5, "monotonic_ns", -1), (5, "monotonic_ns", 0), (5, "monotonic_ns", 1.5),
    (5, "timestamp_utc", "2020-01-01"), (5, "timestamp_utc", "invalidZ"),
    (5, "record_type", "unknown"), (5, "topic", "smartspace/esp32/switch/multi_target/command"),
    (5, "topic", "smartspace/esp32/sensor/+/state"), (5, "qos", 3), (5, "qos", True),
    (5, "retain", "false"), (5, "dup", 0), (5, "connection", 0), (5, "mid", -1),
    (5, "payload_base64", "%%%"), (5, "payload_base64", "é"),
    (-1, "messages_written", 99), (-1, "finalized", False),
    (1, "event", "unknown"), (1, "session_present", 1),
])
def test_invalid_records_fail_preflight(tmp_path, index, key, value):
    records = copy.deepcopy(list(mod.load_capture(MULTI).records))
    records[index][key] = value
    with pytest.raises(mod.CaptureValidationError):
        mod.load_capture(write_records(tmp_path, records), allow_incomplete=True)


@pytest.mark.parametrize("text", ["", "\n", "[]\n", '{"a":1,"a":2}\n', '{"a":NaN}\n', '\ufeff{}\n'])
def test_invalid_json(tmp_path, text):
    path = tmp_path / "bad.jsonl"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(mod.CaptureValidationError):
        mod.load_capture(path)


def test_records_after_footer_and_unknown_header_topics_rejected(tmp_path):
    records = copy.deepcopy(list(mod.load_capture(MULTI).records))
    with pytest.raises(mod.CaptureValidationError):
        mod.load_capture(write_records(tmp_path, records + [records[-1]]))
    records[0]["metadata"]["topics"][0] = "commands"
    with pytest.raises(mod.CaptureValidationError):
        mod.load_capture(write_records(tmp_path, records))


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "inf", "-inf", "oops"])
def test_invalid_speed(value):
    with pytest.raises(ValueError):
        mod.speed_ratio(value)


def test_absolute_clock_deadlines_do_not_accumulate_publication_latency():
    clock = mod.VirtualClock()
    observed = []

    def slow_publish(*a, **k):
        observed.append(clock.now_ns())
        clock.ns += 1_000_000

    events = []
    summary = mod.replay(mod.load_capture(MULTI), clock=clock, publish=slow_publish, emit=events.append)
    assert not summary["errors"]
    assert clock.now_ns() == 6_000_000_000
    assert observed[0] == 100_000_000 and observed[1] == 200_000_000


def test_interrupt_error_and_output_failure_report_partial_progress():
    capture = mod.load_capture(MULTI)
    stop = threading.Event()

    def interrupt(*a, **k):
        stop.set()

    summary = mod.replay(capture, clock=mod.VirtualClock(), stop=stop, publish=interrupt)
    assert summary["status"] == "interrupted" and summary["published"] == 1
    assert summary["not_replayed"] == len(capture.payloads) - 3

    def fail(*a, **k):
        raise OSError("secret must not be exposed")

    for kw in ({"publish": fail}, {"emit": fail}):
        summary = mod.replay(capture, clock=mod.VirtualClock(), **kw)
        assert summary["errors"] == 1 and summary["status"] == "error"
        assert "secret" not in json.dumps(summary)


def test_cli_output_exclusive_no_network_and_invalid_input_preflight(tmp_path, monkeypatch, capsys):
    output = tmp_path / "events.jsonl"
    args = ["--input", str(MULTI), "--dry-run", "--virtual-clock", "--events-output", str(output)]
    assert mod.main(args) == 0
    before = output.read_bytes()
    assert mod.main(args) == 1 and output.read_bytes() == before
    assert mod.main(["--input", str(FIXTURES / "truncated.synthetic.mqtt.jsonl"),
                     "--mosquitto", "never-start-this.exe"]) == 1
    assert "mode" in capsys.readouterr().out


@pytest.mark.parametrize("args", [["--broker", "192.168.1.200"], ["--broker", "localhost"],
                                 ["--port", "1883"], ["--virtual-clock"], []])
def test_cli_blocks_external_brokers_and_unsafe_modes(args):
    with pytest.raises(SystemExit) as exc:
        mod.main(["--input", str(MULTI)] + args)
    assert exc.value.code == 2


def test_isolated_endpoint_guard_and_publication_allowlist():
    broker = IsolatedBroker("missing.exe")
    for host in ("192.168.1.200", "localhost", "127.0.0.1"):
        broker.host = host
        with pytest.raises(RuntimeError):
            broker.check()
    class SafeBroker:
        def check(self):
            pass
    publisher = MqttPublisher(SafeBroker())
    for topic, qos, retain in [("command", 0, False), (mod.TELEMETRY_TOPICS[0], 0, True),
                                (mod.TELEMETRY_TOPICS[0], 3, False)]:
        with pytest.raises(ValueError):
            publisher.publish(topic, b"1", qos=qos, retain=retain)


def test_missing_broker_and_forbidden_endpoint_never_connect(tmp_path):
    with pytest.raises(ValueError):
        with IsolatedBroker(tmp_path / "missing.exe"):
            pytest.fail("Missing broker was accepted")
    broker = IsolatedBroker("unused.exe")
    broker.process = SimpleNamespace(poll=lambda: None)
    broker.port = 1883
    with pytest.raises(RuntimeError):
        broker.check()
    broker.port = 40000
    broker.host = "192.168.1.200"
    with pytest.raises(RuntimeError):
        broker.check()


def test_publication_timeout_stops_without_retry():
    broker = SimpleNamespace(check=lambda: None)
    publisher = MqttPublisher(broker)
    publisher.connected.set()
    calls = []
    def publish(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(rc=0, wait_for_publish=lambda timeout: None,
                               is_published=lambda: False)
    publisher.client = SimpleNamespace(publish=publish)
    with pytest.raises(RuntimeError, match="sin confirmar"):
        publisher.publish(mod.TELEMETRY_TOPICS[0], b"1", qos=1)
    assert len(calls) == 1 and calls[0][1]["retain"] is False


def test_cli_preserves_progress_if_broker_cleanup_fails(monkeypatch, capsys):
    from mqtt_capture import isolated_broker
    class Broker:
        def __init__(self, *args):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            raise RuntimeError("cleanup failed with a secret")
    class Publisher(Broker):
        def check(self):
            pass
        def publish(self, *args, **kwargs):
            pass
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(isolated_broker, "IsolatedBroker", Broker)
    monkeypatch.setattr(isolated_broker, "MqttPublisher", Publisher)
    monkeypatch.setattr(mod, "RealClock", mod.VirtualClock)
    assert mod.main(["--input", str(MULTI), "--mosquitto", "unused.exe"]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary["published"] == 24 and summary["errors"] == 1
    assert "secret" not in json.dumps(summary)


def test_replay_clock_interrupt_and_source_error_preserved(tmp_path):
    class InterruptClock(mod.VirtualClock):
        def wait_until(self, *args):
            raise KeyboardInterrupt()
    summary = mod.replay(mod.load_capture(MULTI), clock=InterruptClock())
    assert summary["status"] == "interrupted" and summary["published"] == 0
    records = copy.deepcopy(list(mod.load_capture(MULTI).records))
    records[1].update(event="error", stage="network_loop", reason_code=7, error_type="OSError")
    records[-1].update(status="incomplete", errors=1)
    path = write_records(tmp_path, records)
    with pytest.raises(mod.CaptureValidationError):
        mod.load_capture(path)
    events = []
    summary = mod.replay(mod.load_capture(path, allow_incomplete=True),
                         clock=mod.VirtualClock(), emit=events.append)
    assert summary["source_errors"] == 1 and summary["errors"] == 0
    assert events[1]["details"] == dict(stage="network_loop", reason_code=7, error_type="OSError")


def test_transport_failure_in_final_silence_is_not_reported_as_success():
    clock = mod.VirtualClock()
    def check():
        if clock.now_ns() >= 6_000_000_000:
            raise RuntimeError("Connection lost after the last telemetry")
    summary = mod.replay(mod.load_capture(MULTI), clock=clock, check=check,
                         publish=lambda *a, **k: None)
    assert summary["published"] == 24
    assert summary["errors"] == 1 and summary["status"] == "error"
