import base64
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import signal
import subprocess
import sys
import threading
from types import SimpleNamespace

import paho.mqtt.client as mqtt
import pytest

from mqtt_capture import record


pytestmark = pytest.mark.unit
STAMP = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
TOPIC = "smartspace/esp32/sensor/objetivo_1_x/state"


class Clock:
    def __init__(self):
        self.ns = 5_000_000_000

    def now(self):
        return self.ns

    def sleep(self, seconds):
        self.ns += round(seconds * 1_000_000_000)


def message(payload=b"123", topic=TOPIC, qos=0, retain=False, dup=False):
    return SimpleNamespace(topic=topic, payload=payload, qos=qos, retain=retain,
                           dup=dup, mid=17)


class FakeClient:
    """Callbacks run in the same thread as loop(), like the recorder's Paho usage."""
    def __init__(self, clock, scripts=None, connect_failures=0, connack=0,
                 subscribe_rc=0, grants=None, no_suback=False, **options):
        self.clock = clock
        self.scripts = scripts or [[]]
        self.connect_failures = connect_failures
        self.connack = connack
        self.subscribe_rc = subscribe_rc
        self.grants = [2] * 10 if grants is None else grants
        self.no_suback = no_suback
        self.options = options
        self.connect_calls = []
        self.subscriptions = []
        self.disconnect_calls = 0
        self.attempts = 0
        self.connected = False
        self.pending = []

    def connect(self, broker, port, keepalive):
        self.connect_calls.append((broker, port, keepalive))
        self.attempts += 1
        if self.attempts <= self.connect_failures:
            raise OSError("do not log username:password")
        index = min(self.attempts - self.connect_failures - 1, len(self.scripts) - 1)
        self.pending = ["connack"]
        if not self.no_suback:
            self.pending.append("suback")
        self.pending.extend(self.scripts[index])
        return mqtt.MQTT_ERR_SUCCESS

    def subscribe(self, topics):
        self.subscriptions.append(topics)
        return self.subscribe_rc, 42

    def loop(self, timeout):
        self.clock.sleep(timeout)
        if not self.pending:
            return mqtt.MQTT_ERR_SUCCESS
        item = self.pending.pop(0)
        if item == "connack":
            self.connected = self.connack == 0
            self.on_connect(self, None, SimpleNamespace(session_present=False),
                            SimpleNamespace(value=self.connack), None)
            if not self.connected:
                return mqtt.MQTT_ERR_CONN_REFUSED
        elif item == "suback":
            self.on_subscribe(self, None, 42,
                              [SimpleNamespace(value=q) for q in self.grants], None)
        elif item == "disconnect":
            self.connected = False
            self.on_disconnect(self, None, None, SimpleNamespace(value=128), None)
            return mqtt.MQTT_ERR_CONN_LOST
        elif item == "clean_disconnect":
            self.connected = False
            self.on_disconnect(self, None, None, SimpleNamespace(value=0), None)
        elif isinstance(item, BaseException):
            raise item
        elif callable(item):
            item()
        else:
            self.on_message(self, None, item)
        return mqtt.MQTT_ERR_SUCCESS

    def disconnect(self):
        self.disconnect_calls += 1
        if self.connected:
            self.connected = False
            if self.on_disconnect:
                self.on_disconnect(self, None, None, SimpleNamespace(value=0), None)
        return mqtt.MQTT_ERR_SUCCESS

    def socket(self):
        return None

    def publish(self, *args, **kwargs):
        pytest.fail("The recorder must never publish")


def run_capture(tmp_path, *, duration=1, scripts=None, stop=None, **client_options):
    clock = Clock()
    client = FakeClient(clock, scripts=scripts, **client_options)

    def factory(**options):
        client.options = options
        return client

    output = tmp_path / "nested" / "capture.mqtt.jsonl"
    stderr = io.StringIO()
    result = record.capture(output, duration=duration, client_factory=factory,
                            clock_ns=clock.now, utc_now=lambda: STAMP,
                            sleep=clock.sleep, stop=stop, stderr=stderr)
    records = [json.loads(line) for line in output.read_text().splitlines()]
    return result, records, client, stderr.getvalue()


