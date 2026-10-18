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

---

## D-005 — Chunking: structure-aware chunks of up to 384 tokens, without a heading prefix (Claude, as delegated by the owner; 2026-10-18)

**Context.** The owner asked Claude to "select a chunking strategy and embedding model you think will
best suit my needs", so the choice is Claude's, made on data under the rule committed in
`eval/grids/retrieval-v1.yaml` at `411f27b`, before any number existed (SOP §3, §12). Run
`eval-retrieval/20261018T011000Z`; report `reports/retrieval-chunking.md`.

**Decision.** `chunking.adopted: S384-noprefix`: chunks never cross a section; elements are packed up to
384 tokens; long paragraphs split at sentences and long tables at rows (repeating the header); no
title or section prefix in the embedded text. The answer model still sees each passage's document,
year, section and pages, as attributes of its evidence block.

**Method.** Five strategies, each scored with two embedders from different families (bge-small, a BERT,
and gte-modernbert, a ModernBERT) on the hybrid lane (0.7 dense + 0.3 BM25). Primary metric:
`recall@4k_tok`, the share of a need's gold passages that reach the answer model when the top chunks
fill 4,000 tokens, which is fair across chunk sizes. Rule: the first strategy, simplest first, within
0.02 of the best on dev.

**Results** (recall@4k_tok, averaged over the two embedders):

| Strategy | Dev (55) | Test (59) | Test vs F384 [95% CI] |
|---|---|---|---|
| F384 (fixed windows, the baseline) | 0.683 | 0.715 | |
| **S384-noprefix (chosen)** | 0.794 | 0.742 | +0.027 [−0.054, +0.112] |
| S384 (with the heading prefix) | 0.792 | 0.720 | +0.006 [−0.065, +0.076] |
| S256 | 0.803 | 0.771 | +0.056 [−0.017, +0.138] |
| S512 | 0.753 | 0.742 | +0.027 [−0.041, +0.097] |

**Reading them.**
- On dev, structure-aware chunking beats fixed windows by 0.07 to 0.12. On test the gain is smaller, and
  no interval excludes zero: with 59 needs, a difference has to exceed about 0.08 to show. The direction
  holds in every structure variant on both splits.
- **S256 was best on both splits**, and on cross-document needs (0.486 against 0.361), but within the
  margin of the simpler S384-noprefix on dev. It is the runner-up to re-test when a larger test set
  exists; smaller passages would also make quotes and highlights tighter.
- **The heading prefix adds nothing here** (0.792 with, 0.794 without on dev; 0.720 and 0.742 on test).
  A plausible reason: 12 of 24 documents share nearly the same title ("Australian IP Report 20XX"), so the
  prefix adds the same words to many chunks without telling them apart.
- **What the misses are.** 19 needs are missed by both embedders within 4k tokens. In 13 of them the gold
  document is in the top 3: search found a neighbouring passage, or the same kind of finding in another
  year's report (plant varieties, for instance, appear in several editions). Some of those are correct
  answers the silver set counts as misses; others suggest adding a hit's neighbouring passages to the
  context, a candidate to measure later.

