# Handover: RAG v2

For the next session. Read `CLAUDE.md`, then D-011 to D-021 in `docs/decisions.md`, then this. The running
log of the session is `docs/progress-rag-v2.md`; the owner's summary is `docs/rag-v2-results-explained.md`.

**Status (2026-10-18):** RAG v2 adopted in config and verified. Branch `claude/charming-edison-sg0ehp`
(not merged). The owner's brief for this session: the best RAG system that stays free to run, up to $2.50
of OpenAI and $2.50 of Gemini. Spent: OpenAI $2.15, Gemini $1.92 (`eval/spend/ledger.jsonl`).

## Update, 2026-10-19: the relevance filter is in the service (D-017 to D-020)
Branch `ccr-fe4defc0-ysiv1i`. Read D-017 to D-020 first.
- **What it does:** search keeps 60 passages (cap 8 a document); the provider's `filter_model` (gpt-6-luna)
  rates each 0-3 (`prompts/filter-v1.md`, 20 a call, in parallel); the answer model gets the 20 rated highest.
  Config: `answer.filter` in `config/service.yaml`, `filter_model`/`filter_effort` per provider (Gemini has
  none, so a Gemini-keyed service doesn't filter). Code: `pipeline.filter_step`, `by_rating`, `parse_grades`.
- **What it shows:** a `search` event while the filter reads; the `retrieval` event's `filter` (status,
  model, read, kept, seconds) and `pool` (every passage read: search rank, rating, chosen or not; chosen ones
  are brief and point to `evidence` by `n`). The trail has a filter step and a table of all 60; Render's log
  records all 60 compactly (`service.app.log_view`).
- **Verified offline:** `econ verify-search` (`reports/search-verification.md`): same 60 passages, the
  measured prompt byte for byte, the same 20 from the measured ratings, the same judged recall.
- **Not yet done live:** the OpenAI account ran out of credit during D-019. After credit is added, ask one
  question through `econ ask --confirm` (or the deployed service) and check the filter event before relying
  on it: that is the first live call of the filter inside the service.
- **Spend so far:** OpenAI $2.88 of $3.50 (eval budget), Gemini $2.26 of $2.50.

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

## Update, 2026-10-19: the owner's decisions and the deployment (D-021)
- Adopted: gpt-6.1-sol answers. Kept: answer-v1 (answer-v2 not adopted: an internal team uses the service).
  Dropped: coverage calibration. The OpenAI account has credit again; ask the owner before every paid call.
- Live: Pages (`https://thomas-amann-ipaustralia.github.io/Econ/`, with the PDFs), Render
  (`https://econ-api-vk5f.onrender.com`, dense lane `ok`), Cloud Run. Render is evidence-only until the owner
  sets `OPENAI_API_KEY` there; the first question after that is the filter's live smoke test.

## Update, 2026-10-19 (later): tracing, the OCR repair, the front end (D-022)
- **Done:** the filter's first live call on Render passed. Langfuse tracing is built and tested (offline with
  the real SDK; live against a Langfuse project, then deleted). The scanned reports' garbled OCR is repaired
  (55 of 62 elements; index rebuilt, 602 judgments re-graded). The front end has a theme switch, gunmetal dark
  mode and a live process view of the trail.
- **For the owner:** create a Langfuse project and put `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` on
  Render (docs/deploy.md, "Tracing to Langfuse"); then set `tracing.required: true`. Merge to `main` to deploy
  the new index, the tracing and the front end.
- **Spend this round:** Gemini $0.26 of the $2 given, OpenAI about $0.06 of the $3 given.

## Update, 2026-10-19 (latest): slow answers, answer-v3 (D-024)
- **Streaming:** `answer.stream_drafts: true`; the answer's prose arrives as `draft` events (OpenAI only), so
  the first words show after about 6-12 s instead of 25-40 s. Code: `providers.OpenAIModel._stream`,
  `pipeline.answer_call`, `ProseReader`; UI `drawSoon`, `liveDraft`.
- **answer-v3** (schema `answer3`, with `follow_ups`) is adopted by the owner and in config; the UI shows
  follow-ups as buttons. Side by side with answer-v1: `reports/answers-v3-compare.md` (6 of 6 pass on both).
- **Measured:** first words at a median 18.7 s, whole answer 44.5 s (keyword search only, locally). The answer
  model's wait before its first word (6-19 s at medium effort) is the next thing to cut; `answer_effort: low`
  is proposed to the owner for a measurement (about US$0.20).
- **For the owner:** set `KEEP_WARM=true` (the keep-warm job has never run); align the Langfuse project.

## Update, 2026-10-19 (latest): answer-v4 (D-025)
- `answer.prompt: answer-v4` (answer-v3 without brevity, the owner's request). Not yet run live.
- Two-thirds of the answer model's output is the claims' quotes and restatements; citing by sentence number
  (the server fills in the quotes) is proposed to the owner in D-025, not built.

## Update, 2026-10-19 (latest): sentence citations and Copy (D-026)
- `answer.prompt: answer-v5`: the model cites `[passage.sentence]`; `econ.answer.cite` builds the claims and
  quotes. Measured on 6 questions: whole answer 50.2 s (v4) to 31.6 s, US$0.040 to US$0.027, 6 of 6 pass.
- Copy button on every finished answer (`copyAnswer` in `web/app.js`).
- Not yet deployed: merge to `main` (Render and Pages deploy from it). Then ask one question live and check
  `/api/health` shows prompt answer-v5 and spans exported.

## Update, 2026-10-19 (latest): reading an answer, and the conversation as JSON (D-030)
- Front end only. The answer's prose is underlined where it rests on claims and lighter where it is the
  assistant's own words (`lineParts`, the same rule as `cite._claim_text`); a marker opens its cited sentences
  under the paragraph (`quoteDrawer`). Each answer has an Answer tab and a "Claims made by the chatbot" tab
  (`claimsPanel`, `pickClaim`), which steps through the claims while the trail follows; the trail no longer
  lists claims.
- The conversation downloads or copies as JSON (`exportChat`, format `econ-chat-export/1`): everything shown
  except passage text. A change to the events the API sends should be reflected in `exportTurn`.
- Deploys with the next merge to `main` (Pages).

## Open items
1. **Langfuse keys on Render**: set and working (2026-10-19). The span counter on `/api/health` read 0 because
   the app was built twice; fixed on `claude/gracious-gates-x2zfot`, live once merged to `main`. Still the owner's:
   `tracing.required: true`.
2. **Tried and not adopted in grid v3 (D-016):** the fusion weight (flat), rerankers that read the notes
   (17M and 32M still harmful), plan-v3's answer-shaped query (level on dev, +0.022 on test with an interval
   that includes zero: the one idea worth re-testing on a larger set).
3. **The plan prompt's document map** must be updated when documents are added; so must the notes
   (`econ.kb.enrich`, about $0.14 a corpus).
4. **The filter's measurement (D-018) on the repaired index**: 189 changed calls, about US$0.15-0.20 of
   OpenAI; the owner's permission first (D-023).
5. Carried from v1: a persistent answer store (Render's log is the only record of answers so far).

## Conventions kept
- Grids and test sets committed before any number; deviations recorded as amendments before the data they
  affect (see grid retrieval-v2, amendment 1).
- Every paid call goes through `econ.evalr.llmcall` or `econ.evalr.judge` (cached, metered, capped).
- Next free decision number: **D-031**.
