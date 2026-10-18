# Handover: the first version of the evidence chat

For the next Claude Code session. Read `CLAUDE.md` first, then the decisions log (D-001 to D-009). Build
only what the owner asks for next; anything that calls a language model spends money and needs a budget.

**Status (2026-10-18):** built, measured and verified locally; not deployed. Branch
`claude/eloquent-hypatia-lt1txf`. No pull request (the owner hasn't asked for one).

## Where things stand
- **Knowledge base:** 24 PDFs, 1,099 pages, 8,601 elements with page and box provenance (D-002, D-004).
  The 2018 and 2021 reports are OCR'd; about 40 of their elements have garbled stretches.
- **Retrieval:** structure-aware chunks of up to 384 tokens without a prefix (D-005), without reference
  entries (D-007 to D-009); the arctic-embed-m-v1.5 embedder and 0.7/0.3 score fusion (D-006). Measured on
  the silver test set (`eval/testset/silver-v1.yaml`, 114 needs): ndcg@10 0.554, recall@4k_tok 0.80 over
  all needs. Serving index in `library/index/` (1,896 passages), verified against the measurement by
  `econ verify-embedder` (`reports/embedder-verification.md`).
- **Memory, measured locally:** the API 121 MB (Render free: 512 MB); the embedder 722 MB after a fix that
  stops concurrent cold requests loading two copies (Cloud Run: 2 GiB). Query embedding about 45 ms on
  one thread, warm; model load about 2 s.
- **Answering:** plan, search, answer, check, with one retry (`src/econ/answer/`). Tested only with the
  scripted model: no live model call has been made (no keys).
- **Service:** the Render API, the Cloud Run embedder and the GitHub Pages front end all ran together
  locally, including the page viewer with PDFs copied from R2 and a headless-browser check on desktop and
  phone widths (no console errors, no horizontal overflow).
- **Reusable pieces:** `econ.evalr` (gold-span test sets and metrics that work across chunkings),
  `econ.retrieval.search.fuse`, `econ.answer.check` (the quote check), `econ.embedder.OnnxEmbedder`.

## Open items
1. **Deploy** (owner's steps in `docs/deploy.md`): Cloud Run, then Render, then Pages.
2. **Smoke test with a real model** (SOP §20.4) once a key exists: a few questions per provider, read
   every answer. Both adapters follow the documented REST shapes but have never made a live call. About
   $0.10.
3. **The TREC-style test set** (SOP §17) with pooled results and a judge from another model family. The
   silver set measures known-item finding only. Then re-test S256 against S384-noprefix (D-005) and the
   close embedder calls in D-006.
4. **Measure neighbour expansion**: in 13 of the 19 needs missed under S384-noprefix, the right document
   was in the top 3 (D-005). Adding a hit's neighbouring passages to the answer context may recover them.
5. **Per-document cap and diversity**: one paper took 8 of 20 slots for PROMPT_1 (causal methods). Measure
   a lower cap or MMR by document.
6. **Re-OCR the garbled pages** of the 2018 and 2021 reports (render scale 3, or another engine).
7. **Langfuse tracing** (SOP §20.0, §20.3) when the owner has keys: one trace per request, retrieval as
   structured spans, the check's results as scores.
8. **Persistent answer store and spend meter**: today the daily cap lives in memory and answers go to
   Render's log only.

## For the owner
1. **The extracted text is in a public repository.** `library/` holds every document's text, committed
   on this branch; the repository is public. The documents are IP Australia's published reports; 17 state
   CC BY 4.0, 7 state no licence in their text. Keep it, or move the library to R2 (the Render build would
   then download it with read-only credentials) and rewrite the branch history. Recommendation: keep it,
   since the public chatbot shows the same passages anyway, but confirm the 7.
2. **Publishing the PDFs on the Pages site** (the R2 secrets in the pages workflow): same question.
3. **Approve the out-of-scope question set** `eval/oos/oos-v1.yaml` and its pass rule before it runs.
4. **Model keys and a budget** for the smoke test and the evaluation; the provisional answer models are
   in `config/service.yaml`.
5. **Gemini's free tier** lets Google use the content to improve its products; the paid tier does not.

## Conventions to keep
- Commit code, run, then commit outputs; manifests record the git state at the start and end of a run.
- `pkill -f` patterns must not appear elsewhere in the same command line, or the shell kills itself; use
  `pkill -f "[u]vicorn econ.service"` as a separate command.
- Grids and test sets are committed before any number; deviations are disclosed in the decision entry.
- Next free decision number: **D-010**.
