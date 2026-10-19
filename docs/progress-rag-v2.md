# Progress log: RAG v2 (making the evidence chat as good as it can be)

A running log, newest entry last, so another session can compile the results. The owner's brief
(2026-10-18): "produce the absolute very best RAG system you can possibly make", with at most $2.50 of
OpenAI and $2.50 of Gemini tokens; any step may change if it measurably improves results and stays free
to run; tests must be thoughtful and rigorous. Branch `claude/charming-edison-sg0ehp`.

Decisions go in `docs/decisions.md` (from D-011). Spend is in `eval/spend/ledger.jsonl` (one line per
paid call; `econ.spend.summary()` totals it), guarded in code against `config/eval.yaml`.

## How "free" is read
- **Free to run** means no new paid service at request time. Local models (rerankers, embedders) on the
  existing Cloud Run embedder (inside its free tier) count as free. Per-question model tokens should not
  grow materially; any change in them is stated with its cost.
- **One-off build costs** (an enrichment pass over the chunks, judging a test set) come out of the
  $5 budget.

## Plan
1. Smoke-test both providers live (SOP §20.4): the answer path had never made a live call.
2. A stronger yardstick: the 114 silver needs plus new exploratory needs like the owner's PROMPT_1-5,
   pooled across many retrieval systems and graded 0-3 by Gemini (batch, half price), with the judge
   validated against the silver gold passages and a Claude spot-check.
3. Free retrieval improvements, measured under a grid committed before the numbers: rerankers,
   contextual enrichment of chunks, the query plan, fusion, context assembly.
4. End-to-end answers on a subset, judged by another model family, to confirm gains carry through.
5. Serve whatever wins, verified against the measurement.

---

## 2026-10-18 — Session start
- Read CLAUDE.md, the handover, D-001 to D-010 and the SOP. Next free decision: D-011.
- Environment: 4 vCPU Xeon, 15 GB RAM, no GPU. `uv sync --extra build --group dev` (21 s); 60 tests pass.
- Both provider keys are injected by the session proxy (a placeholder key in the environment is
  enough). Model lists confirm `gpt-6.1-sol`, `gpt-6-luna`, `gemini-3.8-flash`, `gemini-3.5-flash-lite`.
- Prices rechecked on the providers' pages: gpt-6.1-sol $2 / $0.10 cached / $10; gpt-6-luna $0.10 /
  $0.01 / $0.50; gemini-3.8-flash $0.75 / $0.075 / $3.75 (to 2026-12-31); gemini-3.5-flash-lite $0.30 /
  $0.03 / $2.50. OpenAI Batch and Flex, and Gemini Batch, are 50% off. Config's cached-input prices for
  the two OpenAI models were placeholders at the full price; corrected.
- Added `config/eval.yaml` (budgets, cap at 96%) and `econ.spend` (ledger + guard).

