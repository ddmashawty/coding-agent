from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import pull_swebench_images as pull  # noqa: E402


def test_images_for_limit_1_matches_official_name() -> None:
    pairs = pull.images_for_limit(1, namespace="swebench", prefix=None)
    assert pairs == [
        (
            "django__django-11790",
            "swebench/sweb.eval.x86_64.django_1776_django-11790",
        )
    ]


def test_images_for_limit_honors_prefix() -> None:
    pairs = pull.images_for_limit(1, namespace=None, prefix="reg.example/sweb.eval.x86_64.")
    assert pairs[0][1] == "reg.example/sweb.eval.x86_64.django_1776_django-11790"


def test_pull_all_skips_existing_and_records_size() -> None:
    pulled: list[str] = []
    pairs = [
        ("django__django-11790", "swebench/sweb.eval.x86_64.django_1776_django-11790"),
        ("sphinx-doc__sphinx-8475", "swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-8475"),
    ]

    def exists(image: str) -> bool:
        return image.endswith("django-11790")

    def size(image: str) -> int:
        return 1024 if image.endswith("django-11790") else 2048

    def do_pull(image: str) -> int:
        pulled.append(image)
        return 0

    clock = iter([10.0, 12.5])
    code = pull.pull_all(
        pairs,
        pull=do_pull,
        exists=exists,
        size=size,
        clock=lambda: next(clock),
    )
    assert code == 0
    assert pulled == ["swebench/sweb.eval.x86_64.sphinx-doc_1776_sphinx-8475"]


def test_epoch_source_keeps_raw_instance_id() -> None:
    assert pull.epoch_source_image("django__django-11880") == (
        "ghcr.io/epoch-research/swe-bench.eval.x86_64.django__django-11880"
    )
    assert pull.with_latest("swebench/sweb.eval.x86_64.django_1776_django-11880") == (
        "swebench/sweb.eval.x86_64.django_1776_django-11880:latest"
    )


def test_pull_all_epoch_tags_to_official_name() -> None:
    pulled: list[str] = []
    tagged: list[tuple[str, str]] = []
    pairs = [
        ("django__django-11880", "swebench/sweb.eval.x86_64.django_1776_django-11880"),
    ]
    clock = iter([1.0, 4.0])
    code = pull.pull_all(
        pairs,
        source="epoch",
        pull=lambda image: pulled.append(image) or 0,
        exists=lambda image: False,
        size=lambda image: 2048,
        tag=lambda src, dest: tagged.append((src, dest)) or 0,
        clock=lambda: next(clock),
    )
    assert code == 0
    assert pulled == ["ghcr.io/epoch-research/swe-bench.eval.x86_64.django__django-11880"]
    assert tagged == [
        (
            "ghcr.io/epoch-research/swe-bench.eval.x86_64.django__django-11880",
            "swebench/sweb.eval.x86_64.django_1776_django-11880",
        )
    ]


def test_epoch_skips_when_official_target_exists() -> None:
    pulled: list[str] = []
    pairs = [
        ("django__django-11880", "swebench/sweb.eval.x86_64.django_1776_django-11880"),
    ]
    code = pull.pull_all(
        pairs,
        source="epoch",
        pull=lambda image: pulled.append(image) or 0,
        exists=lambda image: True,
        size=lambda image: 1024,
    )
    assert code == 0
    assert pulled == []


def test_format_bytes() -> None:
    assert pull.format_bytes(512) == "512B"
    assert pull.format_bytes(10 * 1024 * 1024) == "10.0MB"
    assert pull.format_bytes(None) == "unknown"


def test_main_writes_log(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "nested" / "pull.log"

    def fake_pull_all(pairs, **kwargs):
        print(f"images={len(pairs)} {pairs[0][0]}")
        return 0

    monkeypatch.setattr(pull, "pull_all", fake_pull_all)
    code = pull.main(["--limit", "1", "--log", str(log)])
    assert code == 0
    text = log.read_text(encoding="utf-8")
    assert "images=1 limit=1 source=hub" in text
    assert "django__django-11790" in text
