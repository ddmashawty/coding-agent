"""SWE-bench Verified Mini: instance lists, task text, predictions, summary.

Scoring uses the official harness and princeton-nlp/SWE-bench_Verified.
This module does not import swebench.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

LEAK_FIELDS = ("test_patch", "hints_text", "patch", "FAIL_TO_PASS", "PASS_TO_PASS")
DEFAULT_LIST = Path(__file__).resolve().parents[2] / "data" / "swebench_verified_mini.json"
DEFAULT_ROW_CACHE = Path(__file__).resolve().parents[2] / "data" / "cache" / "swebench_verified"
OFFICIAL_DATASET = "princeton-nlp/SWE-bench_Verified"
OFFICIAL_SPLIT = "test"
# SWE-bench 4.1.0 defaults to --namespace swebench (pull Hub images, do not build).
# Default --cache_level env deletes sweb.eval instance images after a run.
OFFICIAL_NAMESPACE = "swebench"
OFFICIAL_CACHE_LEVEL = "instance"
OFFICIAL_CLEAN = False
OFFICIAL_FORCE_REBUILD = False


def load_mini_spec(path: Path | None = None) -> dict[str, Any]:
    target = path or DEFAULT_LIST
    return json.loads(target.read_text(encoding="utf-8"))


def selected_ids(limit: int, spec: dict[str, Any] | None = None) -> list[str]:
    data = spec or load_mini_spec()
    if limit == 1:
        return [str(data["limit_1"])]
    if limit == 10:
        return [str(item) for item in data["limit_10"]]
    raise ValueError("limit must be 1 or 10")


def ids_for_limit(limit: int, spec: dict[str, Any] | None = None) -> list[str]:
    """Instance IDs for pull/eval. 50 is the full Mini pool."""
    data = spec or load_mini_spec()
    if limit == 50:
        return [str(item) for item in data["pool"]]
    return selected_ids(limit, data)


def resolve_image_prefix(*, namespace: str | None = None, prefix: str | None = None, arch: str = "x86_64") -> str:
    if prefix:
        return prefix
    env_prefix = os.environ.get("AGENT0_SWEBENCH_IMAGE_PREFIX")
    if env_prefix:
        return env_prefix
    ns = namespace or os.environ.get("AGENT0_SWEBENCH_IMAGE_NAMESPACE") or OFFICIAL_NAMESPACE
    return f"{ns}/sweb.eval.{arch}."


def resolve_row_cache(cache_dir: Path | None = None) -> Path:
    if cache_dir is not None:
        return cache_dir
    env = os.environ.get("AGENT0_SWEBENCH_ROW_CACHE")
    if env:
        return Path(env)
    return DEFAULT_ROW_CACHE


# Fixed, instance-independent. Same text on every Mini task. Not part of the official prompt.
TASK_PREAMBLE = (
    "The repository is at /testbed. "
    "Only modify non-test source files. "
    "After the fix, run the relevant tests, then call submit."
)


def problem_task(row: dict[str, Any]) -> str:
    """Preamble plus problem statement. Never leak tests or hints."""
    text = row.get("problem_statement")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("instance is missing problem_statement")
    return f"{TASK_PREAMBLE}\n\n{text.strip()}"


def assert_task_has_no_leaks(task: str, row: dict[str, Any]) -> None:
    for field in LEAK_FIELDS:
        value = row.get(field)
        if isinstance(value, str) and value and value in task:
            raise ValueError(f"task text leaked field {field}")


def prediction_record(instance_id: str, model: str, patch: str) -> dict[str, str]:
    return {
        "instance_id": instance_id,
        "model_name_or_path": model,
        "model_patch": patch,
    }


def write_predictions(path: Path, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def official_eval_argv(
    *,
    predictions_path: Path,
    instance_ids: list[str],
    run_id: str,
    dataset_name: str = OFFICIAL_DATASET,
    split: str = OFFICIAL_SPLIT,
    namespace: str = OFFICIAL_NAMESPACE,
    cache_level: str = OFFICIAL_CACHE_LEVEL,
    clean: bool = OFFICIAL_CLEAN,
    force_rebuild: bool = OFFICIAL_FORCE_REBUILD,
    max_workers: int = 1,
) -> list[str]:
    """Official harness argv (SWE-bench 4.1.0).

    `--namespace swebench` pulls Hub images instead of building.
    `--cache_level instance` keeps instance images; default `env` deletes them.
    `--force_rebuild` cannot be combined with a namespace.
    """
    return [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        dataset_name,
        "--split",
        split,
        "--predictions_path",
        str(predictions_path),
        "--run_id",
        run_id,
        "--namespace",
        namespace,
        "--cache_level",
        cache_level,
        "--clean",
        "True" if clean else "False",
        "--force_rebuild",
        "True" if force_rebuild else "False",
        "--max_workers",
        str(max_workers),
        "--instance_ids",
        *instance_ids,
    ]


def fetch_verified_row(
    instance_id: str,
    *,
    client: Any | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    """Load one official Verified row. Uses httpx; no swebench import.

    Hits `cache_dir` first (default `data/cache/swebench_verified/` or
    `AGENT0_SWEBENCH_ROW_CACHE`).
    """
    cache = resolve_row_cache(cache_dir)
    cached = cache / f"{instance_id}.json"
    if cached.is_file():
        row = json.loads(cached.read_text(encoding="utf-8"))
        if row.get("instance_id") != instance_id:
            raise LookupError(f"cached row mismatch for {instance_id}")
        return row

    import httpx

    closer = None
    if client is None:
        closer = httpx.Client(timeout=60)
        client = closer
    try:
        row = _fetch_verified_row_from_hub(instance_id, client)
    finally:
        if closer is not None:
            closer.close()
    cache.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return row


def _fetch_verified_row_from_hub(instance_id: str, client: Any) -> dict[str, Any]:
    """Page the dataset-viewer /rows API. /filter currently 422s on quoted IDs."""
    offset = 0
    page = 100
    while True:
        response = client.get(
            "https://datasets-server.huggingface.co/rows",
            params={
                "dataset": OFFICIAL_DATASET,
                "config": "default",
                "split": OFFICIAL_SPLIT,
                "offset": offset,
                "length": page,
            },
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("rows") or []
        for item in rows:
            row = item.get("row") or item
            if row.get("instance_id") == instance_id:
                return row
        if len(rows) < page:
            break
        offset += page
    raise LookupError(f"{instance_id} not in {OFFICIAL_DATASET}")


def cache_hit_rate(tokens: dict[str, Any]) -> float:
    prompt = float(tokens.get("prompt") or 0)
    hit = float(tokens.get("cache_hit") or 0)
    if prompt <= 0:
        return 0.0
    return hit / prompt


def load_official_resolved(results: dict[str, Any]) -> dict[str, bool]:
    resolved: dict[str, bool] = {}
    for key in ("resolved", "resolved_ids"):
        value = results.get(key)
        if isinstance(value, list):
            for item in value:
                resolved[str(item)] = True
    for key in ("unresolved", "error", "empty_patch", "unresolved_ids"):
        value = results.get(key)
        if isinstance(value, list):
            for item in value:
                resolved.setdefault(str(item), False)
    reports = results.get("reports")
    if isinstance(reports, dict):
        for instance_id, report in reports.items():
            if isinstance(report, dict) and "resolved" in report:
                resolved[str(instance_id)] = bool(report["resolved"])
    return resolved


def summarize_rows(
    *,
    telemetries: dict[str, dict[str, Any]],
    resolved: dict[str, bool],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for instance_id in sorted(telemetries):
        tel = telemetries[instance_id]
        tokens = tel.get("tokens") or {}
        rows.append(
            {
                "instance_id": instance_id,
                "resolved": resolved.get(instance_id),
                "turns": tel.get("turns"),
                "prompt_tokens": tokens.get("prompt"),
                "completion_tokens": tokens.get("completion"),
                "cache_hit": tokens.get("cache_hit"),
                "cache_hit_rate": round(cache_hit_rate(tokens), 4),
                "outcome": tel.get("outcome"),
            }
        )
    return rows


def format_summary_table(rows: list[dict[str, Any]]) -> str:
    header = (
        "instance_id",
        "resolved",
        "turns",
        "prompt",
        "completion",
        "cache_hit",
        "cache_hit_rate",
        "outcome",
    )
    lines = [" | ".join(header), " | ".join("---" for _ in header)]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    str(row["instance_id"]),
                    str(row["resolved"]),
                    str(row["turns"]),
                    str(row["prompt_tokens"]),
                    str(row["completion_tokens"]),
                    str(row["cache_hit"]),
                    str(row["cache_hit_rate"]),
                    str(row["outcome"]),
                ]
            )
        )
    return "\n".join(lines) + "\n"
