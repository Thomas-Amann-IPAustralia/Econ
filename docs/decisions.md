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

---

## D-004 — The knowledge base and the silver test set: 8,601 elements, five chunkings, 114 needs written before any number (2026-10-18)

**Context.** The full parse (manifest `parse/20261018T002206Z`) took 37 minutes on two workers: about
2 s a page for text documents and about 7 s a page for the two OCR'd reports.

**Decision (Claude).**
- **Elements.** 24 documents, 8,601 elements (headings, paragraphs, list items, captions, footnotes,
  tables). No high-severity text findings.
- **OCR quality, measured.** In the two scanned reports, 5.7% (2018) and 4.1% (2021) of word tokens are
  not in the vocabulary of the 22 text-layer documents; many are names and references. About 40 of their
  630 elements have garbled stretches at the start of a line ("Wi aunh a u o r avo nn ann n anng
  2010–16, China has been…"). They stay in: the rest of each paragraph is sound, every OCR passage is
  labelled in the UI, and the page viewer shows the real page. Re-OCR of those pages is an open item.
- **Boilerplate, corrected on first sight.** The first rule (paragraphs recurring verbatim in 3 or more
  documents) dropped 29 paragraphs, including the reports' recurring definitions of copyright, design
  rights, plant breeder's rights and provisional patents: exactly what a question like the owner's
  PROMPT_3 needs. The rule now requires every occurrence to sit in a document's first 4 or last 2 pages.
  It drops 12 paragraphs (licence terms, the Director General's signature line, the "commissioned
  report" disclaimer). The disclaimer's content is kept as a `note` on the three commissioned reports
  and shown with every passage from them. Regression test: `test_definitions_restated_in_body_text_are_not_boilerplate`.
- **Licences.** 17 documents state CC BY 4.0 in their text. 7 state no licence anywhere in their text
  (erp08, ipr-2021, ipr-2022, ipr-2025, ipr-2026 and both analytic notes); the catalogue says so rather
  than assuming.
- **Publisher pages.** 17 of 24 documents have a page on ipaustralia.gov.au that resolves (checked by
  status code and page title; the site returns a true 404 for missing pages). The other 7 are left empty
  rather than guessed.
- **Chunkings built** (`econ chunk`, manifest clean at `d18a504`): F384 1,568 chunks; S256 3,032;
  S384 2,037; S512 1,647; S384-noprefix 1,962.

**The silver test set (`eval/testset/silver-v1.yaml`, committed at `d18a504` before any retrieval
number).** No model budget exists yet for the SOP's TREC-style set (§17), so Claude wrote a smaller
known-item set from the parsed text:
- 114 needs over all 24 documents: 41 lookups, 28 explanations, 25 paraphrases (everyday words for a
  technical passage), 14 trends and 6 cross-document needs; 125 gold passages. Split by hashed id: 55
  dev, 59 test.
- 98 needs come from a seeded random sample of 8 to 10 body passages per document; 16 cross-document
  needs come from searching the parsed text for findings the owner's prompts touch (causal methods,
  correlation caveats, SME growth, the Raising the Bar reforms, the pandemic, AI, the innovation patent).
- Gold is located by text, so one set scores every chunking: a chunk covers a gold passage when it
  holds at least half of its characters. Every verbatim copy of a gold quote anywhere in the corpus
  counts as an equally correct find (8 gold items have copies); `alt` adds restatements.
- **Its limits.** It measures finding the passage a question was written from. Other passages that also
  answer count as misses. The writer saw each passage before writing its question, which favours keyword
  overlap, so most questions were deliberately paraphrased. With 55 dev needs, differences under about
  0.05 are hard to separate.

**Spend:** $0.

**Consequences.** For the owner: whether the extracted text may sit in this public repository (see the
reply of 2026-10-18 and the handover); the 7 documents without a licence statement.
