"""Deterministic P0.3 replay. No backend, hardware or production broker access."""

import argparse
import base64
import binascii
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timedelta
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import threading
import time
import uuid

from .record import FORMAT, SCHEMA_VERSION, TELEMETRY_TOPICS, TOPIC_MODES
from .frames import FRAME_TOPIC, Analyzer, validate as validate_frame, FrameError

REPLAY_QOS = 1  # Uniform delivery class; mixed QoS can overtake QoS-2 handshakes.


class CaptureValidationError(ValueError):
    """No publication is allowed after a preflight validation failure."""


EVENT_FIELDS = {
    "connection_attempt": ("attempt",),
    "reconnection_attempt": ("attempt",),
    "connected": ("connection", "session_present"),
    "reconnected": ("connection", "session_present"),
    "subscription_requested": ("mid",),
    "subscribed": ("mid", "granted_qos"),
    "disconnected": ("reason_code", "expected"),
    "possible_loss": ("cause", "lost_messages"),
    "error": ("stage",),
    "disconnect_requested": (),
}


@dataclass(frozen=True)
class Capture:
    records: tuple
    payloads: dict
    sha256: str
    incomplete: bool
    source_errors: int
    time_basis: str = "mqtt_receive"
    frame_analysis: dict | None = None


def require(condition, message):
    if not condition:
        raise CaptureValidationError(message)


def integer(value, minimum=0, maximum=None):
    return (type(value) is int and value >= minimum
            and (maximum is None or value <= maximum))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Clave JSON duplicada")
        result[key] = value
    return result


def invalid_constant(value):
    raise CaptureValidationError("Constante JSON no finita")


