# End-to-end answers v1: the service today against the adopted retrieval

Grid `answers-v1` (eval/grids/answers-v1.yaml, committed before any answer). 60 test needs: all 33 exploratory test needs and a seeded 27 of the 59 silver test needs. A is the service today (`plan:luna-plan-v1/plain/none`); B is the adopted retrieval (`plan+q:luna-plan-v2/enriched/none`, D-013). Both answered by gpt-6.1-sol at medium effort with prompt answer-v1, on the Flex tier, through the service's own check and retry.

## The check

| | A | B |
|---|---|---|
| Passed (after at most one retry) | 60/60 | 60/60 |
| Passed first time | 1.000 | 0.983 |
| Coverage complete / partial / not_in_kb | 47 / 13 / 0 | 52 / 8 / 0 |
| Cost per answer (Flex) | $0.0111 | $0.0114 |

## Grounding against the judgments

Every passage either answer cites lies in its setting's 20-passage context, which is fully judged, so no cited passage is unjudged.

| Measure | Needs | A | B | B - A [95% CI] |
|---|---|---|---|---|
| Distinct relevant passages cited (grade 2-3) | all (60) | 3.28 | 3.78 | +0.50 [+0.10, +0.93] |
| Distinct relevant passages cited (grade 2-3) | explore (33) | 4.24 | 5.00 | +0.76 [+0.18, +1.39] |
| Distinct relevant passages cited (grade 2-3) | silver (27) | 2.11 | 2.30 | +0.19 [-0.33, +0.78] |
| Distinct highly relevant passages cited (grade 3) | all (60) | 2.20 | 2.57 | +0.37 [+0.03, +0.73] |
| Distinct highly relevant passages cited (grade 3) | explore (33) | 2.64 | 3.27 | +0.64 [+0.15, +1.21] |
| Distinct highly relevant passages cited (grade 3) | silver (27) | 1.67 | 1.70 | +0.04 [-0.33, +0.44] |
| Share of cited passages that are relevant | all (60) | 0.84 | 0.88 | +0.04 [-0.02, +0.12] |
| Share of cited passages that are relevant | explore (33) | 0.82 | 0.88 | +0.05 [-0.02, +0.13] |
| Share of cited passages that are relevant | silver (27) | 0.86 | 0.89 | +0.03 [-0.08, +0.17] |
| Claims per answer | all (60) | 4.45 | 4.60 | +0.15 [-0.20, +0.52] |
| Claims per answer | explore (33) | 5.85 | 5.97 | +0.12 [-0.39, +0.67] |
| Claims per answer | silver (27) | 2.74 | 2.93 | +0.19 [-0.19, +0.59] |
| Words of prose | all (60) | 165.58 | 175.57 | +9.98 [-0.75, +21.30] |
| Words of prose | explore (33) | 228.21 | 238.30 | +10.09 [-6.21, +26.76] |
| Words of prose | silver (27) | 89.04 | 98.89 | +9.85 [-2.89, +25.11] |
| Answer cites a silver gold passage | silver (27) | 0.52 | 0.78 | +0.26 [+0.07, +0.44] |

## Preference

gemini-3.8-flash (prompts/eval/pairwise-v1.md) compared each pair blind, once in each order; a preference counts only when both orders agree (split = they disagreed). Claude read every exploratory pair blind (a seeded random X/Y order), as a second judge from a third family. Sign test on wins, two-sided.

| Judge | Needs | B preferred | A preferred | Tie | Split | p |
|---|---|---|---|---|---|---|
| Gemini, both orders | all (60) | 28 | 16 | 3 | 13 | 0.096 |
| Gemini, both orders | explore (33) | 19 | 7 | 0 | 7 | 0.029 |
| Gemini, both orders | silver (27) | 9 | 9 | 3 | 6 | 1.000 |
| Claude, blind | explore (33) | 18 | 6 | 9 | | 0.023 |

Where both judges stated a preference (20 exploratory pairs), they agreed on 20.

## The rule

Fixed in advance: B is confirmed if the agreed preferences favour B or are tied (B not worse at p < 0.05) and B's pass rate is not lower than A's by more than 5 points. **Confirmed**: the preferences favour B (28 to 16 over all 60 needs; 19 to 7 on the exploratory needs, p = 0.029), and both pass rates are 60/60.

## What it shows and what it doesn't

- The gain is in the kind of question the owner asks: exploratory answers cite more relevant passages and are preferred by both judges. On silver lookups the answers are as good as before (9 to 9), with the gold passage cited more often (0.52 to 0.78).
- The judges see the answers and their verified quotes, not the whole corpus: they judge how well an answer uses and reports what it found, not whether something better was left unfound. The retrieval report covers that.
- One answer model, one prompt, at one effort; 60 needs. A different answer model is a separate question (SOP §20.5).
