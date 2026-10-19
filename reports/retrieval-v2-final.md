# Retrieval grid v2: the choice against the baseline on test

Baseline `plan:luna-plan-v1/plain/none` (the service today); chosen `plan+q:luna-plan-v2/enriched/none`. Judgments `judged-v1`, topped up so both settings' 20-passage contexts are fully judged on every need.

judged@20 on test: baseline 1.000, chosen 1.000.

| Needs | Metric | n | Baseline | Chosen | Difference | 95% CI | p (Holm) |
|---|---|---|---|---|---|---|---|
| all | ndcg@10 | 92 | 0.592 | 0.678 | +0.086 | [+0.049, +0.123] | 0.002 |
| all | ndcg@20 | 92 | 0.598 | 0.677 | +0.079 | [+0.047, +0.112] | 0.002 |
| all | rel_recall@20 | 92 | 0.580 | 0.665 | +0.085 | [+0.049, +0.123] | 0.002 |
| all | p@20 | 92 | 0.303 | 0.372 | +0.069 | [+0.043, +0.096] | 0.002 |
| all | gold_recall@20 | 59 | 0.814 | 0.887 | +0.073 | [+0.017, +0.141] | 0.158 |
| all | gold_recall@4k_tok | 59 | 0.788 | 0.881 | +0.093 | [+0.025, +0.169] | 0.158 |
| silver | ndcg@10 | 59 | 0.617 | 0.709 | +0.092 | [+0.049, +0.136] | 0.003 |
| silver | ndcg@20 | 59 | 0.634 | 0.715 | +0.080 | [+0.041, +0.121] | 0.003 |
| silver | rel_recall@20 | 59 | 0.670 | 0.766 | +0.096 | [+0.048, +0.149] | 0.002 |
| silver | p@20 | 59 | 0.236 | 0.299 | +0.063 | [+0.038, +0.092] | 0.002 |
| silver | gold_recall@20 | 59 | 0.814 | 0.887 | +0.073 | [+0.017, +0.141] | 0.158 |
| silver | gold_recall@4k_tok | 59 | 0.788 | 0.881 | +0.093 | [+0.025, +0.169] | 0.158 |
| explore | ndcg@10 | 33 | 0.547 | 0.622 | +0.075 | [+0.008, +0.141] | 0.158 |
| explore | ndcg@20 | 33 | 0.533 | 0.610 | +0.077 | [+0.022, +0.134] | 0.076 |
| explore | rel_recall@20 | 33 | 0.420 | 0.484 | +0.064 | [+0.018, +0.114] | 0.076 |
| explore | p@20 | 33 | 0.423 | 0.502 | +0.079 | [+0.026, +0.136] | 0.063 |

## Robustness: the stage-1 rule on every judgment

Re-run on all judgments (pool and top-up), the rule chooses `plan+q:luna-plan-v2/enriched/none` (the same setting). Best five on dev by ndcg@10: `plan+q:luna-plan-v2/enriched/none` 0.727; `plan:luna-plan-v2/enriched/ettin-68m` 0.720; `plan:flashlite-plan-v2/enriched/ettin-68m` 0.712; `plan:luna-plan-v2/plain/ettin-68m` 0.707; `plan:flashlite-plan-v1/enriched/ettin-68m` 0.706.
