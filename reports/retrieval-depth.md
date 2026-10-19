# Context depth: the adopted ranking at 20, 40, 60 passages

Grid `retrieval-depth` (eval/grids/retrieval-depth.yaml, committed before any number). Setting `plan+q:luna-plan-v2/enriched/none` with its context extended; the first 20 passages are the served context. 92 test needs. Judgments `judged-v1`, topped up so the 60-passage contexts are fully judged (judged@60 1.000).

## Evidence reached, by depth

| Needs | n | Metric | 20 passages | 40 passages | 60 passages |
|---|---|---|---|---|---|
| all | 92 | relevant (grade 2-3) reached | 0.665 | 0.777 | 0.818 |
| all | 92 | grade 3 reached | 0.757 | 0.822 | 0.852 |
| all | 92 | precision | 0.372 | 0.275 | 0.236 |
| all | 92 | passages (mean) | 19.1 | 34.8 | 46.4 |
| all | 92 | tokens (mean) | 4,930 | 8,931 | 11,862 |
| silver | 59 | relevant (grade 2-3) reached | 0.766 | 0.834 | 0.854 |
| silver | 59 | grade 3 reached | 0.854 | 0.889 | 0.896 |
| silver | 59 | precision | 0.299 | 0.211 | 0.183 |
| silver | 59 | passages (mean) | 18.8 | 33.3 | 43.5 |
| silver | 59 | tokens (mean) | 4,895 | 8,571 | 11,136 |
| explore | 33 | relevant (grade 2-3) reached | 0.484 | 0.674 | 0.754 |
| explore | 33 | grade 3 reached | 0.582 | 0.701 | 0.773 |
| explore | 33 | precision | 0.502 | 0.388 | 0.329 |
| explore | 33 | passages (mean) | 19.5 | 37.5 | 51.7 |
| explore | 33 | tokens (mean) | 4,994 | 9,576 | 13,160 |

## Precision of each band (grade 2-3 share of the passages added)

| Needs | 1-20 | 21-40 | 41-60 |
|---|---|---|---|
| all | 0.371 | 0.139 | 0.084 |
| silver | 0.295 | 0.056 | 0.023 |
| explore | 0.501 | 0.259 | 0.162 |

## Gains over 20 passages (paired, test needs)

| Needs | Depth | relevant reached: difference [95% CI] |
|---|---|---|
| all | 40 | +0.112 [+0.085, +0.139] |
| all | 60 | +0.153 [+0.118, +0.188] |
| silver | 40 | +0.068 [+0.041, +0.099] |
| silver | 60 | +0.088 [+0.057, +0.121] |
| explore | 40 | +0.190 [+0.150, +0.231] |
| explore | 60 | +0.269 [+0.210, +0.327] |

## Breadth rules: a deeper context only for broad questions

| Rule | Needs given the deeper context | relevant reached (all) | silver | explore | passages (mean) | tokens (mean) |
|---|---|---|---|---|---|---|
| always 20 | none | 0.665 | 0.766 | 0.484 | 19.1 | 4,930 |
| `oracle` | 0/59 silver, 33/33 explore | 0.762 | 0.766 | 0.754 | 30.6 | 7,859 |
| `plan_queries` | 6/59 silver, 15/33 explore | 0.721 | 0.783 | 0.610 | 27.0 | 6,942 |
| always 60 | all | 0.818 | 0.854 | 0.754 | 46.4 | 11,862 |

## How to read these numbers

- Recall is the share of a need's judged grade-2/3 passages in the context. Passages no setting ever ranked were never judged, so every recall is an upper bound; the top-up found new relevant passages, so the 20-passage figure is below the one reported in D-013.
- The per-document cap (8) and the first stage's depth (50 a query) stop some contexts short: 53 of 92 needs have fewer than 60 passages (15 of 33 exploratory).
- Exploratory needs with more relevant passages than the deepest context holds: 1 of 33.
- Retrieval only. Whether the answer model uses the extra passages, and what they cost in latency, needs an end-to-end run.
