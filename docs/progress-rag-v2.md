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
