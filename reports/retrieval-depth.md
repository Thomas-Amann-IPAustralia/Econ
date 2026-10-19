# Context depth: the adopted ranking at 20, 40, 60 passages

Grid `retrieval-depth` (eval/grids/retrieval-depth.yaml, committed before any number). Setting `plan+q:luna-plan-v2/enriched/none` with its context extended; the first 20 passages are the served context. 92 test needs. Judgments `judged-v1`, topped up so the 60-passage contexts are fully judged (judged@60 1.000).

## Evidence reached, by depth

| Needs | n | Metric | 20 passages | 40 passages | 60 passages |
|---|---|---|---|---|---|
| all | 92 | relevant (grade 2-3) reached | 0.667 | 0.777 | 0.818 |
| all | 92 | grade 3 reached | 0.748 | 0.822 | 0.851 |
| all | 92 | precision | 0.367 | 0.271 | 0.233 |
| all | 92 | passages (mean) | 19.1 | 34.8 | 46.3 |
| all | 92 | tokens (mean) | 4,945 | 8,945 | 11,837 |
| silver | 59 | relevant (grade 2-3) reached | 0.765 | 0.830 | 0.851 |
| silver | 59 | grade 3 reached | 0.850 | 0.886 | 0.893 |
| silver | 59 | precision | 0.292 | 0.206 | 0.179 |
| silver | 59 | passages (mean) | 18.8 | 33.4 | 43.4 |
| silver | 59 | tokens (mean) | 4,912 | 8,590 | 11,119 |
| explore | 33 | relevant (grade 2-3) reached | 0.491 | 0.682 | 0.760 |
| explore | 33 | grade 3 reached | 0.566 | 0.707 | 0.776 |
| explore | 33 | precision | 0.501 | 0.387 | 0.329 |
| explore | 33 | passages (mean) | 19.5 | 37.4 | 51.5 |
| explore | 33 | tokens (mean) | 5,004 | 9,578 | 13,122 |

## Precision of each band (grade 2-3 share of the passages added)

| Needs | 1-20 | 21-40 | 41-60 |
|---|---|---|---|
| all | 0.367 | 0.137 | 0.084 |
| silver | 0.290 | 0.054 | 0.025 |
| explore | 0.499 | 0.258 | 0.158 |

## Gains over 20 passages (paired, test needs)

| Needs | Depth | relevant reached: difference [95% CI] |
|---|---|---|
| all | 40 | +0.110 [+0.083, +0.137] |
| all | 60 | +0.151 [+0.117, +0.187] |
| silver | 40 | +0.065 [+0.037, +0.096] |
| silver | 60 | +0.086 [+0.053, +0.121] |
| explore | 40 | +0.191 [+0.150, +0.231] |
| explore | 60 | +0.269 [+0.211, +0.327] |

## Breadth rules: a deeper context only for broad questions

| Rule | Needs given the deeper context | relevant reached (all) | silver | explore | passages (mean) | tokens (mean) |
|---|---|---|---|---|---|---|
| always 20 | none | 0.667 | 0.765 | 0.491 | 19.1 | 4,945 |
| `oracle` | 0/59 silver, 33/33 explore | 0.763 | 0.765 | 0.760 | 30.6 | 7,857 |
| `plan_queries` | 6/59 silver, 15/33 explore | 0.722 | 0.783 | 0.614 | 26.9 | 6,947 |
| always 60 | all | 0.818 | 0.851 | 0.760 | 46.3 | 11,837 |

## How to read these numbers

- Recall is the share of a need's judged grade-2/3 passages in the context. Passages no setting ever ranked were never judged, so every recall is an upper bound; the top-up found new relevant passages, so the 20-passage figure is below the one reported in D-013.
- The per-document cap (8) and the first stage's depth (50 a query) stop some contexts short: 55 of 92 needs have fewer than 60 passages (15 of 33 exploratory).
- Exploratory needs with more relevant passages than the deepest context holds: 0 of 33.
- Retrieval only. Whether the answer model uses the extra passages, and what they cost in latency, needs an end-to-end run.
