# Data: what is distributed and what is not

## Not in this repository

| Item | Why it is not distributed | How to get it |
|---|---|---|
| The corpus (`data/rankai.sqlite`: postings, raw payloads, FTS index, vectors, LLM judgments) | Postings are third-party content under each source's terms. Several ask for attribution and links to the original, and ncss.cn's use was limited to a local index. Raw payloads and posting text can also contain contact details of recruiters | Rebuild locally with `python -m rankai ingest` and `python -m rankai vectors`, after reading [SOURCES.md](SOURCES.md) |
| Saved source-check pages (robots.txt, terms, API docs from the 10-29/30 review) | Third-party pages | Re-read each source's current terms; that is required before fetching anyway |
| Query-rewrite cache (`data/qrewrite.jsonl`) | Model outputs tied to the private run. Not needed to recompute scores | Rebuilt on first use (costs a Haiku call per new query) |
| Trained ranker files (`data/ltr_gbm_*.pkl`) | Binary pickles; better rebuilt than trusted | `python eval/ltr.py --fit v0 v1 v1b v2 v2o v1c v2c` rebuilds L's model from the shipped feature files. Its predictions were checked identical to the original's |
| LLM cost log, agent search and rating logs | Local usage records; agent queries can carry personal details | Written as you use the system |
| Run logs (`logs/`) | Contain posting titles and links | Written by `ingest` and the labeling script |

`data/` and `logs/` are in `.gitignore`.

## In this repository (`eval/`)

All evaluation artifacts are numbers and model-written queries. They contain no posting text:

| Files | Contents |
|---|---|
| `queries_*.jsonl` | Synthetic test queries (`id`, `lang`, `query`), written by models under `queries_v*_author_instructions.md` (v0 by the developer agent). No personal data |
| `runs/<set>_<arm>.jsonl` | Each arm's ranked posting ids per query, with scores and features |
| `pool_*.jsonl` | Pooled (query id, posting id) pairs |
| `labels_*.jsonl` | Merged grades per (query id, posting id) with each labeler's raw grade; `_prepay` = before the pay relabel |
| `features_*.jsonl` | Ranking features per labeled pair (reranker scores, similarities, rule flags); used to train L |
| `paired_*.json`, `coverage_*.json`, `report_v3.json`, `ltr_*.json`, `ablate_hand*.json`, `gaps.json`, `mismatch_tags.json`, `model_checks_v3.json`, `label_agreement_*.json`, `labeler_calib*.json` | Computed results |
| `PLAN_v*.md` | Analysis plans written before each held-out round |

Posting ids are row ids in the private database. They identify nothing outside it.

## What can and cannot be reproduced

- **Exactly, offline:** every arm table and paired test (`eval/score.py`, `eval/paired.py`), and L's model
  (`eval/ltr.py --fit`). See [EVALUATION.md §8](EVALUATION.md#8-reproduce).
- **Not from this repository:** re-running an arm on the original corpus, or reading what a labeled posting said.
  A fresh ingest assigns new ids, so the shipped labels do not map onto a rebuilt database. To evaluate a change on
  your own corpus, freeze a snapshot, write new queries, pool and label them (pipeline in
  [EVALUATION.md §8](EVALUATION.md#8-reproduce)).

## Corpus at a glance (2026-11-17, private instance)

| | Count |
|---|---|
| Postings | 82,169 (63,261 English, 18,908 Chinese) |
| Hidden as closed (ATS boards) | 2,621 |
| Archived (posted > 30 days ago) | 15,385 |
| Multi-posting duplicate clusters | 7,298, covering 21,858 postings |
| By kind | full-time 67,080 · contract 5,810 · internship 4,303 · part-time 2,748 · bounty 2,104 · co-founder 64 · outsourcing 60 (rule-inferred) |

Evaluation snapshots were much smaller: v0/v1 12,772 postings, v1b/v2/v3o 24,954, v1c/v2c/v3 26,095. Three HN
job-seeker posts were later deleted from the v0 range, so some docs give that corpus as 12,769.

## Handling notes for your own corpus

- `raw_items` and `opps.text` keep whatever contact details a posting published. Redaction happens on the way out
  (`rankai/text.py: redact`), except for government sources, which are redacted at fetch time.
- Keep ncss.cn content, if you choose to fetch it, in a local index and show only titles and links.
- Open the database read-only (`file:data/rankai.sqlite?mode=ro`) for analysis while an ingest may be running.
- Back up `rankai.sqlite` before re-ingesting if you keep labels. Labels are keyed by row id.
