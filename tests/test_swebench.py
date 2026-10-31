from __future__ import annotations

import json
from pathlib import Path

from agent0.swebench import (
    TASK_PREAMBLE,
    assert_task_has_no_leaks,
    fetch_verified_row,
    format_summary_table,
    ids_for_limit,
    load_mini_spec,
    load_official_resolved,
    official_eval_argv,
    prediction_record,
    problem_task,
    resolve_image_prefix,
    selected_ids,
    summarize_rows,
    write_predictions,
)


def test_mini_ids_are_verified_subset_and_stratified() -> None:
    spec = load_mini_spec()
    pool = spec["pool"]
    assert spec["dataset_name"] == "princeton-nlp/SWE-bench_Verified"
    assert len(pool) == 50
    assert len(set(pool)) == 50
    assert spec["limit_1"] in pool
    assert spec["limit_1"] == "django__django-11790"
    ten = spec["limit_10"]
    assert len(ten) == 10
    assert set(ten) <= set(pool)
    assert sum(item.startswith("django__") for item in ten) == 5
    assert sum(item.startswith("sphinx-doc__") for item in ten) == 5
    assert selected_ids(1) == [spec["limit_1"]]
    assert selected_ids(10) == ten
    assert ids_for_limit(50) == spec["pool"]


def test_problem_task_drops_leaks() -> None:
    row = {
        "instance_id": "django__django-11790",
        "problem_statement": "Username field missing maxlength.",
        "hints_text": "SECRET HINT do not show",
        "test_patch": "diff --git a/tests/secret.py",
        "patch": "diff --git a/django/secret.py",
        "FAIL_TO_PASS": '["test_secret"]',
        "PASS_TO_PASS": "[]",
    }
    task = problem_task(row)
    assert task == TASK_PREAMBLE + "\n\nUsername field missing maxlength."
    assert task.startswith(TASK_PREAMBLE)
    assert_task_has_no_leaks(task, row)
    assert "SECRET HINT" not in task
    assert "tests/secret.py" not in task


def test_predictions_and_official_eval_argv(tmp_path: Path) -> None:
    records = [
        prediction_record("django__django-11790", "deepseek-flash", "diff --git a/x\n"),
        prediction_record("sphinx-doc__sphinx-8475", "deepseek-flash", ""),
    ]
    path = tmp_path / "predictions.jsonl"
    write_predictions(path, records)
    lines = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert set(first) == {"instance_id", "model_name_or_path", "model_patch"}
    argv = official_eval_argv(
        predictions_path=path,
        instance_ids=["django__django-11790", "sphinx-doc__sphinx-8475"],
        run_id="m6",
    )
    assert argv[:3] == ["python", "-m", "swebench.harness.run_evaluation"]
    assert "--dataset_name" in argv
    assert "princeton-nlp/SWE-bench_Verified" in argv
    assert argv[argv.index("--namespace") + 1] == "swebench"
    assert argv[argv.index("--cache_level") + 1] == "instance"
    assert argv[argv.index("--clean") + 1] == "False"
    assert argv[argv.index("--force_rebuild") + 1] == "False"
    assert "--instance_ids" in argv
    assert "django__django-11790" in argv
    assert "swebench.harness" in " ".join(argv)


def test_summary_table_from_telemetry_and_results(tmp_path: Path) -> None:
    tel = {
        "django__django-11790": {
            "turns": 4,
            "tokens": {"prompt": 100, "completion": 20, "cache_hit": 40, "cache_miss": 60},
            "outcome": "submitted",
        }
    }
    results = {"resolved": ["django__django-11790"], "unresolved": []}
    rows = summarize_rows(telemetries=tel, resolved=load_official_resolved(results))
    assert rows[0]["resolved"] is True
    assert rows[0]["cache_hit_rate"] == 0.4
    table = format_summary_table(rows)
    assert "django__django-11790" in table
    assert "0.4" in table


def test_image_prefix_env_and_flag(monkeypatch) -> None:
    monkeypatch.delenv("AGENT0_SWEBENCH_IMAGE_PREFIX", raising=False)
    monkeypatch.delenv("AGENT0_SWEBENCH_IMAGE_NAMESPACE", raising=False)
    assert resolve_image_prefix() == "swebench/sweb.eval.x86_64."
    assert resolve_image_prefix(namespace="mirror") == "mirror/sweb.eval.x86_64."
    assert resolve_image_prefix(prefix="reg.example/sweb.eval.x86_64.") == (
        "reg.example/sweb.eval.x86_64."
    )
    monkeypatch.setenv("AGENT0_SWEBENCH_IMAGE_PREFIX", "hub.local/sweb.eval.x86_64.")
    assert resolve_image_prefix() == "hub.local/sweb.eval.x86_64."


def test_fetch_verified_row_uses_local_cache(tmp_path: Path) -> None:
    cache = tmp_path / "rows"
    cache.mkdir()
    (cache / "django__django-11790.json").write_text(
        '{"instance_id": "django__django-11790", "problem_statement": "cached"}\n',
        encoding="utf-8",
    )

    class Boom:
        def get(self, *args, **kwargs):
            raise AssertionError("network should not be used when cache hits")

    row = fetch_verified_row("django__django-11790", client=Boom(), cache_dir=cache)
    assert row["problem_statement"] == "cached"


def test_fetch_verified_row_writes_cache(tmp_path: Path) -> None:
    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {
                "rows": [
                    {"row": {"instance_id": "other__other-1", "problem_statement": "skip"}},
                    {"row": {"instance_id": "django__django-11790", "problem_statement": "from hf"}},
                ]
            }

    class FakeClient:
        def get(self, url, params=None):
            assert "rows" in url
            assert params["offset"] == 0
            return FakeResponse()

    cache = tmp_path / "rows"
    row = fetch_verified_row("django__django-11790", client=FakeClient(), cache_dir=cache)
    assert row["problem_statement"] == "from hf"
    saved = json.loads((cache / "django__django-11790.json").read_text(encoding="utf-8"))
    assert saved["problem_statement"] == "from hf"
