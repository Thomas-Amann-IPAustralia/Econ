# End-to-end answers v2: the relevance filter's 20 against the adopted 20

Grid `answers-v2` (eval/grids/answers-v2.yaml, committed before any answer on the filtered contexts). 57 test needs (the answers-v1 set). B is the adopted retrieval (`plan+q:luna-plan-v2/enriched/none`, 20 passages; answers-v1's B answers, reused). C is the same 60-passage context rated by filter-v1 (D-018), the 20 rated highest. Both answered by gpt-6.1-sol at medium effort with answer-v1 on the Flex tier, through the check and its retry.

**Deviation from the grid, disclosed:** 3 of the 60 needs are left out of both settings (explore-evidence-1, explore-compare-7, explore-strategy-2): every attempt at C's answer ended in a provider error (HTTP 502, Flex unavailable, then HTTP 429 `credit_balance_exhausted`: the OpenAI account ran out of credit), so no answer exists to compare. The owner chose to finish on the rest. No answer that exists was dropped.

## The check

| | B | C |
|---|---|---|
| Passed (after at most one retry) | 57/57 | 57/57 |
| Passed first time | 0.982 | 1.000 |
| Coverage complete / partial / not_in_kb | 49 / 8 / 0 | 52 / 5 / 0 |
| Cost per answer (Flex) | $0.0120 | $0.0111 |

## Grounding against the judgments

Unjudged cited passages: B 0, C 0 (every C passage lies in a fully judged 60-passage context).

| Measure | Needs | B | C | C - B [95% CI] |
|---|---|---|---|---|
| Distinct relevant passages cited (grade 2-3) | all (57) | 3.70 | 4.09 | +0.39 [+0.07, +0.70] |
| Distinct relevant passages cited (grade 2-3) | explore (30) | 4.97 | 5.43 | +0.47 [-0.03, +0.97] |
| Distinct relevant passages cited (grade 2-3) | silver (27) | 2.30 | 2.59 | +0.30 [-0.07, +0.70] |
| Distinct highly relevant passages cited (grade 3) | all (57) | 2.47 | 2.67 | +0.19 [+0.00, +0.39] |
| Distinct highly relevant passages cited (grade 3) | explore (30) | 3.17 | 3.43 | +0.27 [-0.03, +0.57] |
| Distinct highly relevant passages cited (grade 3) | silver (27) | 1.70 | 1.81 | +0.11 [-0.11, +0.37] |
| Distinct documents among the relevant passages cited | all (57) | 2.30 | 2.51 | +0.21 [+0.00, +0.44] |
| Distinct documents among the relevant passages cited | explore (30) | 2.90 | 3.13 | +0.23 [-0.07, +0.57] |
| Distinct documents among the relevant passages cited | silver (27) | 1.63 | 1.81 | +0.19 [-0.07, +0.52] |
| Share of cited passages that are relevant | all (57) | 0.89 | 0.89 | +0.00 [-0.03, +0.04] |
| Share of cited passages that are relevant | explore (30) | 0.88 | 0.89 | +0.01 [-0.04, +0.05] |
| Share of cited passages that are relevant | silver (27) | 0.89 | 0.89 | -0.00 [-0.05, +0.05] |
| Claims per answer | all (57) | 4.40 | 4.65 | +0.25 [+0.02, +0.47] |
| Claims per answer | explore (30) | 5.73 | 6.17 | +0.43 [+0.07, +0.80] |
| Claims per answer | silver (27) | 2.93 | 2.96 | +0.04 [-0.19, +0.26] |
| Words of prose | all (57) | 168.67 | 172.11 | +3.44 [-4.47, +10.95] |
| Words of prose | explore (30) | 231.47 | 240.73 | +9.27 [-3.23, +21.00] |
| Words of prose | silver (27) | 98.89 | 95.85 | -3.04 [-12.11, +4.41] |
| Answer cites a silver gold passage | silver (27) | 0.78 | 0.70 | -0.07 [-0.22, +0.07] |

## Preference

gemini-3.8-flash (prompts/eval/pairwise-v1.md) compared each pair blind, once in each order; a preference counts only when both orders agree (split = they disagreed). Claude read every exploratory pair blind (seeded X/Y order; verdicts recorded before the key was read). Sign test on wins, two-sided.

| Judge | Needs | C preferred | B preferred | Tie | Split | p |
|---|---|---|---|---|---|---|
| Gemini, both orders | all (57) | 28 | 8 | 6 | 15 | 0.001 |
| Gemini, both orders | explore (30) | 18 | 4 | 0 | 8 | 0.004 |
| Gemini, both orders | silver (27) | 10 | 4 | 6 | 7 | 0.180 |
| Claude, blind | explore (30) | 17 | 4 | 9 | | 0.007 |

Where both judges stated a preference (19 exploratory pairs), they agreed on 19.

## The rule

Fixed in advance: Recommend adopting the filter if (a) Gemini's agreed preferences favour C over B at p < 0.05 (two-sided sign test) on all 60 needs or on the 33 exploratory needs; (b) on the 27 silver needs they do not favour B at p < 0.05; and (c) C's pass rate after the retry is not lower than B's by more than 5 points. Otherwise the better evidence is not shown to give better answers, and the filter is not recommended on this run.

**Met: the filter is recommended** ((a) all 28-8, p = 0.001; exploratory 18-4, p = 0.004: met. (b) silver 10-4, p = 0.180: met. (c) pass rates B 1.000, C 1.000: met.)

## What it shows and what it doesn't

- Only the evidence differs: same needs, answer model, effort, prompt and check.
- The judges see the answers and their verified quotes, not the corpus: they judge how well an answer uses and reports what it found.
- One answer model at one effort; 57 needs.