**Disclosed.** The run's manifest records the git state at its end (`11dc5b5`, plus the untracked draft in
`eval/oos/`), because the manifest code then recorded only the end state. The measurement ran at
`374a744`; the files changed in between (the embedder, the API, the CLI's index command, the front end)
are not used by the measurement. Manifests now record the state at the start too (`2f62fd9`).

**Spend:** $0 (CPU only: about 32 minutes).

**Consequences.** The embedder stage runs on S384-noprefix. For the owner: nothing to decide; S256 is
noted as the runner-up.

---

## D-006 — Embedder: Snowflake arctic-embed-m-v1.5 (109M), served on Cloud Run; fusion stays at 0.7 dense + 0.3 BM25 (Claude, as delegated by the owner; 2026-10-18)

**Context.** The second and third stages of the grid committed at `411f27b`, on the chunking chosen in
D-005. Runs `eval-retrieval/20261018T014224Z` (embedders) and `20261018T030802Z` (fusion); reports
`reports/retrieval-embedders.md` and `reports/retrieval-fusion.md`.

**Decision.** `embedding.adopted: arctic-m-v1.5`
(`Snowflake/snowflake-arctic-embed-m-v1.5` at `e58a8f75`, Apache-2.0, 768 dimensions, CLS pooling, the
query prefix "Represent this sentence for searching relevant passages: "). It is served from the
repository's own ONNX export, whose sha256 (`bc6f7662…`) is now pinned in config. Fusion stays as
configured: min-max score fusion, 0.7 dense and 0.3 BM25.

**Embedder results** (ndcg@10 on the hybrid lane, S384-noprefix; rule: the smallest candidate within
0.02 of the best on dev):

| Model | Params | Dev | Test | Test vs bge-small [95% CI] |
|---|---|---|---|---|
| bge-small (baseline) | 33M | 0.543 | 0.450 | |
| leaf-ir | 23M | 0.570 | 0.516 | +0.066 [−0.001, +0.133] |
| **arctic-m-v1.5 (chosen)** | 109M | **0.590** | 0.522 | +0.071 [+0.002, +0.142] |
| modernbert-embed | 149M | 0.558 | 0.528 | +0.078 [+0.023, +0.136] |
| arctic-l-v2 | 568M | 0.589 | 0.552 | +0.101 [+0.054, +0.149], Holm p 0.003 |
| qwen3-0.6b | 596M | 0.577 | 0.479 | +0.029 [−0.052, +0.111] |
| bge-large / mxbai-large | 335M | 0.569 / 0.557 | 0.457 / 0.474 | +0.006 / +0.024 |

The other six (minilm-l6, arctic-s, granite-small-r2, bge-base, granite-r2, gte-modernbert) scored
0.517 to 0.568 on dev; all are in the report.

**Reading them.**
- arctic-m-v1.5 was best on dev, so the rule chose it outright. **leaf-ir missed the margin by 0.0001**
  (0.569640 against a threshold of 0.569741). Its repository's ONNX export also appears to lack the
  model's final projection layer, which would have needed a custom export.
- **arctic-l-v2 is the runner-up.** It tied on dev (0.589), did better on test, and is the only model
  ahead of the baseline after the Holm adjustment. Head to head over all 114 needs, it leads arctic-m-v1.5
  by +0.015 ndcg@10 [−0.017, +0.047] and +0.013 recall@4k_tok [−0.026, +0.057]: a tie, for a model five
  times larger and about three times slower to embed. Re-test it on the larger test set.
- **Size bought nothing reliable here.** The four models of 335M to 600M parameters averaged no better
  than the best 110M models.
- **Parity, probed.** ONNX and sentence-transformers vectors for arctic-m-v1.5 agree to cosine 1.000000
  on documents, a query and an input long enough to truncate. `econ verify-embedder` checks the whole
  test set and the index after the build.

**Fusion results** (ndcg@10, arctic-m-v1.5; rule: keep the configured hybrid unless another lane beats it
by more than 0.02 on dev):

| Lane | Dev | Test | Test vs hybrid [95% CI] |
|---|---|---|---|
| **hybrid, 0.7 dense + 0.3 BM25 (kept)** | 0.590 | 0.522 | |
| dense only | 0.574 | 0.483 | −0.039 [−0.080, −0.001] |
| BM25 only | 0.448 | 0.371 | −0.151 [−0.235, −0.071] |
| 0.5 / 0.5 | 0.587 | 0.481 | −0.041 [−0.078, −0.008] |
| 0.85 / 0.15 | 0.584 | 0.510 | −0.012 [−0.040, +0.015] |
| reciprocal rank fusion | 0.533 | 0.462 | −0.060 [−0.114, −0.015] |

The keyword lane earns its place: hybrid beats dense-only on both splits. Reciprocal rank fusion trails
score fusion, as it did in the reference build.

**Disclosed.** The embedder run's manifest records the end state (`2f62fd9`, with uncommitted edits to
docs and the front end): it started at `11dc5b5` under the old manifest code. The only code committed
during the run was `src/econ/manifest.py`, which the running process had already loaded. The fusion run
recorded its start state (`2f62fd9`); its uncommitted edits were to docs and `web/app.js`.

