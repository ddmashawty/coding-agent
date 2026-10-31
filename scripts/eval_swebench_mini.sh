#!/usr/bin/env bash
# Official SWE-bench 4.1.0 harness only. Requires the optional swebench group.
#
# Confirmed against:
#   https://www.swebench.com/SWE-bench/guides/evaluation/
#   https://www.swebench.com/SWE-bench/guides/docker_setup/
#   https://www.swebench.com/SWE-bench/reference/harness/
#   SWE-bench v4.1.0 swebench/harness/run_evaluation.py
#
# --namespace swebench : pull Hub images (do not build locally; cannot combine with --force_rebuild).
# --cache_level instance : keep sweb.eval instance images. Default env deletes them after a run.
# --clean False : do not prune images above the cache level.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export HF_HOME="${AGENT0_HF_HOME:-$ROOT/.cache/huggingface}"
NAMESPACE="${AGENT0_SWEBENCH_IMAGE_NAMESPACE:-swebench}"
MAX_WORKERS="${MAX_WORKERS:-1}"

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <predictions.jsonl> <run_id> [instance_id...]" >&2
  exit 2
fi

PREDICTIONS="$1"
RUN_ID="$2"
shift 2

if [[ $# -eq 0 ]]; then
  echo "pass --instance_ids after run_id (official Verified filter)" >&2
  exit 2
fi

run_eval() {
  python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --split test \
    --predictions_path "$PREDICTIONS" \
    --run_id "$RUN_ID" \
    --namespace "$NAMESPACE" \
    --cache_level instance \
    --clean False \
    --force_rebuild False \
    --max_workers "$MAX_WORKERS" \
    --instance_ids "$@"
}

if command -v uv >/dev/null 2>&1; then
  cd "$ROOT"
  uv run --group swebench python -m swebench.harness.run_evaluation \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --split test \
    --predictions_path "$PREDICTIONS" \
    --run_id "$RUN_ID" \
    --namespace "$NAMESPACE" \
    --cache_level instance \
    --clean False \
    --force_rebuild False \
    --max_workers "$MAX_WORKERS" \
    --instance_ids "$@"
else
  run_eval "$@"
fi
