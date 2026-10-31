#!/usr/bin/env python3
"""Pull official SWE-bench instance images. Safe to rerun; skips images already local.

Example (foreground):
    uv run python scripts/pull_swebench_images.py --limit 10 --log runs/pull-10.log

Example (background):
    nohup uv run python scripts/pull_swebench_images.py --limit 10 --log runs/pull-10.log >/dev/null 2>&1 &
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent0.executors.docker import official_instance_image  # noqa: E402
from agent0.swebench import ids_for_limit, resolve_image_prefix  # noqa: E402

SOURCES = ("hub", "epoch")


def epoch_source_image(instance_id: str, *, arch: str = "x86_64") -> str:
    """Epoch GHCR name keeps the raw instance_id (no __ → _1776_ rewrite)."""
    return f"ghcr.io/epoch-research/swe-bench.eval.{arch}.{instance_id}"


def with_latest(image: str) -> str:
    name = image.rsplit("/", 1)[-1]
    if ":" in name:
        return image
    return f"{image}:latest"


def format_bytes(size: int | None) -> str:
    if size is None:
        return "unknown"
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(value)}{unit}"
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def image_exists(image: str) -> bool:
    completed = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def image_size(image: str) -> int | None:
    completed = subprocess.run(
        ["docker", "image", "inspect", "-f", "{{.Size}}", image],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    try:
        return int(completed.stdout.strip())
    except ValueError:
        return None


def pull_image(image: str) -> int:
    return subprocess.run(["docker", "pull", image]).returncode


def tag_image(source: str, target: str) -> int:
    return subprocess.run(["docker", "tag", source, with_latest(target)]).returncode


def images_for_limit(limit: int, *, namespace: str | None, prefix: str | None) -> list[tuple[str, str]]:
    resolved = resolve_image_prefix(namespace=namespace, prefix=prefix)
    return [
        (instance_id, official_instance_image(instance_id, prefix=resolved))
        for instance_id in ids_for_limit(limit)
    ]


class Tee:
    def __init__(self, *streams) -> None:
        self.streams = streams

    def write(self, data: str) -> int:
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


def pull_all(
    pairs: list[tuple[str, str]],
    *,
    source: str = "hub",
    pull=pull_image,
    exists=image_exists,
    size=image_size,
    tag=tag_image,
    clock=time.monotonic,
) -> int:
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    failed: list[str] = []
    for instance_id, image in pairs:
        if exists(image):
            print(f"skip {instance_id} {image} size={format_bytes(size(image))} (already local)")
            continue
        remote = image if source == "hub" else epoch_source_image(instance_id)
        label = remote if remote == image else f"{remote} -> {image}"
        print(f"pull {instance_id} {label}")
        started = clock()
        code = pull(remote)
        if code == 0 and remote != image:
            code = tag(remote, image)
        elapsed = clock() - started
        if code != 0:
            print(f"fail {instance_id} {label} elapsed={elapsed:.1f}s")
            failed.append(instance_id)
            continue
        print(
            f"done {instance_id} {image} elapsed={elapsed:.1f}s size={format_bytes(size(image))}"
        )
    print(f"summary pulled_or_skipped={len(pairs) - len(failed)} failed={len(failed)}")
    if failed:
        print("failed: " + " ".join(failed))
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pull_swebench_images")
    parser.add_argument("--limit", type=int, required=True, choices=(1, 10, 50))
    parser.add_argument("--namespace", default=None, help="Docker Hub namespace (default swebench)")
    parser.add_argument(
        "--image-prefix",
        default=None,
        help="Full prefix before the instance slug, e.g. swebench/sweb.eval.x86_64.",
    )
    parser.add_argument("--log", default=None, help="Also write stdout/stderr to this file")
    parser.add_argument(
        "--source",
        choices=SOURCES,
        default="hub",
        help="hub = Docker Hub swebench (default); epoch = GHCR then tag to the Hub name",
    )
    args = parser.parse_args(argv)

    log_file = None
    stdout = sys.stdout
    stderr = sys.stderr
    if args.log:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_file = log_path.open("a", encoding="utf-8")
        sys.stdout = Tee(stdout, log_file)  # type: ignore[assignment]
        sys.stderr = Tee(stderr, log_file)  # type: ignore[assignment]

    try:
        pairs = images_for_limit(args.limit, namespace=args.namespace, prefix=args.image_prefix)
        print(f"images={len(pairs)} limit={args.limit} source={args.source}")
        return pull_all(pairs, source=args.source)
    finally:
        sys.stdout = stdout
        sys.stderr = stderr
        if log_file is not None:
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