**Spend:** $0 (CPU only: about 75 minutes for the 14 embedders).

**Consequences.**
- Serving: Cloud Run holds a 436 MB ONNX model; about 1 GB of RAM at run time, so 2 GiB and 1 vCPU. The
  Render API loads 1,969 vectors of 768 dimensions (3 MB as float16).
- Open, in order of expected value: re-test S256 and arctic-l-v2 on a larger test set; measure neighbour
  expansion and a lower per-document cap (D-005); try the int8 ONNX export (110 MB, faster cold starts)
  against the float32 index.

---

## D-007 — Leave bibliography entries and citation-only endnotes out of the chunks (Claude, within the delegated chunking choice; 2026-10-18)

**Context.** Read on the adopted index, the owner's broad prompts returned reference-list entries among
their top passages: "Achen, H. C. 2000, Why lagged dependent variables…" at rank 3 for PROMPT_1 (causal
methods), and three endnotes citing the same WIPO paper leading PROMPT_4. Reference lists are dense with
the vocabulary of broad questions ("innovation", "economics", "patents") and answer nothing; each one takes
a slot the answer model could use. The silver test set never has a gold passage in a reference, so its
metrics can't see this.

**Decision.** `chunking.adopted: S384-noprefix-nocite`: S384-noprefix, plus `drop_citations`. An element is
a citation when it is a short paragraph or list item (under 600 characters) that starts like a reference
("Surname, I. …" or "Organisation (2020) …", after an optional endnote number) and carries a publication
signal (a year, "Retrieved", a URL, "Journal", "Working Paper"…). 397 of 8,601 elements qualify. They keep
their place in the canonical text and their pages; they enter no chunk. Endnotes that say something
substantive stay (two gold answers are endnotes).

**Method.** Grid `retrieval-v1b`, committed at `cfba7bf` before its numbers. Rule: non-inferiority, adopt
unless dev recall@4k_tok falls more than 0.01. Checked beforehand: no gold passage, or verbatim copy of one,
lies in a dropped element. A first pattern also caught an ordinary sentence ("Despite the overall decline
in applications in 2016, …") and was tightened before the run; regression test
`test_a_sentence_that_mentions_a_year_is_not_a_citation`.

**Results** (run `eval-retrieval/…` for grid `retrieval-v1b`; report `reports/retrieval-v1b-chunking.md`):

| | recall@4k_tok dev / test | ndcg@10, all 114 | Citation-heavy share of the top 10, all 114 |
|---|---|---|---|
| S384-noprefix | 0.842 / 0.771 | 0.555 | 1.8% |
| **S384-noprefix-nocite** | 0.842 / 0.771 | 0.549 (−0.005 [−0.016, +0.001]) | 0.0% |

**Spend:** $0. **Consequences.** The index is rebuilt and re-verified on the new chunks (1,913 passages).

---

## D-008 — Citation filter v2: section-aware, with a guard for endnotes that say something (Claude; supersedes the filter rule in D-007; 2026-10-18)

**Context.** On the index built after D-007, the owner's prompts still drew reference entries whose
format filter v1 missed: initials without full stops ("Johnson, M, Bialowas, A, …"), an organisation
then a full stop ("Australian Bureau of Statistics. Australian National Accounts…"), a year followed by
"(page 3)", and endnotes listed under per-chapter subheadings. One stayed at rank 1 for PROMPT_1.

**Decision.** `is_citation` now also drops, under a heading containing References, Bibliography,
Endnotes or Sources, any element with a year and a publication marker; and anywhere, an element that
starts with two or more "Surname, I," names. A guard keeps any element with a sentence of 10 or more
words and no year, link or publication marker, so a note such as "…Final Report March 2015. The Harper
Review highlighted that Australia has no overarching IP policy…" stays. 420 elements qualify (397 under
v1); no gold passage lies in one. Regression test:
`test_under_a_references_heading_looser_citations_go_but_substantive_notes_stay`.

