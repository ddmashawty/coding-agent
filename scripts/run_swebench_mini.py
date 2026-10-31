#!/usr/bin/env python3
"""Run agent0 on SWE-bench Verified Mini instances inside per-instance containers."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent0.cli import execute  # noqa: E402
from agent0.config import load_config  # noqa: E402
from agent0.executors.docker import DockerExecutor, official_instance_image  # noqa: E402
from agent0.providers.deepseek import DeepSeekProvider  # noqa: E402
from agent0.session import Session  # noqa: E402
from agent0.swebench import (  # noqa: E402
    assert_task_has_no_leaks,
    fetch_verified_row,
    prediction_record,
    problem_task,
    resolve_image_prefix,
    selected_ids,
    write_predictions,
)
from agent0.tools.registry import headless_tools  # noqa: E402
from agent0.workspace import StartupError, prepare_workspace  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_swebench_mini")
    parser.add_argument("--limit", type=int, required=True, choices=(1, 10))
    parser.add_argument("--out", required=True)
    parser.add_argument("--config", default=None)
    parser.add_argument("--network", action="store_true", help="Enable container network (off by default)")
    parser.add_argument("--image-namespace", default=None)
    parser.add_argument("--image-prefix", default=None, help="Prefix before instance slug")
    parser.add_argument("--row-cache", default=None, help="Local cache for Verified rows")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)

    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    config = load_config(Path(args.config) if args.config else ROOT / "agent.toml", cwd=ROOT)
    if not config.api_key:
        print("DEEPSEEK_API_KEY is not set", file=sys.stderr)
        return 2

    ids = selected_ids(args.limit)
    records: list[dict[str, str]] = []
    for instance_id in ids:
        instance_out = out / instance_id
        instance_out.mkdir(parents=True, exist_ok=True)
        row = fetch_verified_row(
            instance_id,
            cache_dir=Path(args.row_cache) if args.row_cache else None,
        )
        task = problem_task(row)
        assert_task_has_no_leaks(task, row)
        image = official_instance_image(
            instance_id,
            prefix=resolve_image_prefix(namespace=args.image_namespace, prefix=args.image_prefix),
        )
        session = Session.create(instance_out / "sessions")
        executor = DockerExecutor(
            image,
            workdir="/testbed",
            network=args.network,
            activate_conda=True,
            name=f"agent0-{instance_id.lower().replace('_', '-')}"[:60],
        )
        try:
            executor.start()
            try:
                start_commit = prepare_workspace(executor, allow_dirty=args.allow_dirty)
            except StartupError as exc:
                print(f"{instance_id}: {exc}", file=sys.stderr)
                records.append(prediction_record(instance_id, config.model, ""))
                continue
            execute(
                config=config,
                cwd=ROOT,
                task=task,
                session=session,
                events_path=instance_out / "events.jsonl",
                telemetry_path=instance_out / "telemetry.json",
                provider=DeepSeekProvider(config),
                tools=headless_tools(config),
                start_commit=start_commit,
                headless=True,
                executor=executor,
                patch_path=instance_out / "patch.diff",
            )
        finally:
            executor.close()
        patch = ""
        patch_path = instance_out / "patch.diff"
        if patch_path.is_file():
            patch = patch_path.read_text(encoding="utf-8")
        records.append(prediction_record(instance_id, config.model, patch))

    write_predictions(out / "predictions.jsonl", records)
    (out / "instance_ids.json").write_text(json.dumps(ids, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
