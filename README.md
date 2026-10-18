# Econ: IP economics evidence chat

Ask questions of IP Australia's Office of the Chief Economist publications and see exactly where every
answer comes from. The knowledge base is 24 PDFs (1,099 pages): the annual Australian IP Reports 2015 to
2026 and 12 economic research papers and analytic notes.

**Built for traceability.** Every claim in an answer quotes a passage word for word, and code (not a
model) checks each quote against the passage it cites. Each passage shows its document, year, section and
page, and the page viewer draws the passage on the original PDF page. The evidence trail shows the searches
run, every passage found, why each ranked, and which ones the answer cites.

## How it fits together

```
GitHub Pages (web/)  ──►  Render: the API (src/econ/service)  ──►  Cloud Run: the embedder (src/econ/embedder.py)
  chat, evidence trail,       plan, hybrid search, answer,             one ONNX model behind POST /embed
  page viewer, library        quote check, streamed events      ──►  OpenAI or Gemini (when a key is set)
```

Without a model key the service runs in **evidence-only mode**: search with full provenance, no generated
answer. Deployment steps: [docs/deploy.md](docs/deploy.md).

## Repository map

| Path | What |
|---|---|
| `config/` | `sources.yaml` (the corpus registry), `pipeline.yaml` (parse, chunking, embedders, retrieval), `service.yaml` (the API) |
| `src/econ/ingest/` | fetch from R2, the security sweep, Docling parsing with page and box provenance |
| `src/econ/kb/` | chunking, BM25, embedding for measurement |
| `src/econ/evalr/` | the retrieval test set, metrics and measurement stages |
| `src/econ/retrieval/` | hybrid search and the serving index |
| `src/econ/answer/` | prompts, the answer schema, the quote check, model adapters, the request pipeline |
| `src/econ/service/` | the FastAPI service on Render |
| `src/econ/embedder.py` | the Cloud Run embedding service |
| `library/` | the knowledge base: elements, chunks and the serving index (committed) |
| `eval/` | test sets, grids and per-need run outputs |
| `reports/` | measurement reports |
| `web/` | the front end |
| `docs/` | decisions, deployment, handover, the SOP |

## Commands

```bash
uv sync --extra build --group dev        # everything (torch, Docling) for building; CI uses --group dev only
export R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=...

econ fetch && econ sweep && econ parse --workers 2 && econ chunk     # the knowledge base
econ eval-retrieval --stage chunking                                  # then embedders, then fusion
econ index && econ verify-embedder                                    # the serving index, checked
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

This repository holds text extracted from those reports (`library/`), and the published site serves
copies of the PDFs, for reference and traceability. The published reports are the authoritative source:
extracted text can contain conversion errors, most of all in the 2018 and 2021 reports, which were
read by OCR.

## Licence

Code: MIT (see `LICENSE`). The source documents keep their own licences (above).
