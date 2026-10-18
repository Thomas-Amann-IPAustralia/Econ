"""Stage `parse`: PDFs to layout elements with page and box provenance, using Docling.

Each document becomes library/elements/<doc_id>.jsonl: one row per body element in reading order, with
its label, text, page and bounding box (PDF points, top-left origin). Page furniture (running headers,
footers, page numbers), the table of contents and figure interiors are left out; captions are kept.
Documents whose text layer is empty are OCR'd at a higher render scale (D-002).

The Docling result per document is cached in data/parsed/ under the input's hash, so a run can resume.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from econ import config, textcheck
from econ.manifest import Run, StageError, require_upstream, sha256_file, write_json_atomic, write_text_atomic

KEEP = {
    "title",
    "section_header",
    "text",
    "paragraph",
    "list_item",
    "caption",
    "footnote",
    "table",
    "formula",
    "code",
    "reference",
}
NUMBERED = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")

_converters: dict = {}


def _converter(ocr: bool):
    if ocr in _converters:
        return _converters[ocr]
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    cfg = config.pipeline().parse
    opts = PdfPipelineOptions(
        do_ocr=ocr,
        do_table_structure=cfg.table_structure,
        accelerator_options=AcceleratorOptions(num_threads=cfg.threads, device="cpu"),
    )
    if ocr:
        opts.images_scale = cfg.ocr_scale
        opts.ocr_options = RapidOcrOptions(force_full_page_ocr=True)
    conv = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
    _converters[ocr] = conv
    return conv


def heading_level(text: str, docling_level: int | None) -> int:
    """Numbered headings ('2.1 Data') take their depth from the number; others keep Docling's level."""
    m = NUMBERED.match(text)
    if m:
        return min(m.group(1).count(".") + 1, 4)
    return max(1, int(docling_level or 1))


def elements_from_docling(doc, doc_id: str, ocr: bool) -> tuple[list[dict], dict]:
    from docling_core.types.doc import TableItem

    rows: list[dict] = []
    pages = {
        int(no): {"width": round(p.size.width, 2), "height": round(p.size.height, 2)}
        for no, p in doc.pages.items()
    }
    for item, _level in doc.iterate_items():
        label = str(getattr(item, "label", "")).split(".")[-1].lower()
        if label not in KEEP or not getattr(item, "prov", None):
            continue
        if isinstance(item, TableItem):
            text = item.export_to_markdown(doc=doc).strip()
        else:
            text = (getattr(item, "text", "") or "").strip()
        if not text:
            continue
        # Docling's table markdown already starts with its caption; drop the separate caption element.
        if label == "caption" and rows and rows[-1]["label"] == "table" and text in rows[-1]["text"]:
            continue
        boxes = []
        for prov in item.prov:
            h = pages[prov.page_no]["height"]
            bb = prov.bbox.to_top_left_origin(page_height=h)
            boxes.append(
                {
                    "page": prov.page_no,
                    "bbox": [round(bb.l, 1), round(bb.t, 1), round(bb.r, 1), round(bb.b, 1)],
                }
            )
        row = {
            "doc_id": doc_id,
            "seq": len(rows),
            "label": label,
            "text": text,
            "page": boxes[0]["page"],
            "boxes": boxes,
            "ocr": ocr,
        }
        if label in ("section_header", "title"):
            row["level"] = 0 if label == "title" else heading_level(text, getattr(item, "level", None))
        rows.append(row)
    return rows, pages


def _parse_one(args: tuple[str, str, bool, str]) -> tuple[str, dict]:
    doc_id, pdf_path, ocr, cache_path = args
    started = time.time()
    res = _converter(ocr).convert(pdf_path)
    payload = res.document.export_to_dict()
    write_text_atomic(Path(cache_path), json.dumps(payload))
    return doc_id, {"seconds": round(time.time() - started, 1), "status": str(res.status)}


