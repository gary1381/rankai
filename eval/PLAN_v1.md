# v1 held-out evaluation: plan fixed before labels (2026-10-29, ~19:20 UTC)

Written after the v1 runs and pool were made, before any v1 label existed.

## What is tested
"F's candidates + weights learned from the v0 labels" (arm H) against F, on 48 new queries the system has never seen.

## Frozen
- Corpus: snapshot v1 = the v0 corpus (max_opp_id 12772).
- System: query rules, rewrite prompt (qr-v1), posting judge (pj-v1), hand weights `W`, and the gradient-boosting
  models in `data/ltr_gbm_v0.pkl` (fitted on all 1,311 v0 labels). Nothing is changed after seeing the v1 queries.
- Queries: `eval/queries_v1.jsonl`, written by grok-4.7 from `eval/queries_v1_author_instructions.md`, without
  access to the corpus or any results. Used as written; none removed or edited.

## Arms
E (no AI), F (AI query rewrite), G (F + AI posting judgment, hand weights), H (F's top-50 candidates reordered by
the v0 gradient-boosting model, all features), I (as H without the AI posting-judgment features).
Pool: top 10 of each arm, 968 pairs, labeled the same way as v0 (composer-2.5 + grok-4.7, GPT on disagreements,
final = mean).

## Metric and tests
- nDCG@10 (gain 2^rel - 1) over answerable queries: at least one pooled posting with mean rel >= 1.
  nDCG over all 48 is reported next to it. P@5 at rel >= 2. Per language (zh / en / mix).
- Primary: H vs F, paired sign-flip test over queries, two-sided, alpha 0.05.
- Secondary: I vs F, H vs I (AI posting judgment inside the learned model), G vs F, F vs E (does the v0 rewrite gain
  hold on new queries).
- Also: the v0-fitted orderings applied to the v1 labeled pool (`python eval/ltr.py v1 --train v0`).

## Known weak points
- grok-4.7 wrote the queries and is also one of the two labelers.
- Many queries are for non-tech roles; the corpus is mostly tech companies, so some queries may have nothing
  relevant. They drop out of the main metric by the rule above, decided before labels.
- Pay constraints written as "2万" / "两万" are not parsed by the rules and not returned by the rewrite; that gap is
  left as is (fixing it now would tune on the test set).
