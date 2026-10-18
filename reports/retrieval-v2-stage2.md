# Retrieval grid v2, stage 2: the per-document cap

On stage 1's choice `plan+q:luna-plan-v2/enriched/none`. Rule: keep cap 8 unless another cap beats it by more than the margin on dev. **Chosen: `plan+q:luna-plan-v2/enriched/none`.**

| Setting | Dev ndcg@10 | Test ndcg@10 | judged@10 (test) | rel_recall@20 (test) |
|---|---|---|---|---|
| `plan+q:luna-plan-v2/enriched/none` | 0.727 | 0.682 | 1.000 | 0.715 |
| `plan+q:luna-plan-v2/enriched/none/cap5` | 0.707 | 0.656 | 1.000 | 0.656 |
| `plan+q:luna-plan-v2/enriched/none/cap3` | 0.669 | 0.618 | 1.000 | 0.590 |
