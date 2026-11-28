"""Lossless archive/import of mosquitto_sub payload lines, NOT a reception capture."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import uuid

from .frames import FRAME_TOPIC, Analyzer, FrameError, validate

IMPORT_FORMAT = "smartspace.mqtt.payload_import"


def payload_from_line(line, index):
    # mosquitto_sub adds a line terminator; PowerShell may add a UTF-8 BOM.
    payload = line[:-1] if line.endswith(b"\n") else line
    if payload.endswith(b"\r"):
        payload = payload[:-1]
    if index == 0 and payload.startswith(b"\xef\xbb\xbf"):
        payload = payload[3:]
    return payload


def import_file(source, output, *, evidence_kind="unspecified"):
    if evidence_kind not in ("physical_capture", "synthetic", "unspecified"):
        raise ValueError("evidence_kind inválido")
    raw = Path(source).read_bytes()
    if not raw or raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise ValueError("Se requiere JSONL UTF-8 no vacío; no se transcodifica el original")
    header = dict(format=IMPORT_FORMAT, schema_version=1, record_type="import_start",
                  source_sha256=hashlib.sha256(raw).hexdigest(), evidence_kind=evidence_kind,
                  topic=FRAME_TOPIC, topic_origin="declared_by_importer",
                  reception_metadata="unavailable", source_completeness="unknown",
                  timing_policy="esp_rx_us_with_collapsed_unknown_boundaries")
    lines = raw.splitlines(keepends=True)
    with Path(output).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(header) + "\n")
        for index, line in enumerate(lines, 1):
            stream.write(json.dumps(dict(line=index,
                source_line_base64=base64.b64encode(line).decode("ascii"))) + "\n")
        stream.write(json.dumps(dict(record_type="import_end", lines=len(lines))) + "\n")
    return header


def load_import(path):
    from .replay import Capture, CaptureValidationError, unique_object, invalid_constant, require
    raw = Path(path).read_bytes()
    try:
        rows = [json.loads(line, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                for line in raw.decode("utf-8").splitlines()]
        h, end = rows[0], rows[-1]
        require(h.get("format") == IMPORT_FORMAT and type(h.get("schema_version")) is int
                and h["schema_version"] == 1, "Versión de importación inválida")
        require(h.get("record_type") == "import_start" and h.get("topic") == FRAME_TOPIC
                and h.get("topic_origin") == "declared_by_importer"
                and h.get("reception_metadata") == "unavailable"
                and h.get("source_completeness") == "unknown"
                and h.get("timing_policy") == "esp_rx_us_with_collapsed_unknown_boundaries"
                and h.get("evidence_kind") in ("physical_capture", "synthetic", "unspecified"),
                "Proveniencia de importación inválida")
        require(end == dict(record_type="import_end", lines=len(rows)-2), "Importación truncada")
        lines = []
        for index, row in enumerate(rows[1:-1], 1):
            require(set(row) == {"line", "source_line_base64"} and type(row["line"]) is int
                    and row["line"] == index, "Orden de líneas inválido")
            line = base64.b64decode(row["source_line_base64"], validate=True)
            require(base64.b64encode(line).decode("ascii") == row["source_line_base64"], "Base64 no canónico")
            lines.append(line)
        source = b"".join(lines)
        require(bool(source) and source.splitlines(keepends=True) == lines, "Líneas originales incoherentes")
        require(hashlib.sha256(source).hexdigest() == h["source_sha256"], "Hash de original no coincide")
        session = str(uuid.uuid5(uuid.NAMESPACE_URL, IMPORT_FORMAT + h["source_sha256"]))
        base = dict(session_id=session, timestamp_utc=None, monotonic_ns=None,
                    timing_basis="esp_processing_derived", source_completeness="unknown")
        records = [dict(base, sequence=0, record_type="session_start", replay_offset_ns=0, metadata=h)]
        payloads = {}
        analysis = Analyzer()
        offset = 0
        previous = None
        for index, line in enumerate(lines):
            payload = payload_from_line(line, index)
            result = analysis.feed(payload, retain=None)
            boundary = "unknown_invalid_report"
            if result["valid"]:
                report = validate(payload)
                boundary = "origin" if previous is None else "collapsed_unknown_boundary"
                if previous is not None and report["boot_id"] == previous["boot_id"]:
                    delta = report["rx_us"] - previous["rx_us"]
                    if delta >= 0:
                        offset += delta * 1000
                        boundary = "esp_interval"
                previous = report
            sequence = len(records)
            payloads[sequence] = payload
            records.append(dict(base, sequence=sequence, record_type="message", replay_offset_ns=offset,
                topic=FRAME_TOPIC, payload_base64=base64.b64encode(payload).decode("ascii"),
                qos=None, retain=None, dup=None, mid=None, connection=None,
                import_line=index+1, timing_boundary=boundary, frame_validation=result))
        records.append(dict(base, sequence=len(records), record_type="session_end",
                            replay_offset_ns=offset, status="imported", reason="import_end"))
        return Capture(tuple(records), payloads, hashlib.sha256(raw).hexdigest(), False, 0,
                       "esp_processing_derived", analysis.summary())
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        if isinstance(error, CaptureValidationError):
            raise
        raise CaptureValidationError("Importación inválida o truncada") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence-kind", choices=("physical_capture", "synthetic", "unspecified"), default="unspecified")
    args = parser.parse_args(argv)
    try:
        metadata = import_file(args.input, args.output, evidence_kind=args.evidence_kind)
        capture = load_import(args.output)
        print(json.dumps(dict(metadata, analysis=capture.frame_analysis), sort_keys=True))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps(dict(status="error", error_type=type(error).__name__)))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
