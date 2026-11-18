# v2 held-out evaluation: plan fixed before runs and labels (2026-10-30, ~01:15 UTC)

Written after the 48 v2 queries arrived and before any v2 run, pool or label existed.

## Questions
1. **Out-of-sample coverage.** The 10-29 source expansion (A + B + ncss) raised coverage on the v1 queries, but the
   source parameters were chosen after seeing those queries. Does it hold on queries nobody had seen?
2. **Learned ordering, end to end.** v1 left "F's candidates + learned weights" (H) vs F at +0.043, p = 0.076.
   A fresh test of the same frozen H.

## Frozen
- Corpora: snapshot **v2** = the corpus after the source expansion (max_opp_id 24957, 24,954 postings);
  snapshot **v2o** = the v0/v1 corpus (max_opp_id 12772, 12,769 postings). Same queries on both.
- System: query rules, rewrite prompt (qr-v1), posting judge (pj-v1), hand weights `W`, source fetchers.
- Models: H = `data/ltr_gbm_v0.pkl` (unchanged since v1). K = the same recipe fitted on every label before v2
  (v0 + v1 + v1b, a pair labeled twice counts once) -> `data/ltr_gbm_v0+v1+v1b.pkl`, fitted before any v2 run.
- Queries: `eval/queries_v2.jsonl` (= `queries_v2o.jsonl`), written by GPT gpt-6-luna via Codex from
  `eval/queries_v2_author_instructions.md` (v1's instructions, new ids, all 96 earlier queries listed as do-not-repeat),
  without access to the corpus, the sources or any result. Used as written; none removed or edited.

## Arms
- On v2: **F** (AI query rewrite + hand weights), **H** (F's top-50 candidates, v0 gradient-boosting model),
  **J** (F's top-50 candidates by reranker score only: no rule penalties, no priors),
  **K** (F's top-50 candidates, gradient boosting fitted on v0 + v1 + v1b).
- On v2o: **F** and **H** (for question 1).
- Every posting in F's top-50 on either corpus gets an AI judgment first (judge.ensure), as in v1.

## Labels
Pool = top 10 of each arm. composer-2.5 + grok-4.7, **no GPT review** (`--gpt-review none`): GPT wrote the queries,
so it does not label. Final rel = mean of the two. v2o pairs already pooled under v2 are labeled once.

## Metrics and tests
- **Primary 1 (coverage), arm F, v2o vs v2, all 48 queries:** number of queries with at least one rel >= 2 posting in
  the top 10, exact McNemar test on the discordant queries, two-sided, alpha 0.05. Reported with it: P@5 (rel >= 2),
  paired sign-flip test; mean count of rel >= 2 in the top 10; per language.
- **Primary 2 (ordering), on v2:** H vs F, nDCG@10 (gain 2^rel - 1) over answerable queries (at least one pooled
  posting with mean rel >= 1 in the v2 pool), paired sign-flip test, 20,000 rounds, two-sided, alpha 0.05.
  nDCG over all 48 next to it.
- The two primaries answer different questions; each is tested at 0.05, no correction between them.
- Secondary: K vs F, K vs H, J vs F, H vs J; coverage for arm H (v2o vs v2); per language (zh / en / mix);
  which sources supplied the rel >= 2 results.
- Per-language and per-group splits are descriptive.

## Known weak points
- All labels are AI labels, now from only two labelers; no human check yet.
- The v2o run uses today's index with an id cut-off. BM25 term statistics include the new postings, and postings
  updated since 10-29 carry their new text, so v2o is close to, not exactly, the 10-29 system.
- The v2 queries follow the same instructions as v1, so they also lean to non-software roles. That is the intended
  test of the new sources, but v2 is not a sample of real user traffic.
- Pay written as "1.8万" / "25万" is still not parsed by the rules; left as is.