## 2026-10-18 — Smoke test on both providers (SOP §20.4)
Three questions each (a lookup, the owner's PROMPT_1 on causal methods, pavlova). Events in
`eval/smoke/`. Spend: OpenAI $0.048, Gemini $0.069 (including one estimated, unmetered call).

**Bugs found and fixed**
1. Gemini 3.8 Flash counts its thinking inside `maxOutputTokens`: at medium thinking it used about
   3,300-3,700 thought tokens, so the configured 3,000 truncated every answer (`MAX_TOKENS`). Limits
   are now 12,000 (answer) and 1,500 (plan) in config; both providers bill only what is generated.
2. A failed call's usage was thrown away, so a truncated (billed) answer went unmetered, in the ledger
   and in the service's daily cap. `ProviderError` now carries the usage and the pipeline meters it.
   The one lost call is in the ledger as an estimate.

**Finding that matters most so far: the plan can sink a broad question.** On PROMPT_1, the OpenAI
planner (gpt-6-luna) wrote one long query, "causal inference econometric methods identification
strategy Office of the Chief Economist IP Australia". Its evidence was report forewords and contents
pages, and gpt-6.1-sol answered `not_in_kb`, which is wrong: the corpus describes GMM, fixed effects,
placebo tests and lag structures (erp10, erp11, erp15). Gemini's planner wrote three short queries,
found those passages, and Gemini answered well. The corpus-wide words ("IP Australia", "Office of the
Chief Economist") pull in front matter. Candidates: a better plan prompt, keeping the original question
as a query, and a reranker. All go into the measurement.

Both models answered the lookup correctly with verified quotes, and both returned `not_in_kb` for
pavlova. gpt-6.1-sol was more concise and added a caveat; Gemini quoted more.

## 2026-10-18 — The yardstick: test set, plans, enrichment, judge pilot
- **explore-v1** (64 needs, committed at `4aad8ab` before any number): broad questions modelled on the
  owner's prompts, five of them the owner's own; each with a narrative for the judge. With silver-v1:
  178 needs, 86 dev and 92 test (`econ.evalr.judged`).
- **Plans** for every need (`eval/runs/judged-v1/plans/`): gpt-6-luna and gemini-3.5-flash-lite with
  plan-v1 (the service's prompt) and plan-v2 (written from the dev needs only: no corpus-wide words,
  split broad questions, a map of the corpus). Luna with plan-v1 writes one query for 160 of 178 needs;
  flash-lite writes two or three. Cost: $0.015 OpenAI, $0.10 Gemini.
- **Contextual enrichment** (`library/enrich/S384-noprefix-nocite.luna-enrich-v1.jsonl`): a note of at
  most 50 words per chunk, saying where it sits and resolving vague references, by gpt-6-luna on Flex.
  Search-only, never evidence. $0.14 for 1,896 chunks.
- **Measurement path verified**: the systems code reproduces the serving index (top-10 overlap 0.999)
  and D-009's silver ndcg@10 (0.554).
- **Rerankers** screened (bf16 on this CPU's AMX; bf16 vs fp32 Spearman 0.9996, identical top 10):
  ettin-17m/32m/68m, ms-marco-MiniLM-L6, and as a ceiling gte-reranker-modernbert-base and
  ettin-150m. CPU speed in float32, 4 threads: 17M 44 pairs/s, 32M 21, 68M 7, 150M 3.6.
- **Judge pilot** (12 seeded needs, about 1,000 passages, both Gemini models, by Batch):
  Batch ignores the JSON schema (bare lists, "score" for "grade", maps), so the parser reads every
  shape but still needs each passage graded exactly once. Against Claude's blind grades of 100 pairs:
  gemini-3.8-flash quadratic kappa 0.915 (95% agreement on relevant or not), flash-lite 0.774 (over-
  grades: 63% precision on "relevant"). By the rule set before the pilot, Flash judges. Both judges
  graded every gold-covering chunk 3. Pilot cost $0.23.
- **Grid amendment 1** (before any pool judgment): Flash can't afford depth-20 judging of every system,
  so the pool is every system's top 10, stage 1 chooses on ndcg@10, and a top-up judges ranks 11-20 of
  the chosen setting and the baseline.

## 2026-10-18 — Serving path for a reranker (built, off until the grid decides)
- `econ.reranker.OnnxReranker`: the Ettin rerankers' repository ONNX exports hold only the transformer
  (`last_hidden_state`), so the score head (CLS pooling, dense + GELU, LayerNorm, dense to one logit) is
  read from the repository's safetensors (parsed without the library) and applied in numpy. Parity with
  sentence-transformers in float32: max absolute difference 3e-6 on 50 real pairs, for 17m and 32m.
- The Cloud Run service gains `POST /rerank` (same token, same limits: 64 passages, 4,000 characters
  each); the image fetches the adopted reranker at a pinned revision with hash checks, or none.
- The pipeline reranks the first stage's top `reranking.depth` (50) against the question as asked (plus
  pasted headings), keeps the first-stage rank on the record, and if the reranker fails keeps the
  first-stage order with a visible status, as search does when the embedder fails.
- Tests: `tests/test_rerank.py` (7). Revisions pinned in `config/pipeline.yaml` and `econ.evalr.systems`.
- The answer-eval runner (`econ.evalr.answers`) mirrors the service's answer step on any setting.

## 2026-10-18 — Pool judged; first look at stage 1
- **Pool judgments** (`eval/judgments/judged-v1.jsonl`): 8,246 graded (need, passage) pairs: the top 10
  of all 62 non-ceiling settings plus BM25 and dense alone, and the pilot's depth-20 grades for 12 needs.
  Two Batch jobs, 446 requests, every reply parsed. $1.15 (Gemini total $1.56).
- **Judge validity on the whole silver set:** 128 of 129 passages that hold a gold answer were graded
  relevant (125 of them 3). Every one of the 178 needs has at least one relevant passage. Grade mix: 54%
  0, 22% 1, 12% 2, 12% 3.
- **First look** (ndcg@10; the formal run waits for the latency measurement and the ceiling rerankers,
  which can't change the choice under the rule):
  - the service today, `plan:luna-plan-v1/plain/none`: dev 0.654, test 0.606;
  - context notes alone, `plan:luna-plan-v1/enriched/none`: dev 0.713, test 0.675;
  - no planner at all, enriched index, `raw/enriched/none`: dev 0.689, test 0.670;
  - best: `plan+q:luna-plan-v2/enriched/none` (plan-v2 queries plus the question, enriched index, no
    reranker): dev 0.736, test 0.692; on exploratory dev needs 0.739 against the baseline's 0.599;
  - rerankers help the plain index (ettin-68m: 0.654 to 0.706 dev) but not the enriched one (0.736 to
    0.711 with plan+q): they read only the passage, not its context note. The small ones (17M, 32M,
    MiniLM) are neutral to harmful throughout.

## 2026-10-18 — Adoption, verification, answers, out-of-scope set (D-012 to D-015)
- **Stage 1 (formal)** chose `plan+q:luna-plan-v2/enriched/none`; stage 2 kept the cap at 8; the final,
  fully judged test comparison: ndcg@10 0.597 to 0.682, ndcg@20 0.616 to 0.694, relevant-passage recall in
  the context 0.623 to 0.715, all Holm p 0.002. Re-run on every judgment, the rule picks the same setting.
- **Adopted** (D-013): context notes in the index, plan-v2, the question kept as a search. Index rebuilt
  (ONNX); `econ verify-search` against the measurement: top-10 overlap 0.996, judged ndcg@10 0.7038 served
  vs 0.7039 measured.
- **Bug found and fixed:** the shared Snowball stemmer is not thread-safe (81 wrong, 17 errors in 200 calls
  on 8 threads); the service tokenises in a thread pool. Now per thread.
- **End-to-end answers** (D-014): 60 test needs x 2, all pass the check; exploratory answers cite 4.2 to
  5.0 relevant passages; Gemini (both orders) prefers the new answers 19 to 7 on exploratory needs, Claude
  (blind) 18 to 6; they agree on all 20 pairs where both had a preference.
- **Out-of-scope set** (D-015), first run, live pipeline: 13 of 18 by the rule, every answer read. A poem
  request was obeyed; "What's the trend?" and a thin question labelled `complete`. PROMPT_1 now answered
  well. A transient 502 left one question unanswered: provider calls now retry once. answer-v2 proposed
  to the owner (declines non-information requests, an advice caveat, stricter `complete`); on 9 items it
  fixes the poem and the advice caveat with no loss on the controls.
- **Spend at the end:** OpenAI $2.13 of $2.50, Gemini $1.86 of $2.50.
- Records: D-011 to D-015, `CLAUDE.md`, `README.md`, `docs/handover-rag-v2.md`,
  `docs/rag-v2-results-explained.md`.

## 2026-10-18 — Grid v3 (D-016): no further change
Fusion weight, note-reading rerankers and an answer-shaped query (plan-v3), pre-registered, topped up to
fully judged top 10s: none beats the adopted setting on dev by the margin. Rerankers with notes are still
harmful at 17M and 32M; the fusion weight is flat between 0.6 and 0.8; plan-v3 is level on dev and +0.022 on
test (interval includes zero). Final spend: OpenAI $2.15 of $2.50, Gemini $1.92 of $2.50.

## 2026-10-18 — Context depth (D-017): broad questions need more than 20 passages
The adopted ranking at 40 and 60 passages, pre-registered, ranks 21-60 judged on the 92 test needs (1,388
passages, $0.23). Exploratory needs: relevant evidence reached 0.491 at 20, 0.682 at 40, 0.760 at 60; lookups
0.765 to 0.851. A perfect breadth classifier (60 for broad questions) gets 0.763 at 31 passages on average;
the plan's query count is a weak proxy. Recommended to the owner, pending an end-to-end check: always 40, or a
breadth field in the plan. Spend: OpenAI $2.15 of $2.50, Gemini $2.16 of $2.50.

## 2026-10-18 — A relevance filter (D-018): the best 20 of 60
Free diagnosis first: the missing evidence is mostly found but ranked 21-60; re-chunking, de-duplication and
query interleaving would not help; removing the per-document cap helps a little. Then, pre-registered: gpt-6-luna
rates the 60-passage context and the answer model gets the best 20. Exploratory evidence reached 0.491 to 0.635,
lookups 0.765 to 0.833, ndcg@10 0.672 to 0.846, same context size; filter step 4.4 s median, about $0.002 a
question. Recommended to the owner, pending an end-to-end answer comparison (needs about $0.60 more OpenAI
budget). Spend: OpenAI $2.25 of $2.50, Gemini $2.16 of $2.50.

## 2026-10-18 — End-to-end check of the filter (D-019): better answers
The filter's 20 against the adopted 20 on the answers-v1 needs, answer model and prompt unchanged. The OpenAI
account ran out of credit with 3 needs unanswered; on the other 57 (the owner's choice), Gemini prefers the filtered
answers 28 to 8 (exploratory 18 to 4) and Claude, blind, 17 to 4; all 57 pass the check. Recommended to the owner:
adopt the filter in the service (a design is in D-019). Spend: OpenAI $2.88 of $3.50 (account credit exhausted),
Gemini $2.26 of $2.50.

## 2026-10-19 — The relevance filter in the service (D-020)
The owner adopted the filter. Built: config (`answer.filter`, `filter_model` per provider), the locked prompt
filter-v1, the pipeline step (parallel calls, validation, fallback), the `search` event and `retrieval.pool`
(all 60 passages with search rank, rating and selection), the compact log, the trail's filter step and 60-row
table, and `econ verify-search` checks for the filter (same 60, same prompt, same 20 from the measured
ratings). 92 tests pass. Not yet run live: the OpenAI account needs credit first.

## 2026-10-19 — The owner's decisions; deployment checked (D-021)
gpt-6.1-sol adopted; answer-v1 kept (answer-v2 not adopted); coverage calibration dropped; every paid call
still needs the owner's permission. Checked live: Pages (with PDFs), Render on `main`'s commit (dense lane
`ok`, CORS for the Pages origin), Cloud Run. Render's build rehearsed with plain pip: the service holds about
137 MB. Left: the owner sets `OPENAI_API_KEY` on Render, then one question as the filter's live smoke test.

## 2026-10-19 — Tracing, the OCR repair, the front end (D-022)
- The filter's first live call on Render: filter ok (42 read, 20 kept, 3.85 s), the answer passed the check,
  US$0.029.
- Langfuse tracing (`econ.tracing`, SDK 5.0.2): one trace per question with typed observations, the build on
  each, usage and costs, scores from the check; 11 offline tests with the real SDK; verified live and the test
  traces deleted. Waits for the owner's Langfuse keys on Render.
- OCR repair in the parse stage: 62 garbled elements in the 2018 and 2021 reports; 47 repaired by RapidOCR
  under crop variants, 8 by gemini-3.8-flash (US$0.019), 7 names left as printed. 57 chunks changed, one
  added (1,897); notes for 54 new prompts (US$0.004); index rebuilt (other documents' vectors identical);
  602 judgments re-graded (US$0.245).
- Front end: Light/Dark switch, gunmetal dark mode, the trail's process view with an activity log and a
  passage strip, after wind-tunnel's pipeline view.

## 2026-10-19 — The Langfuse keys on Render, checked; a counter fix
- Render runs `main` (0185d87) with tracing on in `prod`. One question as the smoke test (trade marks and small
  businesses; the owner's request to check the keys): filter `ok` (60 read, 20 kept, 10.0 s), the answer passed
  the check first time (4 claims), US$0.027, 39.5 s.
- `/api/health` still said 0 spans exported, 0 failed. Cause: uvicorn reads `econ.service.app:app` twice at
  start-up, and the module built a new app on each read: two indexes in memory and two tracers. Langfuse keeps one
  client per key, so the first tracer's exporter sent every span and the served tracer's counter never moved.
  Traces were sent; the health line could not see them. Reproduced locally under `econ serve` (the trace reached
  Langfuse, the counter stayed at 0). Fixed: the app is built once (a test covers it); under `econ serve` the
  counter now reads 2 exported about 5 s after a question. Test traces deleted from the session's Langfuse project.
- Deploys with the next merge to `main`; then `/api/health` should show `exported` above 0 after a question.
