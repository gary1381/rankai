# v3 held-out evaluation: plan fixed before queries, runs and labels (2026-11-02 UTC)

Written before the 48 v3 queries existed. Adzuna / USAJOBS were dropped by the project owner on 11-01, so v3 uses the corpus as it
stands and no new source is tested.

## Questions
1. **Is a scale-aware constraint penalty better than none?** J (reranker score only, constraints shown as tags) vs
   M (reranker score x (1 - 0.5 x violations)). Named as v3's primary in the hand-weight ablation (docs/EVALUATION.md).
2. **Does the default hold on clean queries?** J was picked after seeing v2, so v1 + v2 cannot confirm J vs F.
3. **Does the 10-30 ncss city pass help on queries nobody had seen?** It looked neutral in-sample (+3 / -2, v1 + v2).

## Frozen
- Corpora: snapshot **v3** = the current corpus (max_opp_id 26098, 26,095 postings); snapshot **v3o** = the corpus
  before the 10-30 city pass and GitHub bot queries (max_opp_id 24957, 24,954 postings). Same queries on both.
  No ingest between now and scoring.
- System: query rules, rewrite prompt (qr-v1), hand weights `W`, reranker (Qwen3-Reranker-0.6B), e5 vectors, source
  fetchers.
- Model: L = I's recipe (no AI posting judgment) fitted on every label before v3 (v0 + v1 + v1b + v2 + v2o + v1c + v2c,
  a pair labeled under two names counts once, the later label wins)
  -> `data/ltr_gbm_v0+v1+v1b+v2+v2o+v1c+v2c.pkl`, fitted before the v3 queries existed.
- Queries: `eval/queries_v3.jsonl` (= `queries_v3o.jsonl`), written by GPT gpt-6-luna via Codex from
  `eval/queries_v3_author_instructions.md` (v2's instructions, new ids, all 144 earlier queries listed as do-not-repeat),
  without access to the corpus, the sources or any result. Used as written; none removed or edited.

## Arms
- On v3: **F** (AI query rewrite + hand weights), **J** (F's top-50 candidates by reranker score only),
  **M** (J with the factor penalty), **L** (F's top-50 candidates, gradient boosting, no AI posting judgment).
- On v3o: **J** (for question 3).
- No arm needs a stored AI posting judgment, so no new Haiku judgments are made. Only the 48 query rewrites cost money.

## Labels
Pool = top 10 of each arm. composer-2.5 + grok-4.7, **no GPT review** (`--gpt-review none`): GPT wrote the queries, so
it does not label. Final rel = mean of the two. v3o pairs already pooled under v3 are labeled once.

## Metrics and tests
Ordering: nDCG@10 (gain 2^rel - 1) over answerable queries (at least one pooled posting with mean rel >= 1), paired
sign-flip test, 20,000 rounds, two-sided. Coverage: queries with at least one rel >= 2 posting in the top 10, exact
McNemar test.

- **Primary 1, on v3:** J vs M, nDCG@10.
- **Primary 2, on v3:** J vs F, nDCG@10.
- **Primary 3, arm J, v3o vs v3:** coverage, leaving out buyer-side outsourcing queries (`eval/gaps.py: buyer_side`:
  they want providers, not job posts). Reported with it: the same over all 48.
- Each primary at alpha 0.05, Holm-adjusted p next to it (three tests, and 1 and 2 share arm J).
- Secondary: L vs J, L vs F, nDCG over all 48, P@5, MRR; per language (zh / en / mix); how often J and M give the same
  top 10; how many top-10 results of J carry a `mismatch` tag.
- Per-language and per-group splits are descriptive.

## What each outcome means
- J >= M (not significantly worse) and J > F or J = F: J stays the default. Simplest arm, no reason to add a penalty.
- M significantly better than J: propose M as the default to the project owner; do not switch without that decision.
- J significantly worse than F: J was a mistake of choosing on v2; tell the project owner and reopen the choice.
- L significantly better than J: a third result for learned weights; it would need one more clean test before any
  switch, since v1 and v2 disagreed.

## Known weak points
- All labels are AI labels from two labelers, and recent batches disagree on about 40% of pairs. No human check yet.
- Arms that share candidates and differ little can look tied because few pairs differ; 48 queries cannot show a small
  effect. A tie is "no evidence of a difference", not proof of equality.
- J's pool is shared with M and L, so unlabeled results are not expected; any are reported.
- The queries follow the same instructions as v1 and v2, so they lean to non-software roles. v3 is not a sample of real
  user traffic.
- v3o uses today's index with an id cut-off, so term statistics include the newer postings.
