# Econ: IP economics evidence chat

Ask questions of IP Australia's Office of the Chief Economist publications and WIPO reports and see exactly
where every answer comes from. The knowledge base is 30 PDFs (1,858 pages): the annual Australian IP Reports
2015 to 2026, 12 economic research papers and analytic notes, and six reports of the World Intellectual
Property Organization (WIPO), with the Global Innovation Index 2026's data file for its economy profiles.

**Built for traceability.** Every claim in an answer quotes a passage word for word: the model cites
numbered sentences, and code (not a model) copies those sentences from the passages as the quotes and checks
every citation. Each passage shows its document, year, section and
page, and the page viewer draws the passage on the original PDF page. The evidence trail shows the searches
run, every passage found, why each ranked, and which ones the answer cites.

## How it fits together

```
GitHub Pages (web/)  ──►  Render: the API (src/econ/service)  ──►  Cloud Run: the embedder (src/econ/embedder.py)
  chat, evidence trail,       plan, hybrid search, relevance           one ONNX model behind POST /embed
  page viewer, library        filter, answer, quote check,      ──►  OpenAI or Gemini (when a key is set)
                              streamed events
```

Without a model key the service runs in **evidence-only mode**: search with full provenance, no generated
answer. Deployment steps: [docs/deploy.md](docs/deploy.md).

**How well it finds things (RAG v2, D-011 to D-015).** Measured on a judged test set of 178 questions
(the original known-item questions plus exploratory ones like staff ask), graded by a Gemini judge whose
grades agreed with Claude's blind grades of a sample at quadratic kappa 0.92. Search uses short context notes on every
passage and searches the question alongside the plan's queries; against the first version, the share of
relevant passages that reach the answer rose from 0.62 to 0.72, and on exploratory questions two judges
preferred the new answers by about three to one. Plain-English summary:
[docs/rag-v2-results-explained.md](docs/rag-v2-results-explained.md).

**The relevance filter (D-018 to D-020).** Search keeps its first 60 passages and a small model (gpt-6-luna) rates
each 0 to 3 for how much an answer could use it; the answer model gets the 20 rated highest. On the judged test set
this lifted ndcg@10 from 0.67 to 0.85 and the share of a broad question's relevant passages reaching the answer
from 0.49 to 0.64, at the same context size; blind judges preferred the resulting answers (Gemini 28 to 8, Claude
17 to 4 on exploratory questions). The evidence trail lists all 60 passages with their ratings.

## Repository map

| Path | What |
|---|---|
| `config/` | `sources.yaml` (the corpus registry), `pipeline.yaml` (parse, chunking, embedders, retrieval), `service.yaml` (the API) |
| `src/econ/ingest/` | fetch from R2, the security sweep, Docling parsing with page and box provenance |
| `src/econ/kb/` | chunking, BM25, embedding for measurement, the context notes (`enrich.py`) |
| `src/econ/evalr/` | test sets (silver, judged), metrics, measurement grids, the judge, answer and out-of-scope runs, the metered call layer |
| `src/econ/reranker.py` | an ONNX cross-encoder for the Cloud Run service (measured, not adopted) |
| `src/econ/retrieval/` | hybrid search and the serving index |
| `src/econ/answer/` | prompts, the answer schema, the quote check, model adapters, the request pipeline |
| `src/econ/service/` | the FastAPI service on Render |
| `src/econ/embedder.py` | the Cloud Run embedding service |
| `library/` | the knowledge base: elements, chunks and the serving index (committed) |
| `eval/` | test sets, grids, judgments, per-need run outputs, the paid-reply cache and the spend ledger |
| `reports/` | measurement reports |
| `web/` | the front end |
| `docs/` | decisions, deployment, handover, the SOP |

## Commands

```bash
uv sync --extra build --group dev        # everything (torch, Docling) for building; CI uses --group dev only
export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=...

econ fetch && econ sweep && econ parse --workers 2 && econ chunk     # the knowledge base
econ eval-retrieval --stage chunking                                  # then embedders, then fusion (silver set)
econ eval-retrieval-v2 --stage stage1                                 # then stage2, final (judged set, cached)
econ index && econ verify-embedder && econ verify-search              # the serving index, checked
econ ask "How did trade mark filings change during the pandemic?"     # one question, locally
econ serve                                                            # the API on http://127.0.0.1:8787
uv run pytest -q                                                      # tests: no network, no models
```

To try the front end locally, serve `web/` (for example `python -m http.server -d web 8000`) and open
`http://localhost:8000/?api=http://127.0.0.1:8787`.

## Source documents

The knowledge base is built from IP Australia's public reports: the Australian IP Reports and the Office
of the Chief Economist's research papers and notes, as published at
[ipaustralia.gov.au](https://www.ipaustralia.gov.au/tools-and-research/professional-resources/data-research-and-reports).
They are © Commonwealth of Australia (IP Australia); most state a Creative Commons Attribution 4.0
licence, and `library/index/docs.json` records each one's licence as found in its text. Three research
papers are independent reports commissioned by IP Australia, and their findings are their authors'.

The six WIPO documents are © WIPO, published under a Creative Commons Attribution 4.0 licence, as are the
Global Innovation Index 2026 data from which the knowledge base writes the GII's 139 economy profiles
(`econ.ingest.gii`): the Global Innovation Index 2026, WIPO's page on Australia's GII 2026 results, World
Intellectual Property Indicators 2025, the PCT Yearly Review 2026, the Madrid Yearly Review 2026 and World
Intangible Investment Highlights 2026, as published at [wipo.int](https://www.wipo.int/publications/).

This repository holds text extracted from those reports (`library/`), and the published site serves
copies of the PDFs, for reference and traceability. The published reports are the authoritative source:
extracted text can contain conversion errors, most of all in the 2018 and 2021 reports, which were
read by OCR.

## Licence

Code: MIT (see `LICENSE`). The source documents keep their own licences (above).