def load_capture(path, *, allow_incomplete=False):
    """Validate the entire input before opening an MQTT connection; never repair it."""
    raw = Path(path).read_bytes()
    from .import_frames import IMPORT_FORMAT, load_import
    try:
        first = json.loads(raw.decode("utf-8").splitlines()[0])
    except (ValueError, IndexError):
        first = None
    if isinstance(first, dict) and first.get("format") == IMPORT_FORMAT:
        return load_import(path)
    records, payloads = [], {}
    declared_topics = ()
    frames = Analyzer()
    previous_ns = -1
    session = None
    try:
        lines = raw.decode("utf-8").splitlines()
        require(bool(lines), "Archivo vacío")
        for line_number, line in enumerate(lines, 1):
            r = json.loads(line, object_pairs_hook=unique_object,
                           parse_constant=invalid_constant)
            require(isinstance(r, dict), "El registro debe ser un objeto")
            require(r.get("format") == FORMAT, "Formato desconocido")
            require(type(r.get("schema_version")) is int
                    and r["schema_version"] == SCHEMA_VERSION, "Versión desconocida")
            require(integer(r.get("sequence")) and r["sequence"] == len(records),
                    "Secuencia interrumpida o fuera de orden")
            require(integer(r.get("monotonic_ns"))
                    and r["monotonic_ns"] >= previous_ns, "Tiempo monotónico inválido")
            previous_ns = r["monotonic_ns"]
            stamp = r.get("timestamp_utc")
            require(isinstance(stamp, str) and stamp.endswith("Z"), "Timestamp UTC inválido")
            require(datetime.fromisoformat(stamp.replace("Z", "+00:00")).utcoffset()
                    == timedelta(0), "Timestamp no UTC")
            require(isinstance(r.get("session_id"), str), "Falta session_id")
            uuid.UUID(r["session_id"])
            if session is None:
                session = r["session_id"]
            require(session == r["session_id"], "Sesiones mezcladas")
            kind = r.get("record_type")
            require(kind in ("session_start", "message", "event", "session_end"),
                    "Tipo de registro desconocido")
            require((len(records) == 0) == (kind == "session_start"), "Cabecera fuera de lugar")
            require(not records or records[-1]["record_type"] != "session_end",
                    "Registros posteriores al cierre")
            if kind == "session_start":
                meta = r.get("metadata")
                require(isinstance(meta, dict), "Metadatos ausentes")
                topics = meta.get("topics")
                require(isinstance(topics, list) and all(isinstance(t, str) for t in topics)
                        and len(topics) == len(set(topics))
                        and any(set(topics) == set(mode) for mode in TOPIC_MODES.values()), "Topics de cabecera no permitidos")
                declared_topics = tuple(topics)
                require(meta.get("payload_encoding") == "base64"
                        and meta.get("time_origin") == "session_start", "Codificación/reloj desconocidos")
            elif kind == "message":
                require(r.get("topic") in declared_topics, "Topic fuera de la telemetría permitida")
                require(integer(r.get("qos"), 0, 2), "QoS inválido")
                require(type(r.get("retain")) is bool and type(r.get("dup")) is bool,
                        "Flags MQTT inválidos")
                require(integer(r.get("mid"), 0, 65535) and integer(r.get("connection"), 1),
                        "Identificadores MQTT inválidos")
                encoded = r.get("payload_base64")
                require(isinstance(encoded, str), "Falta Base64")
                payloads[r["sequence"]] = base64.b64decode(encoded, validate=True)
                require(base64.b64encode(payloads[r["sequence"]]).decode("ascii") == encoded,
                        "Base64 no canónico")
                if r["topic"] == FRAME_TOPIC:
                    r["frame_validation"] = frames.feed(payloads[r["sequence"]], retain=r["retain"])
            elif kind == "event":
                event = r.get("event")
                require(isinstance(event, str) and event in EVENT_FIELDS, "Evento desconocido")
                require(all(key in r for key in EVENT_FIELDS[event]), "Evento incompleto")
                for key in ("attempt", "connection", "mid", "reason_code"):
                    if key in r:
                        require(integer(r[key]), "Código de evento inválido")
                for key in ("expected", "session_present"):
                    if key in r:
                        require(type(r[key]) is bool, "Flag de evento inválido")
                if event == "subscribed":
                    grants = r["granted_qos"]
                    require(isinstance(grants, list) and len(grants) == len(declared_topics)
                            and all(integer(q, 0, 2) for q in grants), "SUBACK inválido")
                if event in ("error", "possible_loss"):
                    require(isinstance(r.get("stage" if event == "error" else "cause"), str),
                            "Detalle de evento inválido")
            elif kind == "session_end":
                require(r.get("finalized") is True and r.get("status") in ("complete", "incomplete"),
                        "Cierre inválido")
                require(isinstance(r.get("reason"), str), "Motivo de cierre inválido")
                for key in ("messages_received", "messages_written", "ignored_messages",
                            "errors", "unexpected_disconnects", "connections"):
                    require(integer(r.get(key)), "Contador de cierre inválido")
                require(r["messages_written"] == len(payloads)
                        and r["messages_received"] >= r["messages_written"], "Recuento de cierre incoherente")
            records.append(r)
    except (ValueError, TypeError, KeyError, binascii.Error, OverflowError) as error:
        # Do not echo arbitrary input (it may contain credentials).
        detail = str(error) if isinstance(error, CaptureValidationError) else "JSON/campos inválidos"
        raise CaptureValidationError(f"Línea {len(records) + 1}: {detail}") from None
    ended = records[-1]["record_type"] == "session_end"
    source_errors = sum(r.get("event") == "error" for r in records)
    gaps = any(r.get("event") == "possible_loss"
               or (r.get("event") == "disconnected" and r.get("expected") is False)
               for r in records)
    incomplete = not ended or source_errors > 0 or gaps
    if ended:
        footer = records[-1]
        require(footer["errors"] >= source_errors, "Recuento de errores incoherente")
        incomplete |= (footer["status"] == "incomplete" or footer["errors"] > 0
                       or footer["unexpected_disconnects"] > 0
                       or footer["messages_received"] != footer["messages_written"]
                       or footer["reason"] not in ("duration", "ctrl_c"))
    require(allow_incomplete or not incomplete,
            "Captura incompleta/con incidencias: inspeccionar y usar --allow-incomplete explícitamente")
    return Capture(tuple(records), payloads, hashlib.sha256(raw).hexdigest(),
                   bool(incomplete), source_errors, "mqtt_receive",
                   frames.summary() if FRAME_TOPIC in declared_topics else None)


class RealClock:
    now_ns = staticmethod(time.monotonic_ns)

    def wait_until(self, deadline_ns, stop):
        while not stop.is_set():
            remaining = deadline_ns - self.now_ns()
            if remaining <= 0:
                return
            stop.wait(min(remaining / 1_000_000_000, 0.1))