def test_original_bytes_order_metadata_and_retained_duplicates(tmp_path):
    raw = [b"\xff\x00\n", b"", b" 1.00\r\n", b" 1.00\r\n"]
    inputs = [message(value, qos=2, retain=True, dup=i == 3) for i, value in enumerate(raw)]
    result, rows, client, errors = run_capture(tmp_path, scripts=[inputs])
    assert result == 0 and not errors
    assert rows[0]["record_type"] == "session_start"
    assert rows[0]["metadata"]["paho_mqtt_version"] == "2.2.0"
    assert rows[-1]["status"] == "complete" and rows[-1]["finalized"]
    assert rows[-1]["messages_written"] == 4
    assert rows[-1]["lost_messages"] is None
    messages = [r for r in rows if r["record_type"] == "message"]
    assert [base64.b64decode(r["payload_base64"], validate=True) for r in messages] == raw
    assert all(r["topic"] == TOPIC and r["qos"] == 2 and r["retain"] for r in messages)
    assert [r["dup"] for r in messages] == [False, False, False, True]
    assert [r["sequence"] for r in rows] == list(range(len(rows)))
    assert len({r["session_id"] for r in rows}) == 1
    assert all(r["schema_version"] == 1 and r["format"] == record.FORMAT for r in rows)
    assert all(r["timestamp_utc"] == "2026-11-24T12:00:00.000000Z" for r in rows)
    assert [r["monotonic_ns"] for r in messages] == [300_000_000, 400_000_000, 500_000_000, 600_000_000]
    assert rows[-1]["monotonic_ns"] == 1_000_000_000
    assert client.options["callback_api_version"] == mqtt.CallbackAPIVersion.VERSION2
    assert client.options["clean_session"] is True
    assert client.disconnect_calls == 1


def test_exact_existing_topics_and_no_command_or_unrelated_payload(tmp_path):
    expected = ["smartspace/esp32/sensor/n__mero_de_objetivos/state"] + [
        f"smartspace/esp32/sensor/objetivo_{slot}_{field}/state"
        for slot in range(1, 4) for field in ("x", "y", "velocidad")]
    inputs = [message(topic=topic) for topic in expected]
    inputs += [message(b"secret", topic="smartspace/esp32/switch/multi_target_tracking/command"),
               message(b"secret", topic="smartspace/esp32/sensor/unknown/state")]
    result, rows, client, _ = run_capture(tmp_path, duration=2, scripts=[inputs])
    assert result == 0
    assert client.subscriptions == [[(t, 2) for t in expected]]
    assert rows[-1]["messages_written"] == 10 and rows[-1]["ignored_messages"] == 2
    assert base64.b64encode(b"secret").decode() not in json.dumps(rows)


@pytest.mark.parametrize("disconnect", ["disconnect", "clean_disconnect"])
def test_disconnect_reconnect_resubscribe_and_known_gap(tmp_path, disconnect):
    result, rows, client, errors = run_capture(
        tmp_path, duration=3, scripts=[[message(b"1"), disconnect], [message(b"2")]])
    assert result == 1 and "incompleta" in errors
    events = [r.get("event") for r in rows]
    for event in ("connected", "disconnected", "possible_loss", "reconnection_attempt", "reconnected"):
        assert event in events
    assert len(client.subscriptions) == 2
    assert rows[-1]["unexpected_disconnects"] == 1
    assert rows[-1]["messages_written"] == 2 and rows[-1]["status"] == "incomplete"


def test_connection_failure_retries_without_recording_exception_secrets(tmp_path):
    result, rows, client, errors = run_capture(
        tmp_path, duration=3, connect_failures=1, scripts=[[message()]])
    assert result == 1 and client.attempts == 2
    assert any(r.get("stage") == "connect" for r in rows)
    assert "username" not in json.dumps(rows) + errors
    assert "password" not in json.dumps(rows) + errors
    assert rows[-1]["messages_written"] == 1


@pytest.mark.parametrize("options", [
    {"connack": 135}, {"subscribe_rc": 4}, {"grants": [128] * 10},
    {"grants": [0]}, {"no_suback": True},
])
def test_rejected_or_unconfirmed_subscription_is_incomplete(tmp_path, options):
    result, rows, client, _ = run_capture(tmp_path, scripts=[[message()]], **options)
    assert result == 1
    assert rows[-1]["status"] == "incomplete"
    assert any(r.get("event") == "error" for r in rows)
    assert client.disconnect_calls == 1


