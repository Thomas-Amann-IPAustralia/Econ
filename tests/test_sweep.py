"""Sweep rules. The first real run quarantined 4 of 24 PDFs on '/JS' bytes inside compressed streams (D-002)."""

import zlib

from econ.ingest.sweep import active_content


def _pdf(*objs: bytes) -> bytes:
    return b"%PDF-1.7\n" + b"\n".join(objs) + b"\n%%EOF"


def test_js_bytes_inside_a_content_stream_are_ignored():
    blob = _pdf(
        b"1 0 obj << /Length 20 /Filter /FlateDecode >>\nstream\n\x87\x14/JS\x88\xff\x00junk\nendstream\nendobj"
    )
    assert active_content(blob) == []


def test_js_action_in_an_object_dictionary_is_found():
    blob = _pdf(b"2 0 obj << /S /JavaScript /JS (app.alert(1)) >>\nendobj")
    assert {f["rule"] for f in active_content(blob)} == {"javascript"}


def test_js_action_inside_a_compressed_object_stream_is_found():
    inner = zlib.compress(b"3 0 << /S /JavaScript /JS (app.alert(1)) >>")
    blob = _pdf(
        b"4 0 obj << /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode >>\nstream\n"
        + inner
        + b"\nendstream\nendobj"
    )
    assert {f["rule"] for f in active_content(blob)} == {"javascript"}


def test_launch_and_embedded_files_are_found():
    blob = _pdf(
        b"5 0 obj << /S /Launch /F (cmd.exe) >>\nendobj", b"6 0 obj << /EmbeddedFiles 7 0 R >>\nendobj"
    )
    assert {f["rule"] for f in active_content(blob)} == {"launch_action", "embedded_file"}
