# How the chatbot finds its evidence, and how the choices were made

A plain-language companion to decisions D-005 and D-006 and the reports in `reports/`.

## What "retrieval" means here

Before the chatbot writes anything, it has to find the right passages among 1,099 pages. It does that
in three steps:

1. **Cutting the documents into passages** (chunking). The answer model can't read every page for every
   question, so each document is cut into passages of a few paragraphs, and the best 20 are handed over.
2. **Finding passages by meaning.** An embedding model turns each passage, and each question, into a list
   of numbers that captures what it is about. Passages whose numbers sit close to the question's are
   about the same thing, even when they use different words ("brand" and "trade mark").
3. **Finding passages by keywords**, the classic way (BM25), which is good at exact terms: names,
   figures, "Raising the Bar". The two rankings are combined.

Each of these involves choices, and the owner asked Claude to make the first two on evidence.

## How the choices were tested

With no money yet for model-written tests, Claude wrote 114 test questions from the documents themselves.
Each question comes with the exact sentence (or sentences) that answers it. A choice is better when the
right sentences end up among the passages handed to the answer model. Half the questions were used to
choose; the other half to check the choice.

Two things to keep in mind when reading the numbers:

- **They undercount.** If a question is answered by a sentence in the 2023 report and the same finding
  also appears, worded differently, in the 2024 report, finding the 2024 passage counts as a miss. So
  the absolute numbers are pessimistic; the comparisons between choices are what matter.
- **They are noisy.** With about 55 questions on each side, a difference of less than about 0.05 to
  0.08 could be chance. The rules were written before any number existed, so a lucky result couldn't
  steer the choice.

## Chunking: cut along the document's own structure

| How passages are cut | Share of the answering sentences that reach the answer model (test half) |
|---|---|
| Fixed-size windows, ignoring headings (the usual default) | 72% |
| **Along sections, up to about 300 words, no heading added (chosen)** | 74% |
| Along sections, smaller (about 200 words) | 77% |

On the half used for choosing, cutting along sections found 11 percentage points more of the answering
sentences than fixed windows. On the checking half the advantage was smaller (3 points for the chosen
setting, 6 for the smaller passages) and could be chance; every section-based setting still came out
ahead. The smaller passages did best on both halves; they were within the rule's tie margin of the
simpler chosen setting, and are the first thing to re-test with a larger test set.

Adding each passage's document title and section heading to its text, a common recommendation, made no
difference here: twelve of the documents are annual editions of the same report with nearly the same
title, so the heading words don't tell passages apart.

## The embedding model: a mid-sized one was as good as the big ones

Fourteen freely licensed embedding models were compared, from 23 million to 600 million parameters
(roughly, the model's size). Larger models cost more: slower to start on Cloud Run, slower per question,
more expensive to run. So the rule was set in advance: take the smallest model that scores within a
whisker of the best.

The winner was **Snowflake's arctic-embed-m-v1.5**, a 109-million-parameter model. It scored best on the
choosing half. On the checking half it found the answering sentences near the top of the list noticeably
more often than the baseline model (the gain's lower bound is just above zero). A model five times its
size from the same family scored the same on the choosing half and a little better on the checking half,
but head to head over all 114 questions the two are statistically indistinguishable. None of the four
largest models beat it reliably.

## Combining meaning and keywords

Searching by meaning alone, by keywords alone, and by several blends of the two were compared with the
chosen model. The blend already configured (70% meaning, 30% keywords) did best on both halves. Meaning
alone missed answers that keywords catch (exact figures, names of reforms), and keywords alone did much
worse than either.

## What this means for you

- The chatbot will usually put the passage that answers a factual question within its top few results,
  and the right document in its top five about 95% of the time.
- Broad questions that need several documents ("what does the research say about X?") are harder: the
  test set's few such questions were found less reliably. The question planner, which splits a broad
  question into several searches, needs a language model and is switched on once a key is added.
- Every choice here is reversible and recorded. A larger, independently judged test set, planned for when
  there is a model budget, may overturn the close calls: smaller passages, and the larger arctic model.