def parse(run: Run, *, workers: int = 1, only: list[str] | None = None) -> None:
    from docling_core.types.doc import DoclingDocument

    sweep_m = require_upstream("sweep")
    run.upstream["sweep"] = sweep_m["run_id"]
    lib = config.path(config.pipeline().paths.library)
    sweep_report = json.loads((lib / "sweep.json").read_text())
    raw = config.path(config.pipeline().paths.raw)
    cache = config.path("data/parsed")
    cache.mkdir(parents=True, exist_ok=True)
    cfg = config.pipeline().parse

    docs = sorted(config.sources().documents, key=lambda d: d.doc_id)
    if only:
        docs = [d for d in docs if d.doc_id in only]
    jobs, plan = [], {}
    for d in docs:
        pdf = raw / f"{d.doc_id}.pdf"
        digest = sha256_file(pdf)
        info = sweep_report[d.doc_id]
        if info["quarantined"]:
            raise StageError("document is quarantined by the sweep", item=d.doc_id)
        ocr = info["image_only_pages"] >= cfg.ocr_page_share * info["pages"]
        cpath = cache / f"{d.doc_id}.{digest[:16]}.{'ocr' if ocr else 'text'}.json"
        plan[d.doc_id] = (pdf, cpath, ocr)
        run.add_input(pdf)
        if not cpath.exists():
            jobs.append((d.doc_id, str(pdf), ocr, str(cpath)))

    timings = {}
    # OCR documents last: they are the slowest, and a failure there shouldn't hold up the rest.
    jobs.sort(key=lambda j: (j[2], j[0]))
    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for doc_id, info in pool.map(_parse_one, jobs):
                timings[doc_id] = info
                print(f"parsed {doc_id} in {info['seconds']}s", flush=True)
    else:
        for job in jobs:
            doc_id, info = _parse_one(job)
            timings[doc_id] = info
            print(f"parsed {doc_id} in {info['seconds']}s", flush=True)

    out_dir = lib / "elements"
    out_dir.mkdir(parents=True, exist_ok=True)
    catalogue = {}
    n_el, findings = 0, []
    for d in docs:
        pdf, cpath, ocr = plan[d.doc_id]
        ddoc = DoclingDocument.model_validate(json.loads(cpath.read_text()))
        rows, pages = elements_from_docling(ddoc, d.doc_id, ocr)
        if not rows:
            raise StageError("no body text extracted", item=d.doc_id)
        for r in rows:
            for f in textcheck.scan(r["text"]):
                if f.severity == "high":
                    findings.append({"doc_id": d.doc_id, "seq": r["seq"], **f.as_dict()})
        body = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
        out = out_dir / f"{d.doc_id}.jsonl"
        write_text_atomic(out, body)
        run.add_output(out)
        labels = {}
        for r in rows:
            labels[r["label"]] = labels.get(r["label"], 0) + 1
        body_text = " ".join(r["text"] for r in rows)
        licence = (
            "CC BY 4.0" if re.search(r"Creative Commons Attribution 4\.0|CC BY 4\.0", body_text) else None
        )
        if licence is None:
            run.warn(f"{d.doc_id}: no licence statement found in the extracted text")
        catalogue[d.doc_id] = {
            "licence": licence,
            "pages": pages,
            "page_count": len(pages),
            "ocr": ocr,
            "elements": len(rows),
            "labels": dict(sorted(labels.items())),
            "source_sha256": sha256_file(pdf),
        }
        n_el += len(rows)

    out = lib / "parse.json"
    write_json_atomic(out, catalogue)
    run.add_output(out)
    run.counts.update(
        documents=len(docs), parsed_now=len(timings), elements=n_el, text_findings=len(findings)
    )
    run.params["timings"] = timings
    if findings:
        run.params["findings"] = findings[:50]
        raise StageError(
            f"{len(findings)} high-severity text finding(s) in extracted text",
            item=f"{findings[0]['doc_id']}#{findings[0]['seq']}",
        )