class VirtualClock:
    def __init__(self):
        self.ns = 0

    def now_ns(self):
        return self.ns

    def wait_until(self, deadline_ns, stop):
        if not stop.is_set():
            self.ns = max(self.ns, deadline_ns)


def speed_ratio(value):
    try:
        result = Fraction(str(value))
        if result <= 0:
            raise ValueError()
        return result
    except (ValueError, ZeroDivisionError):
        raise ValueError("La velocidad debe ser positiva y finita") from None


def normalized_event(record, scheduled_ns, payload=None, *, allow_unknown_retain=False, include_invalid_frames=False):
    kind = record["record_type"]
    result = {
        "format": "smartspace.mqtt.replay.event", "schema_version": 1,
        "mode": "replay", "source_session_id": record["session_id"],
        "sequence": record["sequence"], "record_type": kind,
        "source_timestamp_utc": record["timestamp_utc"],
        "source_monotonic_ns": record["monotonic_ns"], "scheduled_ns": scheduled_ns,
        "action": "observe",
    }
    if kind == "message":
        result.update(topic=record["topic"], payload_base64=base64.b64encode(payload).decode("ascii"),
                      qos=REPLAY_QOS, original_qos=record["qos"], original_retain=record["retain"],
                      original_dup=record["dup"], original_connection=record["connection"],
                      publish_retain=False,
                      action="omit_retained" if record["retain"] else "publish")
    elif kind == "event":
        keys = set(EVENT_FIELDS[record["event"]]) | {
            "reason_code", "reason_codes", "mid", "error_type"}
        result.update(event=record["event"], scope="recorder_to_broker",
                      details={k: record[k] for k in sorted(keys) if k in record})
    elif kind == "session_end":
        result.update(source_status=record["status"], source_reason=record["reason"])
    if record.get("timing_basis") == "esp_processing_derived":
        result.update(timing_basis="esp_processing_derived", source_completeness="unknown")
        if kind == "message":
            result.update(import_line=record["import_line"], timing_boundary=record["timing_boundary"])
            if not allow_unknown_retain:
                result["action"] = "omit_unknown_retain"
    if kind == "message" and record["topic"] == FRAME_TOPIC:
        result["frame_validation"] = record["frame_validation"]
        try:
            result["frame"] = validate_frame(payload)
            result["frame_valid"] = True
        except FrameError as error:
            result.update(frame_valid=False, frame_error=str(error))
            if not include_invalid_frames and result["action"] == "publish":
                result["action"] = "omit_invalid_frame"
    return result


