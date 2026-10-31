#!/usr/bin/env python3
"""Join per-instance telemetry.json with official harness results into one table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent0.swebench import format_summary_table, load_official_resolved, summarize_rows  # noqa: E402


def _load_telemetries(out_dir: Path) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for path in sorted(out_dir.glob("*/telemetry.json")):
        found[path.parent.name] = json.loads(path.read_text(encoding="utf-8"))
    return found


def _load_results(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_reports_dir(path: Path) -> dict[str, bool]:
    resolved: dict[str, bool] = {}
    for report in path.rglob("report.json"):
        data = json.loads(report.read_text(encoding="utf-8"))
        instance_id = data.get("instance_id") or report.parent.name
        if "resolved" in data:
            resolved[str(instance_id)] = bool(data["resolved"])
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="summarize_swebench")
    parser.add_argument("--out", required=True, help="Directory with <id>/telemetry.json")
    parser.add_argument("--results", default=None, help="Official results.json")
    parser.add_argument("--reports-dir", default=None, help="Official logs/evaluation/<run_id>")
    parser.add_argument("--table", default=None, help="Write markdown table here")
    args = parser.parse_args(argv)

    telemetries = _load_telemetries(Path(args.out))
    resolved: dict[str, bool] = {}
    if args.results:
        resolved.update(load_official_resolved(_load_results(Path(args.results))))
    if args.reports_dir:
        resolved.update(_load_reports_dir(Path(args.reports_dir)))
    rows = summarize_rows(telemetries=telemetries, resolved=resolved)
    table = format_summary_table(rows)
    if args.table:
        Path(args.table).write_text(table, encoding="utf-8")
    sys.stdout.write(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