def test_handshake_timeout(tmp_path):
    result, rows, _, _ = run_capture(tmp_path, duration=8, no_suback=True)
    assert result == 1 and rows[-1]["reason"] == "handshake_timeout"
    assert rows[-1]["monotonic_ns"] == 5_000_000_000


def test_no_messages_is_not_zero_targets(tmp_path):
    result, rows, _, _ = run_capture(tmp_path)
    assert result == 1 and rows[-1]["messages_written"] == 0
    assert any(r.get("stage") == "no_telemetry" for r in rows)
    assert not any(r["record_type"] == "message" for r in rows)


def test_explicit_zero_target_measurement_is_valid(tmp_path):
    result, rows, _, _ = run_capture(
        tmp_path, scripts=[[message(b"0", topic=record.TELEMETRY_TOPICS[0])]])
    assert result == 0 and rows[-1]["messages_written"] == 1


@pytest.mark.parametrize("keyboard_interrupt", [False, True])
def test_ctrl_c_finalizes_and_disconnects(tmp_path, keyboard_interrupt):
    stop = threading.Event()
    action = KeyboardInterrupt() if keyboard_interrupt else stop.set
    result, rows, client, _ = run_capture(tmp_path, duration=60,
                                         scripts=[[message(), action]], stop=stop)
    assert result == 0 and rows[-1]["reason"] == "ctrl_c"
    assert rows[-1]["monotonic_ns"] < 1_000_000_000
    assert client.disconnect_calls == 1
    assert any(r.get("event") == "disconnected" and r["expected"] for r in rows)


def test_wall_clock_change_does_not_change_monotonic_intervals():
    clock = Clock()
    utc = [STAMP, STAMP - timedelta(hours=1)]
    stream = io.StringIO()
    writer = record.JsonlWriter(stream, clock_ns=clock.now, utc_now=lambda: utc.pop(0))
    writer.emit("event", event="first")
    clock.sleep(0.25)
    writer.emit("event", event="second")
    rows = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert rows[1]["timestamp_utc"] < rows[0]["timestamp_utc"]
    assert rows[1]["monotonic_ns"] - rows[0]["monotonic_ns"] == 250_000_000


def test_timestamp_is_taken_before_payload_encoding(monkeypatch):
    clock = Clock()
    stream = io.StringIO()
    writer = record.JsonlWriter(stream, clock_ns=clock.now, utc_now=lambda: STAMP)
    recorder = record.Recorder(writer, FakeClient(clock))
    original = base64.b64encode

    def slow_encode(payload):
        clock.sleep(0.5)
        return original(payload)

    monkeypatch.setattr(record.base64, "b64encode", slow_encode)
    recorder.on_message(None, None, message())
    assert json.loads(stream.getvalue())["monotonic_ns"] == 0


@pytest.mark.parametrize("failure", ["write", "flush", "short"])
def test_writer_stops_after_disk_error(failure):
    class BrokenStream(io.StringIO):
        def write(self, text):
            if failure == "write":
                raise OSError("disk full with sensitive path")
            if failure == "short":
                return super().write(text[:5])
            return super().write(text)

        def flush(self):
            if failure == "flush":
                raise OSError("disk full")

    stream = BrokenStream()
    writer = record.JsonlWriter(stream)
    with pytest.raises(record.CaptureIOError):
        writer.emit("message")
    before = stream.getvalue()
    with pytest.raises(record.CaptureIOError):
        writer.emit("session_end", status="complete")
    assert stream.getvalue() == before and writer.failed


def test_disk_failure_during_capture_disconnects_without_footer(tmp_path, monkeypatch):
    original_write = record.JsonlWriter.emit

    def fail_message(self, record_type, **fields):
        if record_type == "message":
            self.failed = True
            raise record.CaptureIOError()
        return original_write(self, record_type, **fields)

    monkeypatch.setattr(record.JsonlWriter, "emit", fail_message)
    result, rows, client, errors = run_capture(tmp_path, scripts=[[message()]])
    assert result == 1 and "incompleta" in errors
    assert client.disconnect_calls == 1
    assert all(r["record_type"] != "session_end" for r in rows)


