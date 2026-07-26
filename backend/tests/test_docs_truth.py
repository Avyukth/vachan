"""Executable honesty checks for the public development documentation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.main import app

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROOT_README = PROJECT_ROOT / "README.md"
FRONTEND_README = PROJECT_ROOT / "frontend" / "README.md"

MOUNTED_START = "<!-- mounted-api:start -->"
MOUNTED_END = "<!-- mounted-api:end -->"
CONTRACT_START = "<!-- contract-api:start -->"
CONTRACT_END = "<!-- contract-api:end -->"
ROUTE_ROW = re.compile(r"^\|\s*(GET|POST|WS)\s*\|\s*`([^`]+)`\s*\|")


def _marked_section(markdown: str, start: str, end: str) -> str:
    try:
        return markdown.split(start, maxsplit=1)[1].split(end, maxsplit=1)[0]
    except IndexError as error:
        raise AssertionError(f"README is missing required markers {start!r} / {end!r}") from error


def _documented_routes(section: str) -> set[tuple[str, str]]:
    return {
        (match.group(1), match.group(2))
        for line in section.splitlines()
        if (match := ROUTE_ROW.match(line))
    }


def _walk_routes(routes: Iterable[Any]) -> Iterable[Any]:
    """Flatten FastAPI routes across eager and lazy included-router versions."""

    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _walk_routes(included.routes)
        else:
            yield route


def _mounted_product_routes() -> set[tuple[str, str]]:
    mounted: set[tuple[str, str]] = set()
    for route in _walk_routes(app.routes):
        path = getattr(route, "path", "")
        if not (path == "/healthz" or path.startswith("/api/") or path.startswith("/ws/")):
            continue
        if "/dev/" in path or "/spike/" in path or "audio-spike" in path:
            continue

        methods = getattr(route, "methods", None)
        if methods:
            mounted.update(
                (method, path) for method in methods if method not in {"HEAD", "OPTIONS"}
            )
        else:
            mounted.add(("WS", path))
    return mounted


def test_readme_mounted_api_table_matches_real_route_registry() -> None:
    markdown = ROOT_README.read_text(encoding="utf-8")
    documented = _documented_routes(_marked_section(markdown, MOUNTED_START, MOUNTED_END))
    mounted = _mounted_product_routes()

    assert documented == mounted, (
        "README mounted API table drifted from the FastAPI route registry.\n"
        f"Documented but not mounted: {sorted(documented - mounted)}\n"
        f"Mounted but undocumented: {sorted(mounted - documented)}"
    )


def test_unmounted_evidence_endpoint_is_labeled_contract_only() -> None:
    markdown = ROOT_README.read_text(encoding="utf-8")
    mounted = _documented_routes(_marked_section(markdown, MOUNTED_START, MOUNTED_END))
    contracted = _documented_routes(_marked_section(markdown, CONTRACT_START, CONTRACT_END))

    evidence_route = ("GET", "/api/evidence/{call_id}")
    assert evidence_route not in mounted
    assert evidence_route in contracted


def test_frontend_readme_is_bun_only() -> None:
    markdown = FRONTEND_README.read_text(encoding="utf-8")
    prohibited = sorted(
        {
            match.group(0).casefold()
            for match in re.finditer(r"\b(?:npm|pnpm|yarn)\b", markdown, re.IGNORECASE)
        }
    )

    assert prohibited == [], f"frontend README contains non-bun commands: {prohibited}"
    for command in ("bun install", "bun run check", "bun run build"):
        assert command in markdown, f"frontend README is missing required command: {command}"


def test_readme_distinguishes_synthetic_stt_from_pending_live_proof() -> None:
    markdown = ROOT_README.read_text(encoding="utf-8")

    for required in (
        "synthetic-hi-IN",
        "real Saaras STT",
        "not a real human/live call",
        "sarvam-v8o",
        "sarvam-ch1",
        "sarvam-ztt",
    ):
        assert required in markdown, f"README is missing honesty marker: {required}"

    assert re.search(r"\(\d+\s+beads\b", markdown, re.IGNORECASE) is None, (
        "README hard-codes a bead count; direct readers to br stats instead"
    )
