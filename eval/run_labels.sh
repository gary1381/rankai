#!/usr/bin/env bash
# Label every rankai_rel_<snapshot>_NN task file in $RANKAI_LABEL_DIR/inbox with an external dual-labeling tool,
# two tasks at a time. Usage: eval/run_labels.sh v0 [extra args for the labeler]
#   e.g. eval/run_labels.sh v2 --gpt-review none   (GPT wrote the v2 queries, so GPT must not review)
#
# The labeling tool is not part of this repository. RANKAI_LABELER must name a command that takes
#   <task> --dir <label dir> [extra args]
# reads <dir>/inbox/<task>.jsonl (+ .md instructions written by eval/pool.py), has two LLM labelers grade every item
# (composer-2.5 and grok-4.7 in rounds v0-v3, with a GPT review of disagreements when under 40% of a file disagrees),
# and writes <dir>/outbox/<task>.compare.json, which eval/merge_labels.py reads.
set -u
snap=${1:-v0}
shift || true
extra="$*"
root=$(cd "$(dirname "$0")/.." && pwd)
dir=${RANKAI_LABEL_DIR:-$root/data/labeling}
labeler=${RANKAI_LABELER:?set RANKAI_LABELER to your dual-labeling command (see the header of this script)}
log=$root/logs/labels_${snap}
mkdir -p "$log"
ls "$dir/inbox" | sed -n "s/^\(rankai_rel_${snap}_[0-9][0-9]\)\.jsonl$/\1/p" | \
  xargs -P 2 -I{} sh -c "test -f '$dir/outbox/{}.compare.json' && echo 'skip {}' || $labeler {} --dir '$dir' $extra > '$log/{}.log' 2>&1; echo \"{} exit \$?\""
echo ALL_DONE
