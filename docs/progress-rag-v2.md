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