def test_existing_file_is_preserved_without_connecting(tmp_path):
    output = tmp_path / "capture.mqtt.jsonl"
    output.write_bytes(b"original evidence\n")

    def unexpected_client(**kwargs):
        pytest.fail("Must not create a client when the output already exists")

    assert record.capture(output, client_factory=unexpected_client, stderr=io.StringIO()) == 1
    assert output.read_bytes() == b"original evidence\n"


def test_fsync_failure_reports_incomplete_without_success_footer(tmp_path, monkeypatch):
    def fail_sync(fd):
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(record.os, "fsync", fail_sync)
    result, rows, client, errors = run_capture(tmp_path, scripts=[[message()]])
    assert result == 1 and "incompleta" in errors
    assert "sensitive" not in errors
    assert client.disconnect_calls == 1
    assert not any(row["record_type"] == "session_end" for row in rows)


def test_io_error_in_shutdown_still_disconnects(tmp_path, monkeypatch):
    original_emit = record.JsonlWriter.emit

    def fail_shutdown(self, record_type, **fields):
        if fields.get("event") == "disconnect_requested":
            self.failed = True
            raise record.CaptureIOError()
        return original_emit(self, record_type, **fields)

    monkeypatch.setattr(record.JsonlWriter, "emit", fail_shutdown)
    result, rows, client, errors = run_capture(tmp_path, scripts=[[message()]])
    assert result == 1 and "incompleta" in errors
    assert client.disconnect_calls == 1
    assert not any(row["record_type"] == "session_end" for row in rows)


@pytest.mark.parametrize("error", [OSError("private network detail"), RuntimeError("private detail")])
def test_loop_errors_are_recorded_without_free_text(tmp_path, error):
    result, rows, client, errors = run_capture(tmp_path, scripts=[[message(), error]])
    assert result == 1 and rows[-1]["status"] == "incomplete"
    assert any(row.get("event") == "error" for row in rows)
    assert "private" not in json.dumps(rows) + errors
    assert client.disconnect_calls == 1


def test_sessions_have_distinct_ids(tmp_path):
    _, first, _, _ = run_capture(tmp_path / "first", scripts=[[message()]])
    _, second, _, _ = run_capture(tmp_path / "second", scripts=[[message()]])
    assert first[0]["session_id"] != second[0]["session_id"]


@pytest.mark.parametrize("options", [
    {"broker": "mqtt://user:password@host"}, {"broker": "user@host"},
    {"port": 0}, {"port": 65536}, {"duration": 0},
    {"duration": -1}, {"duration": float("nan")}, {"duration": float("inf")},
])
def test_invalid_options_do_not_create_capture(tmp_path, options):
    output = tmp_path / "capture.mqtt.jsonl"
    with pytest.raises(ValueError):
        record.capture(output, **options)
    assert not output.exists()


def test_cli_parameters_and_sigint_handler_restoration(tmp_path, monkeypatch):
    handlers = []
    previous = object()

    def fake_signal(sig, handler):
        assert sig == signal.SIGINT
        handlers.append(handler)
        return previous

    def fake_capture(output, **kwargs):
        assert output == tmp_path / "out.mqtt.jsonl"
        assert (kwargs["broker"], kwargs["port"], kwargs["duration"]) == ("localhost", 1884, 12.5)
        handlers[0](signal.SIGINT, None)
        assert kwargs["stop"].is_set()
        return 0

    monkeypatch.setattr(record.signal, "signal", fake_signal)
    monkeypatch.setattr(record, "capture", fake_capture)
    assert record.main(["--broker", "localhost", "--port", "1884", "--duration", "12.5",
                        "--output", str(tmp_path / "out.mqtt.jsonl")]) == 0
    assert handlers[-1] is previous


def test_standalone_import_does_not_import_backend_or_fastapi():
    result = subprocess.run(
        [sys.executable, "-c", "import sys; import mqtt_capture.record; "
         "assert not any(n == 'fastapi' or n == 'backend' or n.startswith('backend.') "
         "for n in sys.modules)"], cwd=Path(__file__).resolve().parents[1],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
