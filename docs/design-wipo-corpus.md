# The WIPO reports as a second corpus (D-033)

For the owner. It covers what was built, what the WIPO reports need that IP Australia's don't, how the two
collections meet, whether 40 passages to the answer model is sensible, and what is still the owner's call.
The decision record is D-033 in `docs/decisions.md`.

## The request (the owner, 2026-10-19)

WIPO's reports are in the R2 bucket under `WIPO/`, with a Global Innovation Index workbook (deferred). The
owner asked for an on/off switch in the UI. When it is on, search should double: 60 candidates from the WIPO
reports and 60 from IP Australia's go to the Luna filter, 120 in all. The owner asked for the WIPO reports
to be treated as a corpus of their own, since their graphs may need different handling, and asked whether
that needs a multimodal embedding model. The owner also asked about chunk size, how the two sets of
passages interact, whether 40 passages can meaningfully go to the answer model, and how else to handle
volume and quality.

## Status

- **Built and tested; no WIPO documents yet.** Corpora in config, per-corpus ingestion (`--corpus wipo`), the
  service's two-collection search, the filter over both, the switch, collection labels, the export, and new
  prompt versions for combined questions. 140 tests pass (11 new). The switch was checked in a headless
  browser against a local API with a throwaway index of 12 WIPO pages (below).
- **Blocked:** the R2 keys in this environment are refused for every request (list, head and list-buckets
  on both endpoints: `AccessDenied`). The `WIPO/` folder could not be listed, so `config/sources-wipo.yaml`
  has no entries yet. Until there is a WIPO index, the service lists WIPO as not available and the switch
  shows as "Include WIPO reports (coming)", disabled.
- **Probe:** to ground the design, World Intellectual Property Indicators 2024 was downloaded from wipo.int
  into a scratch folder. Pages 19 to 24 (prose with charts) and 40 to 45 (the statistical annex) were parsed
  with the pipeline's own Docling settings and chunked with the adopted strategy. Nothing from the probe is
  committed.

## How it is built

**Each corpus stands alone up to search.** `config/pipeline.yaml` lists the corpora. Each has its own
registry (`config/sources-wipo.yaml`), its own R2 folder (`WIPO/`), its own library (`library/wipo/`:
elements, chunks, notes, index), its own manifests (`manifests/wipo/<stage>/`) and its own context-note
prompt (`prompts/eval/enrich-wipo-v1.md`). Every stage takes `--corpus wipo`. IP Australia's corpus keeps
every path it had. The reasons:

- **Keyword statistics.** BM25 weights a word by how rare it is in its collection. In one combined index,
  WIPO's statistics-heavy text would change the weight of words like "applications" or "Australia" for IP
  Australia's passages, so search with the switch off would no longer be the search that was measured.
- **Boilerplate.** The chunker drops paragraphs that recur in three or more documents (licence notices and
  similar). Counted across both collections, an IP Australia paragraph could cross that line because of a WIPO
  document. Counted within each collection, it cannot.
- **The switch off means nothing changed.** A test checks this. The same question with and without the
  WIPO index loaded gives the same 60 passages, scores and ratings, and sends the same prompts byte for byte.

**The service loads both indexes side by side.** The rows are concatenated, IP Australia's first, and the
vectors are stacked. Each corpus keeps its own BM25 (`StackedBM25`), and every search is limited to one
corpus. The fetch stage owns a folder: `fetch --corpus wipo` lists `WIPO/`, and IP Australia's fetch ignores
it. An object can be listed as `deferred` (the workbook) so it is acknowledged without being fetched. A failed
fetch writes every unregistered key to its manifest, so the registry can be written from it.

**A question with the switch on** (`corpora: ["wipo"]` on `/api/ask`, or `econ ask --also wipo`):

1. The plan uses `plan-v4`, which describes both collections. It tells the planner that country and office
   names matter in WIPO's reports and that "Australia" does not in IP Australia's.
2. Each query is searched in each collection separately. Each gives its own top 60, with the cap of 8
   passages a document applied within the collection.