def replay(capture, *, publish=None, speed=1, clock=None, emit=lambda event: None,
           check=lambda: None, stop=None, allow_unknown_retain=False, include_invalid_frames=False):
    """Absolute deadlines prevent cumulative drift. Ties follow file sequence.

    publish(topic, bytes, qos=..., retain=False) is injectable for offline tests.
    Normalized events describe replay intent, not backend person/state normalization.
    """
    ratio = speed_ratio(speed)
    clock = clock if clock is not None else RealClock()
    stop = stop if stop is not None else threading.Event()
    summary = dict(mode="replay", dry_run=publish is None, records_read=len(capture.records),
                   messages_read=len(capture.payloads), published=0, planned=0,
                   omitted_retained=0, not_replayed=len(capture.payloads),
                   events_observed=0, errors=0, source_errors=capture.source_errors,
                   source_incomplete=capture.incomplete, status="complete",
                   source_sha256=capture.sha256, normalized_sha256=None, publish_qos=REPLAY_QOS)
    if capture.frame_analysis is not None:
        summary.update(frame_analysis=capture.frame_analysis, timing_basis=capture.time_basis,
                       omitted_invalid_frames=0, omitted_unknown_retain=0)
    if capture.time_basis == "esp_processing_derived":
        summary.update(source_completeness="unknown",
                       original_sha256=capture.records[0]["metadata"]["source_sha256"])
    digest = hashlib.sha256()
    start = clock.now_ns()
    try:
        for r in capture.records:
            deadline = r.get("replay_offset_ns", r["monotonic_ns"]) * ratio.denominator // ratio.numerator
            clock.wait_until(start + deadline, stop)
            if stop.is_set():
                summary["status"] = "interrupted"
                break
            check()
            payload = capture.payloads.get(r["sequence"])
            event = normalized_event(r, deadline, payload, allow_unknown_retain=allow_unknown_retain,
                                     include_invalid_frames=include_invalid_frames)
            if event["action"] == "publish":
                if publish is not None:
                    publish(r["topic"], payload, qos=REPLAY_QOS, retain=False)
                    summary["published"] += 1
                else:
                    summary["planned"] += 1
                summary["not_replayed"] -= 1
            elif event["action"] == "omit_retained":
                summary["omitted_retained"] += 1
                summary["not_replayed"] -= 1
            elif event["action"] in ("omit_invalid_frame", "omit_unknown_retain"):
                key = "omitted_invalid_frames" if event["action"] == "omit_invalid_frame" else "omitted_unknown_retain"
                summary[key] += 1
                summary["not_replayed"] -= 1
            elif r["record_type"] == "event":
                summary["events_observed"] += 1
            emit(event)
            digest.update((json.dumps(event, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True) + "\n").encode("utf-8"))
    except KeyboardInterrupt:
        summary["status"] = "interrupted"
    except Exception as error:
        summary.update(status="error", errors=1, error_type=type(error).__name__)
    summary["normalized_sha256"] = digest.hexdigest()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--speed", default="1", help="1=real; 10=10x; 0.5=mitad")
    parser.add_argument("--dry-run", action="store_true", help="No abrir ningún broker")
    parser.add_argument("--virtual-clock", action="store_true", help="Solo con --dry-run")
    parser.add_argument("--allow-incomplete", action="store_true")
    parser.add_argument("--events-output", type=Path, help="JSONL derivado nuevo, nunca sobrescribir")
    parser.add_argument("--mosquitto", type=Path, help="Ejecutable local; arranca una instancia temporal aislada")
    parser.add_argument("--allow-unknown-retain", action="store_true", help="Permitir publicación de importados sin flag retain conocido")
    parser.add_argument("--include-invalid-frames", action="store_true", help="Reproducir bytes de informes inválidos para diagnóstico aislado")
    args = parser.parse_args(argv)
    summary = dict(mode="replay", dry_run=args.dry_run, status="error", errors=0,
                   records_read=0, messages_read=0, published=0, planned=0,
                   omitted_retained=0, not_replayed=0)
    try:
        try:
            speed_ratio(args.speed)
        except ValueError as error:
            parser.error(str(error))
        if args.virtual_clock and not args.dry_run:
            parser.error("--virtual-clock requiere --dry-run")
        if not args.dry_run and not args.mosquitto:
            parser.error("Indica --mosquitto o --dry-run; no se aceptan brokers externos")
        capture = load_capture(args.input, allow_incomplete=args.allow_incomplete)
        summary.update(records_read=len(capture.records), messages_read=len(capture.payloads),
                       not_replayed=len(capture.payloads), source_sha256=capture.sha256,
                       source_incomplete=capture.incomplete, source_errors=capture.source_errors)
        with ExitStack() as stack:
            emit = lambda event: None
            if args.events_output:
                stream = stack.enter_context(args.events_output.open("x", encoding="utf-8", newline="\n"))

                def emit(event):
                    stream.write(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n")
                    stream.flush()

            publish = None
            check = lambda: None
            if not args.dry_run:
                from .isolated_broker import IsolatedBroker, MqttPublisher
                broker = stack.enter_context(IsolatedBroker(args.mosquitto))
                publisher = stack.enter_context(MqttPublisher(broker))
                publish = publisher.publish
                check = publisher.check
            summary = replay(capture, publish=publish, speed=args.speed, emit=emit,
                             check=check,
                             clock=VirtualClock() if args.virtual_clock else RealClock(),
                             allow_unknown_retain=args.allow_unknown_retain,
                             include_invalid_frames=args.include_invalid_frames)
        print(json.dumps(summary, sort_keys=True))
        return 130 if summary["status"] == "interrupted" else (1 if summary["errors"] else 0)
    except KeyboardInterrupt:
        summary.update(status="interrupted")
        print(json.dumps(summary, sort_keys=True))
        return 130
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        # Input and subprocess error strings can contain secrets: only safe validation text.
        if isinstance(error, CaptureValidationError):
            print(str(error), file=sys.stderr)
        summary.update(status="error", errors=summary["errors"] + 1, error_type=type(error).__name__)
        print(json.dumps(summary, sort_keys=True))
        return 1


if __name__ == "__main__":
    sys.exit(main())
