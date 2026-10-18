# Retrieval grid v3: variants of the adopted setting

Grid `retrieval-v3` (eval/grids/retrieval-v3.yaml, committed before any number). Adopted setting `plan+q:luna-plan-v2/enriched/none`. Judgments `judged-v1`, topped up so every variant's top 10 is judged. Rule: A variant replaces the adopted setting only if its dev ndcg@10 exceeds the adopted setting's by more than 0.02 and, for a reranker, it reranks 50 passages within 2.5 s (ONNX float32, 4 vCPU, the latency method of v2, re-measured with the notes). If several qualify, the highest on dev. Test is reported for every variant with a paired bootstrap interval against the adopted setting.

**Outcome: `plan+q:luna-plan-v2/enriched/none`** (the adopted setting stays).

| Setting | Latency (50 passages) | Dev ndcg@10 | Test ndcg@10 | Test vs adopted [95% CI] | judged@10 | rel_recall@20 (test) |
|---|---|---|---|---|---|---|
| `plan+q:luna-plan-v2/enriched/none` |  | 0.726 | 0.679 | adopted | 1.000 | 0.705 |
| `plan+q:luna-plan-v2/enriched/none/a0.5` |  | 0.708 | 0.682 | +0.003 [-0.013, +0.018] | 1.000 | 0.706 |
| `plan+q:luna-plan-v2/enriched/none/a0.6` |  | 0.728 | 0.680 | +0.001 [-0.009, +0.011] | 1.000 | 0.704 |
| `plan+q:luna-plan-v2/enriched/none/a0.8` |  | 0.727 | 0.686 | +0.007 [-0.002, +0.017] | 1.000 | 0.698 |
| `plan+q:luna-plan-v2/enriched/none/a0.9` |  | 0.710 | 0.676 | -0.003 [-0.017, +0.011] | 1.000 | 0.691 |
| `plan+q:luna-plan-v2/enriched/ettin-17m/noted` | 2.3 s | 0.660 | 0.600 | -0.079 [-0.120, -0.037] | 1.000 | 0.637 |
| `plan+q:luna-plan-v2/enriched/ettin-32m/noted` | 5.2 s | 0.696 | 0.636 | -0.043 [-0.083, -0.003] | 1.000 | 0.659 |
| `plan+q:luna-plan-v2/enriched/ettin-68m/noted` | 11.5 s | 0.725 | 0.679 | +0.001 [-0.034, +0.036] | 1.000 | 0.682 |
| `plan+q:luna-plan-v3/enriched/none` |  | 0.727 | 0.701 | +0.022 [-0.005, +0.049] | 1.000 | 0.705 |

Latency for ettin-68m is the v2 measurement without notes (11.5 s); with notes it is slower still.