3. The two lists are interleaved (IP Australia's 1st, WIPO's 1st, IP Australia's 2nd, …), so a rating tie
   never favours one collection. The filter (`filter-v2`) rates all 120 on one scale, 20 to a call with all
   six calls in parallel. Each passage names its publisher.
4. The answer model gets the 20 rated highest, then any further passages rated 2 or 3, up to 40
   (`answer.combined`: `keep_min 20`, `keep_max 40`, `keep_grade 2`). If the filter fails, it gets the first
   20 of the interleaved list, 10 from each collection.
5. The answer uses `answer-v6`: answer-v5 with each passage's publisher named. The model is told to keep the
   publishers apart, to give and cite both figures when they differ, and that it need not use every passage.
   The check is unchanged.
6. The trail labels every passage with its collection ("IP Australia", "WIPO"). The pool table lists all 120,
   each ranked within its own collection. The export records `corpora` and each passage's `corpus` and
   `publisher`.

The PDF viewer outlines a passage only for PDFs on the Pages site. WIPO's are not there
(`pdfs_on_site: false`), because publishing them is the owner's call. A WIPO passage's "Show on p. N" links
to WIPO's own copy at that page instead. When WIPO's reports are available, the footer adds a line crediting
WIPO as the source.

## Charts: what a RAG system can do with them

There are three ways to handle charts:

1. **Use the text around the chart.** The title, notes, source line and the prose that discusses the chart
   are searched like any other text. This is free and deterministic, and everything stays quotable.
2. **Turn the chart into text at ingestion.** A vision model writes a description of each chart, or reads
   its values into a table, and that text is indexed. This is a one-off paid step per chart. The text is
   written by a model, not by WIPO.
3. **Multimodal retrieval.** Page images are embedded (ColPali-style page embedders, or multimodal
   embedding APIs), and the answer model is shown the image. That needs a GPU-class model or a paid API on
   every query, plus a third search lane. The answer would rest on an image.

**What the probe showed about WIPO's charts.** They are vector graphics. Docling recognises each one as a
picture and leaves out its insides, so axis ticks and labels don't leak into the text. What survives is the
chart's one-line takeaway headline (for example "China rejected more than half a million patent
applications in 2023"), its numbered title, its note and its source line. The prose beside the chart states
the key figures. Figure 1.8's data is in the text as "China (5 million) had the highest number of patents in
force, followed by the US (3.5 million), Japan (2.1 million)…". The statistical annex is mostly tables, and
Docling extracts them verbatim as tables, so they can be cited. Charts that appear only in the annex (A31 and
A32 in the probe) leave just their title and note.

**Recommendation: no multimodal embedding model now.** The system's promise is that every claim cites
sentences copied word for word from a publication, and code checks them. Values read off a chart by a model
can't meet that, and neither can an image. Most of what WIPO's charts say is already in text: in the prose,
in the annex tables and in the headlines. A multimodal lane would also cost money or a GPU on every
question, and nothing in the test set could measure it. Do this instead, in order:

1. **Free: keep each chart's words searchable.** Under the adopted strategy a chunk's searchable text has
   no heading prefix, so a chart-only chunk whose title sits in its section path is searchable only through
   its note. In the probe, 4 of 39 chunks were just a "Note: …" line. For WIPO, put the figure or table title
   into the searchable text of the chunks that need it. Keep the picture's box on the chunk, so that "Show on
   page" outlines the chart itself and the reader sees it.
2. **Cheap and paid, search only: a description of each chart.** A vision model would describe each chart:
   what it plots, the series and the visible ranking or trend. The description is used exactly like the
   context notes: search only, never evidence, never shown as fact. At gemini-3.8-flash prices this is about
   US$0.002 a chart, so about US$2 per 1,000 charts. It needs the owner's permission, and it is worth doing
   only if the measurement shows chart-only facts being missed.
3. **Not recommended:** model-read chart values used as citable evidence, or page-image retrieval.

## Chunk size and the other WIPO-specific choices

- **Prose: keep the adopted chunking** (structure-aware, up to 384 tokens). In the probe, WIPO's headlines
  became section breaks, so chunks are single-topic (median 307 tokens, largest 382). That suits search.
- **Tables need their own treatment.** 17 of the 39 probe chunks were pieces of four annex tables. A
  13-column table split into 7 chunks of one to three rows each, every one repeating a header of about 100
  tokens. Two options to measure: one chunk per row with the table title and column names spelled into it
  ("Computer technology: 2012 152,054; 2017 232,335; 2022 420,634; share 12.4%"), or a larger token budget
  for tables. The full WIPI annex runs to more than 100 pages, so without a fix table pieces will dominate
  the corpus.
- **The per-document cap.** Search keeps at most 8 passages from one document. WIPO's reports are long
  (WIPI 2024 is 194 pages). With fewer than 8 WIPO documents, the cap stops the WIPO pool from reaching 60.
  The probe had only one document and gave 8 passages. Once the registry is known, the cap for WIPO may need
  to rise.
- **Annual editions repeat.** WIPI-style series restate the same indicators every year, and IP Australia's
  reports quote WIPO's statistics (the probe's top passage was an IP Report's "Source: World Intellectual
  Property Organization, IP Statistics data center"). Collapsing near-duplicates before the filter is a free
  improvement to test.

These are chunking choices, which the owner delegated (D-005). They will still be measured before adoption,
and that needs a WIPO test set (below).

## How the two collections meet

- **Separate until the filter.** Searching apart keeps each collection's ranking as its own index gives it.
  A larger, statistics-dense WIPO collection can't crowd IP Australia's passages out of the 120, and the
  reverse holds too.
- **One scale at the filter, no quota after it.** A fixed 20 + 20 split would force WIPO passages into an
  answer about, say, Queensland's trade mark filings, and force IP Australia passages into a question about
  China. The filter's rating decides, and the trail shows all 120, so a reader can see what each collection
  offered.
- **Publishers named, figures kept apart.** The two publishers count differently: WIPO counts by receiving
  office and by applicant's origin on its own definitions and with publication lags, while IP Australia counts
  from its own administrative data. answer-v6 says whose figure each is, never presents a worldwide figure as
  Australia's, and gives both figures, cited, when they differ.

## Can 40 passages go to the answer model and still give a good answer?

Mechanically, yes. With 20 passages, answer-v5 used about 8,500 input tokens and cost US$0.027 a question
(D-026). Forty passages is about 15,000 input tokens, a small fraction of gpt-6.1-sol's context. That costs
about US$0.013 more in input, plus the filter's six calls instead of three (about US$0.002 more). Expect
about US$0.04 to US$0.05 a question with the switch on and 40 kept. The daily cap of US$2 then covers about
40 such questions. Latency: the filter's calls run in parallel, so it stays about 4 to 10 s. Reading 15,000
tokens adds a second or two; a longer answer adds more.

Whether the answer stays good is the real question, and it has not been measured. What is known:

- **More passages reach more of a broad question's evidence.** D-017, on the judged test set, before the
  filter: exploratory questions' relevant evidence reached was 0.49 at 20 passages, 0.68 at 40 and 0.76 at
  60. Fact-finding questions gained little (0.77 to 0.85).
- **The risks of a long context:**
  - Models attend less to passages in the middle of a long context. Ordering best-rated first puts the
    weakest passages there.
  - Since answer-v4 there is no brevity instruction, so the answer may try to use everything and grow
    longer and slower. answer-v6 says it needn't.
  - Near-duplicates and conflicting figures across publishers and years become more common.

That is why the adopted rule is adaptive rather than a flat 40. A lookup keeps the usual 20, and a broad
question gets up to 40 when the filter rates that many useful. Setting `keep_max` to 20 gives a flat 20, and
setting `keep_min` to 40 gives a flat 40. Both are one-line config changes.

## Other ways to handle volume and quality, in the order worth trying

1. Near-duplicate collapse across collections and editions before the filter (free).
2. The WIPO table and figure-title chunking above (free).
3. A breadth flag from the plan (D-017's suggestion): broad questions get 40, lookups 20, decided before the
   filter rather than from its ratings.
4. The chart descriptions as search-only notes (paid, one-off).
5. For very broad questions, answering in two passes: one note per collection, then a synthesis. This is
   slower and dearer, and not needed unless 40 passages proves too many.

## Measuring it (needs the owner's permission to spend)

The judged test set covers only IP Australia's documents. A WIPO test set needs three kinds of question:

- WIPO fact lookups ("How many patents were in force worldwide in 2023?");
- comparisons ("How does Australia's grant rate compare with other offices?");
- Australia-only controls, to check that WIPO passages don't push out the right answer.

Write the needs first, as before, then judge with the Gemini grader (a different family from the answer
model). Estimated costs:

| Step | Estimate |
|---|---|
| WIPO context notes (gpt-6-luna) | about US$0.14 per 1,900 chunks; `econ enrich --corpus wipo` prints the estimate before any call |
| Judging (60 needs × 120 passages, Batch) | about US$1.20 |
| End-to-end answers on 60 needs | about US$3 |
| Blind pairwise judging | about US$0.50 |

## The Global Innovation Index workbook (deferred)

The workbook holds indicators by economy and year, which is data, not prose. Embedding its rows as passages
works poorly. Two options for later, both traceable:

- A small lookup tool the plan can call ("Australia's GII rank in 2025"), with the cited source being the
  sheet, row and column.
- Deterministic sentences generated from each economy's row ("Australia, 2025: GII rank 23; Human capital and
  research pillar score …"), each citable back to its cells.

The registry lists the workbook as `deferred` once its key is known.

## To ingest the WIPO reports (next session)

1. **The owner:** fix the R2 key in this environment. It is refused for every call; a read-only token for
   `econ-knowledge` is what `docs/deploy.md` describes. The Pages workflow uses its own copy of the R2
   secrets, which should be checked too if the token was rotated.
2. Run `econ fetch --corpus wipo`. It fails and lists every object. Write the registry entries (`wipo-…`
   doc_ids, titles, years, series, WIPO's URLs) and the workbook as `deferred`.
3. Run `econ sweep --corpus wipo` and `econ parse --corpus wipo --workers 2`. Docling took 5 to 11 s a page
   in the probe, so a 194-page report takes 20 to 30 minutes. Any allowlist entries go to the owner as
   proposals.
4. Check the WIPO chunking choices (tables, figure titles, the cap), then run `econ chunk --corpus wipo`.
5. Run `econ enrich --corpus wipo` for the estimate, get the owner's go-ahead, then run it with `--confirm`.
6. Run `econ index --corpus wipo`. `library/wipo/index/` is committed. Render offers the switch once it is
   deployed.
7. Write plan-v5 with the WIPO documents listed, as plan-v2 lists IP Australia's.
8. **The owner:** decide whether WIPO's PDFs go on the Pages site (`pdfs_on_site: true`). Then measure, as
   above, before relying on the combined mode.
