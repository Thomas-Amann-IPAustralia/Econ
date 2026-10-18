"""Stage `sweep`: a security sweep of every raw PDF before anything is parsed.

Two checks per document:
- active content in the file itself (JavaScript, launch actions, embedded files);
- the text checks in econ.textcheck over the PDF's text layer.

High-severity findings quarantine the document and fail the run, unless config/allowlist.yaml (owner-only)
lists that exact finding. The parse stage re-checks the extracted text, which is what enters the KB.
"""

from __future__ import annotations

import re
import zlib

import yaml

from econ import config, textcheck
from econ.manifest import Run, StageError, require_upstream, write_json_atomic

ACTIVE = {
    "javascript": re.compile(rb"/(JavaScript|JS)\b"),
    "launch_action": re.compile(rb"/Launch\b"),
    "embedded_file": re.compile(rb"/EmbeddedFiles?\b"),
    "submit_form": re.compile(rb"/SubmitForm\b"),
}
_STREAM = re.compile(rb"(<<(?:(?!>>\s*stream).)*?>>)\s*stream\r?\n(.*?)\r?\nendstream", re.S)


def object_text(blob: bytes) -> bytes:
    """The PDF's object dictionaries, where actions live: everything outside streams, plus the contents
    of compressed object streams. Page content, images and fonts are left out, because a raw-byte search
    of them matched '/JS' in compressed binary in 4 of 24 documents (D-002)."""
    parts, last = [], 0
    for m in _STREAM.finditer(blob):
        parts.append(blob[last : m.start()])
        parts.append(m.group(1))
        if re.search(rb"/Type\s*/ObjStm", m.group(1)):
            data = m.group(2)
            try:
                data = zlib.decompress(data) if re.search(rb"/FlateDecode", m.group(1)) else data
            except zlib.error:
                data = b""
            parts.append(data)
        last = m.end()
    parts.append(blob[last:])
    return b"\n".join(parts)


def active_content(blob: bytes) -> list[dict]:
    text = object_text(blob)
    return [
        {"rule": name, "severity": "high", "excerpt": m.group(0).decode("latin-1")}
        for name, rx in ACTIVE.items()
        if (m := rx.search(text))
    ]


def allowlist() -> list[dict]:
    p = config.CONFIG_DIR / "allowlist.yaml"
    if not p.exists():
        return []
    return (yaml.safe_load(p.read_text()) or {}).get("entries", []) or []


def _allowed(doc_id: str, f: dict, entries: list[dict]) -> bool:
    return any(
        e.get("doc_id") == doc_id and e.get("rule") == f["rule"] and e.get("excerpt") in f["excerpt"]
        for e in entries
    )


def sweep(run: Run) -> dict:
    import pypdfium2 as pdfium  # build extra
    import pypdfium2.raw as pdfium_c

    run.upstream["fetch"] = require_upstream("fetch")["run_id"]
    raw = config.path(config.pipeline().paths.raw)
    entries = allowlist()
    report: dict[str, dict] = {}
    quarantined = []
    for doc in sorted(config.sources().documents, key=lambda d: d.doc_id):
        p = raw / f"{doc.doc_id}.pdf"
        blob = p.read_bytes()
        findings = active_content(blob)
        pdf = pdfium.PdfDocument(blob)
        js_actions = pdfium_c.FPDFDoc_GetJavaScriptActionCount(pdf.raw)
        if js_actions > 0:
            findings.append(
                {
                    "rule": "javascript",
                    "severity": "high",
                    "excerpt": f"{js_actions} document-level action(s)",
                }
            )
        chars = []
        for i in range(len(pdf)):
            text = pdf[i].get_textpage().get_text_range()
            chars.append(len(text.strip()))
            for f in textcheck.scan(text):
                findings.append({**f.as_dict(), "page": i + 1})
        for f in findings:
            f["allowlisted"] = f["severity"] == "high" and _allowed(doc.doc_id, f, entries)
        blocking = [f for f in findings if f["severity"] == "high" and not f["allowlisted"]]
        if blocking:
            quarantined.append(doc.doc_id)
        report[doc.doc_id] = {
            "pages": len(pdf),
            "text_layer_chars": sum(chars),
            "image_only_pages": sum(c < config.pipeline().parse.ocr_min_chars_per_page for c in chars),
            "findings": findings,
            "quarantined": bool(blocking),
        }
        run.add_input(p)

    out = config.path(config.pipeline().paths.library) / "sweep.json"
    write_json_atomic(out, report)
    run.add_output(out)
    run.counts.update(
        documents=len(report),
        findings=sum(len(r["findings"]) for r in report.values()),
        high=sum(f["severity"] == "high" for r in report.values() for f in r["findings"]),
        quarantined=len(quarantined),
    )
    if quarantined:
        raise StageError(
            f"{len(quarantined)} document(s) quarantined by high-severity findings; the owner reviews "
            "them and may add allowlist entries",
            item=quarantined[0],
            report=str(out.relative_to(config.ROOT)),
        )
    return report
