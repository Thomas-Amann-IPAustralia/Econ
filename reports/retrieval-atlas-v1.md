# Retrieval for the atlas chat (atlas-v1)

A free measurement, with no model calls (D-038, WP5). Each question was searched as asked (no plan), over the atlas index built from commit `3e13aef7aee3` (4611 passages). The service's relevance filter then chooses 20 passages from the 60 the search reads; it can't be run free, so the context here is the search's own first 20, and the pool is the 60 the filter would read. Pinning puts an observation's own passages first when the question names its id.

The test set (`eval/atlas/atlas-v1.jsonl`) was written and committed before any number: 20 lookups by topic without ids (one gold observation each, over all eight lenses and three stages), 5 by id, 10 exploratory needs with gold sets, and 5 out of scope (not measured here).

| Variant | Lookups: gold in the 20 | in the 60 | By id: in the 20 | in the 60 | Exploratory recall, 20 | in 60 |
|---|---:|---:|---:|---:|---:|---:|
| notes-on.cap2.pin-on | 100% | 100% | 100% | 100% | 0.813 | 0.813 |
| notes-on.cap2.pin-off | 100% | 100% | 80% | 100% | 0.813 | 0.813 |
| notes-on.cap3.pin-on | 100% | 100% | 100% | 100% | 0.790 | 0.813 |
| notes-on.cap3.pin-off | 100% | 100% | 80% | 100% | 0.790 | 0.813 |
| notes-on.cap4.pin-on | 100% | 100% | 100% | 100% | 0.736 | 0.813 |
| notes-on.cap4.pin-off | 100% | 100% | 80% | 100% | 0.736 | 0.813 |
| notes-on.cap8.pin-on | 100% | 100% | 100% | 100% | 0.630 | 0.813 |
| notes-on.cap8.pin-off | 100% | 100% | 80% | 100% | 0.630 | 0.813 |
| notes-off.cap2.pin-on | 100% | 100% | 100% | 100% | 0.792 | 0.916 |
| notes-off.cap2.pin-off | 100% | 100% | 60% | 60% | 0.792 | 0.916 |
| notes-off.cap3.pin-on | 100% | 100% | 100% | 100% | 0.734 | 0.916 |
| notes-off.cap3.pin-off | 100% | 100% | 60% | 60% | 0.734 | 0.916 |
| notes-off.cap4.pin-on | 100% | 100% | 100% | 100% | 0.720 | 0.916 |
| notes-off.cap4.pin-off | 100% | 100% | 60% | 60% | 0.720 | 0.916 |
| notes-off.cap8.pin-on | 100% | 100% | 100% | 100% | 0.705 | 0.916 |
| notes-off.cap8.pin-off | 100% | 100% | 60% | 60% | 0.705 | 0.916 |

## Decision (free retrieval settings, delegated by D-013's brief; recorded in D-038)

Adopted: **notes-off.cap2.pin-on**. Every variant with pinning finds every lookup's and every by-id need's gold pages in the 20 passages (100% and 100%), so the exploratory needs decide. Without the notes, the 60 passages the filter chooses from hold 0.916 of their gold pages against 0.813 with them, while the search's own first 20 hold 0.792 against 0.813. A note repeats its observation's headline on every passage of the page, so one well-matched page fills more of the candidates; the service's filter picks from the pool, so the pool's reach matters more. Recall in the 20 by the cap a page may hold (notes off): 2: 0.792, 3: 0.734, 4: 0.720, 8: 0.705. Pinning is what finds a named observation and the Stage 3 page that tested it: without it, by-id needs fall to 60%. The test set is small (40 needs, written from the pages, so its words are the pages' words); the smoke test reads real answers.

## Lookups missed by the configured variant (notes-off.cap2.pin-on)

None.

## Exploratory needs, need by need (the configured variant, and with notes)

| Need | Gold pages | In the 20 | In the 60 | With notes: in the 20 | in the 60 |
|---|---:|---:|---:|---:|---:|
| a26: What do we know about universities and patents? | 8 | 6 | 6 | 6 | 6 |
| a27: What does the analysis say about filing without an attorney? | 5 | 4 | 5 | 4 | 4 |
| a28: How do official fees relate to filing and to renewals? | 9 | 8 | 9 | 8 | 8 |
| a29: What do we know about women inventors? | 6 | 6 | 6 | 6 | 6 |
| a30: How does the advantage of a place relate to its IP filing? | 7 | 5 | 6 | 4 | 4 |
| a31: What has been found about the business cycle and IP filing? | 7 | 6 | 7 | 4 | 4 |
| a32: What do we know about provisional applications? | 5 | 4 | 4 | 4 | 4 |
| a33: How does Australia compare with other OECD countries on R&D and patents? | 7 | 6 | 7 | 7 | 7 |
| a34: What does it mean to hold factors together, and why is that not an experiment? | 4 | 3 | 4 | 3 | 3 |
| a35: What data gaps hold back the analysis of firms? | 4 | 2 | 3 | 4 | 4 |