**Results** (grid `retrieval-v1c`, committed at `d6baa17` before its numbers; same non-inferiority rule
as v1b):

| | recall@4k_tok dev / test | All 114: ndcg@10 | All 114: recall@4k_tok | Citation-heavy share of top 10 |
|---|---|---|---|---|
| S384-noprefix | 0.842 / 0.771 | 0.555 | 0.806 | 1.8% |
| **S384-noprefix-nocite (v2)** | 0.842 / 0.763 | 0.554 (−0.001 [−0.003, +0.002]) | 0.801 (−0.004 [−0.026, +0.013]) | 0.0% |

**Checked.** Index rebuilt (1,914 passages) and re-verified at `3ff9855`: top 10 identical to the
sentence-transformers path on all 114 questions.

**Spend:** $0.

---

## D-009 — Citation filter v3: inside a reference list, every dated entry is a citation (Claude; refines D-008; 2026-10-18)

**Context.** After D-008 a references entry ("Arellano, M., and Bond, S. 1991. Some tests of
specification for panel data…") still led PROMPT_1: D-008's guard took its long title for a sentence
with something to say.

**Decision.** Under a heading containing References, Bibliography or Works cited (not Endnotes), every
element with a year is a citation, without the guard. Endnotes keep the guard, since some say
something substantive. 475 elements qualify; no gold passage lies in one. Regression test
`test_everything_dated_in_a_reference_list_is_a_citation`.

**Results** (grid `retrieval-v1d`, committed before its numbers; same rule): dev recall@4k_tok 0.842 for
both; over all 114 needs ndcg@10 −0.001 [−0.003, +0.002] and recall@4k_tok −0.004 [−0.026, +0.013];
citation-heavy share of the top 10 from 2.2% to 0.0%. Index rebuilt (1,896 passages) and re-verified
(`3b2fdc9 clean`; identical top 10 on all 114 questions).

**Spend:** $0.

---

## D-010 — Publication, the out-of-scope set, and keys (owner; 2026-10-18)

**Context.** The handover (D-009 state) put five questions to the owner: whether the extracted text may
stay in the public repository, whether the PDFs may be published on the Pages site, how to deploy, the
out-of-scope question set, and model keys.

**Decision (owner).**
1. **The extracted text stays public** in `library/`. Every PDF was taken from IP Australia's public
   website; a static acknowledgement in the README is enough. Done: README "Source documents".
2. **The PDFs may be published on the Pages site** (the R2 secrets in the pages workflow), with a short
   static disclaimer that they are IP Australia's public reports. Done: a footer on every view of the
   site, linking to the reports' page on ipaustralia.gov.au and naming the published reports as the
   authoritative source.
3. **Deployment** is the owner's, following `docs/deploy.md`; Claude gave the steps in the session.
4. **Model keys and a budget** come in the next session. Until then the service runs evidence-only.
5. **The out-of-scope set `eval/oos/oos-v1.yaml` is approved**, its questions and pass rule as written
   ("comfortable with it if you are"). Claude re-checked the four corpus facts it relies on against
   `library/elements/` (the 2014 GII rank in ipr-2015, the innovation patent's phase-out in ipr-2018,
   the 16% SME growth finding in ipr-2022 and ipr-2024, 88,725 trade mark applications in 2021 in
   ipr-2022). It runs with the first model budget.

**Consequence.** `CLAUDE.md` no longer lists adding the PDFs to the public site as a question for the
owner; publishing anything else new still is.

**Spend:** $0.
