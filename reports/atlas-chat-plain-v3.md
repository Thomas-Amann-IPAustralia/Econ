# The atlas chat in plain English: atlas-answer-v3 against v2 (atlas-smoke-v2)

**The owner's direction (4 November 2026):** loosen the atlas chat's language for readers who are not technical,
"less concerned with the language being as exact as the Econ chat", while the numbers check stays hard-coded and
every statement is still supported by evidence.

**What changed, and what didn't.** The check never required the prose to match its sources' wording: code copies
the cited sentences as the quotes, and checks them and every number. What made answers dense was the prompt
(atlas-answer-v2 asked for thoroughness, every figure with its period, and an id and strength label on every
finding). **atlas-answer-v3** keeps every evidence rule (only the passages; cite what you state; never a cause from an
association; Stage 3's outcome first; numbers exactly as a cited sentence gives them, on the cited line) and changes
how answers read: being easy to understand comes before matching the atlas's wording; rephrase freely, saying only what
the cited sentences support; a plain one-to-three-sentence answer first; usually 150 to 350 words; few numbers, each
explained in words; observation ids once, and strength in plain words; jargon translated or replaced. The check is
unchanged.

**Measured** on the same 20 needs as the smoke test (`eval/runs/atlas-smoke-v2/`; v2's answers are the smoke test's
final state, `eval/runs/atlas-smoke-v1/`). US$0.3384 for this run; US$1.3819 of the owner's US$2.00 over both.

| The check and coverage | atlas-answer-v2 | atlas-answer-v3 |
|---|---:|---:|
| Passed first time | 18 | 19 |
| Passed in the end | 20 | 20 |
| Flagged | 0 | 0 |
| Lookups and by-id citing their gold | 10/10 | 10/10 |
| Exploratory gold pages cited | 27/30 | 21/30 |
| Out of scope "not in the atlas" | 4/5 | 4/5 |
| Mean cost an answer | US$0.0212 | US$0.0169 |
| Mean seconds | 27.2 | 18.2 |

| How the answers read (the 15 in-scope needs, `econ.evalr.readability`) | atlas-answer-v2 | atlas-answer-v3 |
|---|---:|---:|
| Words an answer | 338 | 198 |
| Words a sentence | 19.3 | 18.7 |
| Sentences over 25 words | 21% | 18% |
| Reading ease (higher is easier) | 50.7 | 51.7 |
| Analysts' terms per 100 words | 2.28 | 0.43 |
| Numbers per 100 words | 4.55 | 3.70 |

v3's answers are 41% shorter, use a fifth of the analysts' terms, and passed the check first time on 19 of 20 (the
one retry, a36, cited no sentence for "2026" while saying the atlas covers a later edition of the GII). The reading-ease
score barely moves (7 of 15 answers score easier): it counts syllables and sentence length, and the atlas's
subject words (applications, organisations, standard patents) stay long. What it doesn't see is what changed most:
v2's "the hazard ratios for patents ending were 1.276 ... and 1.383" became v3's "more likely to end after grant—not
stay in force longer"; v2's "each standard-deviation step up in area advantage went with 1.717 times ..." became
"more advantaged areas tend to file more standard patents per person".

**The cost of brevity:** exploratory answers cite fewer of their gold pages (21/30 against 27/30): a shorter answer
ranges less widely. The reader can ask a follow-up, and each answer offers two or three.

**Read, every v3 answer in full.** None states an association as a cause. The nearest is a08 ("a strong sign of
applicants responding to the reforms"), inside a conclusion that says "rather than a proven causal effect". Five of the
freest paraphrases were compared with the sentences they cite (a02, a08, a26, a29, a33): each says what its sources
say; the loosest, a26's "half of universities' standard patent applications carry postcodes with no residents", drops
"with a filer's postcode", and the cited headline itself says "half". Out of scope: as v2 (four "not in the atlas",
the policy question declined with the fee evidence as a reading).

**Recommendation:** adopt **atlas-answer-v3** (with atlas-plan-v1 and atlas-filter-v1) instead of v2: it is what the
owner asked for, it passes the check more often, and it is faster and a little cheaper; the trade is breadth on broad
questions, which follow-ups recover. Configured as the candidate in `knowledge_bases.atlas`; adopting it is the
owner's (D-037, decision 5).
