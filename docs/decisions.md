# Decision log

Append-only. Each entry says whose decision it was. A correction is a new entry that names the one it
corrects. Method: docs/sop-agent-construction-v2.md.

---

## D-001 — The stack: Python 3.12 with uv, typer, pydantic config, numpy search (2026-10-18)

**Context.** The owner asked for a RAG chatbot over the `econ-knowledge` R2 bucket (EU jurisdiction): 24
PDFs, 1,099 pages, published by IP Australia between 2014 and 2026. Its purpose is exploratory research
for IP Australia's strategic direction; transparency and traceability matter most. The front end must be
on GitHub Pages; the owner has a free Render account. No Gemini, OpenAI or Langfuse keys yet, so
benchmarks that need a model come later.

**Decision (Claude, within the agreed scope).**
- One package, `econ`, under `src/`, with a typer CLI named `econ`. Python 3.12: Docling has no 3.13
  wheels for one of its dependencies.
- Config in `config/*.yaml`, validated by pydantic with unknown keys as errors: `sources.yaml` (the corpus
  registry), `pipeline.yaml` (parse, chunking, embedding, retrieval), `service.yaml` (the API).
- Three dependency sets, so each host installs only what it runs: the core (the Render API: FastAPI,
  numpy, httpx, pydantic, snowballstemmer), `embedder` (onnxruntime, tokenizers: Cloud Run) and `build`
  (Docling, torch on the CPU index, sentence-transformers, boto3: this session and CI-less builds).
- Keyword search is BM25 in plain numpy (term-major weights, precomputed), so the Render instance needs no
  search engine and no scipy.
- Manifests for every stage run (`manifests/<command>/<run_id>.json`), failed runs included; stages fail
  loudly with exit code 2.
- The SOP's evidence and record-keeping rules apply. Langfuse tracing is deferred until the owner has
  keys; until then every answer is one JSON line in Render's log (`logging.record_questions`).

**Spend:** $0.

---

## D-002 — Parsing: Docling with page and box provenance; OCR for two scanned reports; the sweep reads PDF objects, not bytes (2026-10-18)

**Context.** Traceability needs every passage tied to its page and position. The reports are designed
documents (sidebars, charts, tables). Two, the 2018 and 2021 IP Reports, have no text layer at all (0
characters on every page): their text is outlined vector paths.

**Decision (Claude).**
- **Docling** (MIT) parses each PDF into layout elements in reading order: headings, text, list items,
  captions, footnotes and tables (as Markdown). Each element keeps its page and bounding box, which the
  UI draws over the page. Running headers and footers, page numbers, the table of contents and the text
  inside figures are dropped; captions are kept. A table's separate caption element is dropped, since
  Docling's table Markdown already starts with it.
- **OCR** runs only on documents where at least half the pages have under 100 text-layer characters:
  exactly the two scanned reports. RapidOCR on full pages at render scale 2.0. A probe at the default
  scale (1.0) garbled line starts ("Win ad h nh an anng 2o d"); at 2.0 the same page read cleanly, with
  one footnote marker misread ("?" for "7").
- Heading levels: numbered headings ("2.1 Data") take their depth from the number; others keep
  Docling's level, which is almost always 1. Section paths are therefore shallow: usually the nearest
  heading.
- Probe speed on this session's 4 vCPUs (with AMX): about 5 s a page on one worker. The full parse runs
  as two workers of two threads.

**The security sweep, and a rule fixed on its first real run.** The sweep checks each raw PDF for active
content (JavaScript, launch actions, embedded files, form submission) and runs the text checks
(`econ.textcheck`) over every page's text layer. Its first run quarantined 4 of 24 documents for
JavaScript. All four were false positives: the regex matched the bytes `/JS` inside compressed binary
streams (about 40% printable bytes around each match), and pdfium reports no document-level JavaScript
in any of them. The rule now reads only the PDF's object dictionaries, including those inside compressed
object streams, and leaves out page content, images and fonts; pdfium's count of document-level
JavaScript actions is a second signal. Regression tests: `tests/test_sweep.py`. The second run passed: no
high-severity findings, and 34 low ones (contact email addresses printed in the publications).

**Licences.** 17 documents state "© Commonwealth of Australia, CC BY 4.0" in their first pages; the parse
stage records each document's licence from its extracted text and warns when none is found.

**Spend:** $0.

---

## D-003 — Hosting: GitHub Pages for the front end, Render for the API, Google Cloud Run for the embedding model (owner: Cloud Run for embeddings; the rest settled in the build) (2026-10-18)

**Context.** The owner set GitHub Pages for the front end and offered a free Render account, accepting a
cold start but preferring a shorter one. Mid-build, the owner asked for Google Cloud Run to run the
embedding model. A free Render instance has 512 MB and 0.1 CPU and sleeps after 15 idle minutes; waking
takes about a minute (render.com/docs/free).

**Decision.**
- **Cloud Run (owner's decision)** serves the embedding model: one ONNX model behind `POST /embed`
  (`econ.embedder`), with the model baked into the image at a pinned revision and a checked hash, scale to
  zero, startup CPU boost, at most 2 instances. A shared bearer token guards it. The index is embedded with
  the same ONNX code path, so a query and a chunk go through identical code.
- **Render** runs the API (`econ.service.app`): BM25 and the vector search over the committed index (a few
  MB in numpy), the calls to the embedder and the answer model, the answer check, and the stream of events
  the page renders. It loads no model, so it boots fast and fits the free instance.
- **GitHub Pages** serves the static front end, the catalogue, and the PDFs (copied from R2 at deploy time
  when the R2 secrets are set; never committed).
- **Cold start, as the user sees it.** The page calls `/api/health` the moment it opens, so Render starts
  waking while the user types; Render's first act on waking is to wake Cloud Run. The page shows a status
  chip with a running timer. The answer streams in stages, so the evidence appears before the model has
  written anything. An optional workflow (`keep-warm.yml`, off by default) pings the API every 10 minutes
  in Canberra business hours.
- **Degradation is visible, not silent.** If the embedder is down or slow, search runs on keywords alone
  and the trail says so. Without a model key, the service runs in evidence-only mode.

**What Cloud Run changes for the embedder choice.** Without it, the embedder would have had to fit
Render's 512 MB beside the API, which ruled out anything much over 150M parameters. On Cloud Run, size is
a question of cold-start time and CPU seconds, so the measurement (D-004) includes four models of 335M to
600M parameters, and the rule prefers the smallest model within the tie margin.

**Not verified:** nothing here has been deployed. This session has no GCP credentials and no Render API
key. `docs/deploy.md` gives the owner's steps.

**Spend:** $0.
