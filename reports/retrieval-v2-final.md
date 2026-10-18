# Retrieval grid v2: the choice against the baseline on test

Baseline `plan:luna-plan-v1/plain/none` (the service today); chosen `plan+q:luna-plan-v2/enriched/none`. Judgments `judged-v1`, topped up so both settings' 20-passage contexts are fully judged on every need.

judged@20 on test: baseline 1.000, chosen 1.000.

| Needs | Metric | n | Baseline | Chosen | Difference | 95% CI | p (Holm) |
|---|---|---|---|---|---|---|---|
| all | ndcg@10 | 92 | 0.597 | 0.682 | +0.085 | [+0.046, +0.123] | 0.002 |
| all | ndcg@20 | 92 | 0.616 | 0.694 | +0.078 | [+0.043, +0.112] | 0.002 |
| all | rel_recall@20 | 92 | 0.623 | 0.715 | +0.092 | [+0.053, +0.134] | 0.002 |
| all | p@20 | 92 | 0.301 | 0.367 | +0.066 | [+0.040, +0.094] | 0.002 |
| all | gold_recall@20 | 59 | 0.814 | 0.887 | +0.073 | [+0.017, +0.141] | 0.158 |
| all | gold_recall@4k_tok | 59 | 0.788 | 0.881 | +0.093 | [+0.025, +0.169] | 0.158 |
| silver | ndcg@10 | 59 | 0.625 | 0.713 | +0.088 | [+0.043, +0.133] | 0.006 |
| silver | ndcg@20 | 59 | 0.651 | 0.728 | +0.077 | [+0.034, +0.121] | 0.006 |
| silver | rel_recall@20 | 59 | 0.699 | 0.798 | +0.099 | [+0.045, +0.156] | 0.004 |
| silver | p@20 | 59 | 0.234 | 0.292 | +0.058 | [+0.031, +0.089] | 0.002 |
| silver | gold_recall@20 | 59 | 0.814 | 0.887 | +0.073 | [+0.017, +0.141] | 0.158 |
| silver | gold_recall@4k_tok | 59 | 0.788 | 0.881 | +0.093 | [+0.025, +0.169] | 0.158 |
| explore | ndcg@10 | 33 | 0.548 | 0.627 | +0.079 | [+0.008, +0.146] | 0.158 |
| explore | ndcg@20 | 33 | 0.553 | 0.632 | +0.079 | [+0.023, +0.136] | 0.064 |
| explore | rel_recall@20 | 33 | 0.487 | 0.566 | +0.080 | [+0.031, +0.132] | 0.025 |
| explore | p@20 | 33 | 0.420 | 0.501 | +0.081 | [+0.033, +0.133] | 0.025 |

## Robustness: the stage-1 rule on every judgment

Re-run on all judgments (pool and top-up), the rule chooses `plan+q:luna-plan-v2/enriched/none` (the same setting). Best five on dev by ndcg@10: `plan+q:luna-plan-v2/enriched/none` 0.727; `plan:luna-plan-v2/enriched/ettin-68m` 0.726; `plan:flashlite-plan-v2/enriched/ettin-68m` 0.719; `plan:luna-plan-v2/plain/ettin-68m` 0.710; `plan:luna-plan-v1/enriched/ettin-68m` 0.707.
