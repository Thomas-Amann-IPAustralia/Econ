# A relevance filter: 60 passages read, the best 20 passed

Grid `retrieval-filter` (eval/grids/retrieval-filter.yaml, committed before any filter call). Filter `filter-v1` on gpt-6-luna (low effort) over the adopted setting's 60-passage contexts (fully judged), 92 test needs; 0 kept the first-stage order after a failed filter call.

Rule fixed in advance: On the exploratory test needs, the filtered 20 reach at least 0.59 of the relevant passages (half of the oracle filter's gain over the adopted 0.491); on the silver needs they lose no more than 0.02 against the adopted 0.765; and the filter step (the slowest of a need's parallel calls) has a median standard-tier latency of 5 s or less.

## All test needs (n = 92)

| Context | relevant reached | grade 3 reached | relevant documents | ndcg@10 | precision | passages | tokens |
|---|---|---|---|---|---|---|---|
| Adopted, 20 passages (served today) | 0.667 | 0.748 | 0.838 | 0.672 | 0.367 | 19.1 | 4,945 |
| **Filter, 60 read, 20 passed** | 0.762 | 0.834 | 0.926 | 0.846 | 0.443 | 19.1 | 5,009 |
| Oracle filter (the judge's grades), 60 to 20 | 0.792 | 0.846 | 0.948 | 0.919 | 0.471 | 19.1 | 4,991 |
| Adopted, 40 passages | 0.777 | 0.822 | 0.933 | 0.672 | 0.271 | 34.8 | 8,945 |
| Filter: passages it grades 2-3, up to 40 | 0.777 | 0.845 | 0.931 | 0.749 | 0.597 | 15.7 | 4,110 |
| Adopted, 60 passages | 0.818 | 0.851 | 0.958 | 0.672 | 0.233 | 46.3 | 11,837 |

## Exploratory (n = 33)

| Context | relevant reached | grade 3 reached | relevant documents | ndcg@10 | precision | passages | tokens |
|---|---|---|---|---|---|---|---|
| Adopted, 20 passages (served today) | 0.491 | 0.566 | 0.767 | 0.618 | 0.501 | 19.5 | 5,004 |
| **Filter, 60 read, 20 passed** | 0.635 | 0.728 | 0.892 | 0.831 | 0.648 | 19.5 | 5,114 |
| Oracle filter (the judge's grades), 60 to 20 | 0.694 | 0.763 | 0.930 | 0.912 | 0.708 | 19.5 | 5,157 |
| Adopted, 40 passages | 0.682 | 0.707 | 0.932 | 0.618 | 0.387 | 37.4 | 9,578 |
| Filter: passages it grades 2-3, up to 40 | 0.697 | 0.769 | 0.922 | 0.716 | 0.657 | 22.9 | 5,974 |
| Adopted, 60 passages | 0.760 | 0.776 | 0.958 | 0.618 | 0.329 | 51.5 | 13,122 |

## Silver lookups (n = 59)

| Context | relevant reached | grade 3 reached | relevant documents | ndcg@10 | precision | passages | tokens |
|---|---|---|---|---|---|---|---|
| Adopted, 20 passages (served today) | 0.765 | 0.850 | 0.877 | 0.702 | 0.292 | 18.8 | 4,912 |
| **Filter, 60 read, 20 passed** | 0.833 | 0.893 | 0.945 | 0.854 | 0.328 | 18.8 | 4,950 |
| Oracle filter (the judge's grades), 60 to 20 | 0.847 | 0.893 | 0.958 | 0.924 | 0.338 | 18.8 | 4,899 |
| Adopted, 40 passages | 0.830 | 0.886 | 0.933 | 0.702 | 0.206 | 33.4 | 8,590 |
| Filter: passages it grades 2-3, up to 40 | 0.822 | 0.887 | 0.935 | 0.768 | 0.563 | 11.7 | 3,068 |
| Adopted, 60 passages | 0.851 | 0.893 | 0.958 | 0.702 | 0.179 | 43.4 | 11,119 |

## The filter against the adopted 20 (paired, 95% bootstrap interval)

| Needs | Metric | Difference | 95% CI | p |
|---|---|---|---|---|
| all | rel_recall | +0.096 | [+0.070, +0.122] | 0.000 |
| all | doc_coverage | +0.088 | [+0.058, +0.120] | 0.000 |
| all | ndcg@10 | +0.174 | [+0.143, +0.206] | 0.000 |
| explore | rel_recall | +0.145 | [+0.107, +0.183] | 0.000 |
| explore | doc_coverage | +0.125 | [+0.075, +0.177] | 0.000 |
| explore | ndcg@10 | +0.213 | [+0.161, +0.268] | 0.000 |
| silver | rel_recall | +0.068 | [+0.038, +0.102] | 0.000 |
| silver | doc_coverage | +0.068 | [+0.031, +0.109] | 0.001 |
| silver | ndcg@10 | +0.152 | [+0.115, +0.190] | 0.000 |

## Agreement and cost

- The filter's grades against the judge's, on every passage it read: quadratic kappa 0.76; of the passages the filter grades 2-3, 59% the judge grades 2-3; of the judge's 2-3 passages, the filter grades 92% 2-3.
- Latency of the filter step at the standard tier (8 needs, a need's calls in parallel): median 4.4 s, slowest 7.1 s. At the Flex tier the median was 5.1 s.
- Spend on this run: $0.089 for the Flex filter calls, plus the standard-tier probe (in the ledger, purpose `filter:...:latency`).

**Against the rule: met** (exploratory 0.635 against 0.59; silver 0.833 against 0.745; median latency 4.4 s against 5 s).

## How to read these numbers

- Every passage in these contexts is judged, so recall here is exact for the passages the search found; relevant passages no setting ever ranked are not counted.
- The oracle filter uses the judge's own grades, so it is the ceiling for this design, not a result.
- Retrieval only: whether answers use the better 20 needs an end-to-end run.
