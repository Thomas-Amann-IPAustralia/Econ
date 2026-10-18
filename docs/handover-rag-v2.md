# Handover: RAG v2

For the next session. Read `CLAUDE.md`, then D-011 to D-015 in `docs/decisions.md`, then this. The running
log of the session is `docs/progress-rag-v2.md`; the owner's summary is `docs/rag-v2-results-explained.md`.

**Status (2026-10-18):** RAG v2 adopted in config and verified. Branch `claude/charming-edison-sg0ehp`
(not merged). The owner's brief for this session: the best RAG system that stays free to run, up to $2.50
of OpenAI and $2.50 of Gemini. Spent: OpenAI $2.13, Gemini $1.86 (`eval/spend/ledger.jsonl`).

## What changed in the service
- `retrieval.enrichment: S384-noprefix-nocite.luna-enrich-v1` (context notes in front of each chunk for
  BM25 and dense; search only). The index in `library/index/` is rebuilt with them (`index.json` records the
  notes file and its hash).
- `answer.plan_prompt: plan-v2`, `answer.plan_keeps_question: true`.
- `reranking.adopted: null` (built: `econ.reranker`, `POST /rerank`, pipeline step with fallback).
- Fixes: output limits include thinking (12,000 / 1,500); failed billed calls are metered; one retry on
  transient provider errors; a per-thread stemmer (the shared one corrupted BM25 under concurrency).
- Deploy: the Render API needs only the new commit (index and config are in the repo). The Cloud Run image
  is unchanged in behaviour (it fetches no reranker while none is adopted).

## The yardstick, for anything that comes next
- `econ.evalr.judged.load()` gives the 178 needs (`eval/testset/silver-v1.yaml` + `explore-v1.yaml`).
- Grades: `eval/judgments/judged-v1.jsonl` (gemini-3.8-flash, `prompts/eval/judge-v1.md`). Unjudged passages
  count as 0, so a new method must be topped up before it is compared (`grid2.topup_targets`, `judge.py`,
  Batch at half price; about $0.00016 a passage).
- Settings are named `<query form>/<text>/<reranker>[/capN]` (`grid2.named`); cached plans in
  `eval/runs/judged-v1/plans/`, reranker scores in `eval/cache/rerank/`, paid replies in `eval/cache/llm/`.
- Batch ignores the JSON schema: parse every reply shape and require each item exactly once.

## Open items
1. **For the owner: answer-v2** (D-015): declines non-information requests (the poem), says when a reply is
   not advice, calibrates `complete`. Run on 9 items only; before adopting, run the answers-v1 set with it
   (about $0.70) to check in-scope answers don't suffer.
2. **Model choice** (SOP §20.5): gpt-6.1-sol vs gemini-3.8-flash vs others, judged across families.
3. **Coverage calibration**: answers label `complete` too readily (the vague and trade-secrets items).
4. **A reranker that reads the notes** (note + passage as its input) is the untested idea most likely to add
   to retrieval; the 150M ettin model led on dev without the notes (0.753) but not on test.
5. **The plan prompt's document map** must be updated when documents are added; so must the notes
   (`econ.kb.enrich`, about $0.14 a corpus).
6. Carried from v1: Langfuse tracing, re-OCR of the 2018 and 2021 garbled pages, a persistent answer store.

## Conventions kept
- Grids and test sets committed before any number; deviations recorded as amendments before the data they
  affect (see grid retrieval-v2, amendment 1).
- Every paid call goes through `econ.evalr.llmcall` or `econ.evalr.judge` (cached, metered, capped).
- Next free decision number: **D-016**.
