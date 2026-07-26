from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"

SAFE_TERMINAL_SEQUENCE = (
    "blind-greeting",
    "hostile-opener",
    "anti-scam-response",
    "verification-request",
    "verification-values",
    "unlock-and-disclose",
    "promise-offer",
    "dual-format-readback",
    "handover",
    "spouse-demands-amount",
    "content-free-refusal",
    "borrower-return",
    "fresh-verification-request",
    "fresh-verification-values",
    "corrected-promise-offer",
    "corrected-readback",
    "explicit-yes",
    "commitment-confirmed",
)


def _load_script(filename: str) -> list[tuple[Any, ...]]:
    namespace = runpy.run_path(
        str(SCRIPT_DIR / filename),
        run_name=f"audio_tooling_contract_{filename}",
    )
    return namespace["SCRIPT"]


def _slug_sequence(script: list[tuple[Any, ...]]) -> tuple[str, ...]:
    return tuple(row[1] for row in script)


@pytest.mark.parametrize(
    "filename",
    [
        "make_demo_video_audio.py",
        "make_multilingual_demo_audio.py",
    ],
)
def test_demo_audio_scripts_preserve_terminal_order(filename: str) -> None:
    script = _load_script(filename)
    slugs = _slug_sequence(script)

    assert slugs == SAFE_TERMINAL_SEQUENCE
    assert slugs.index("handover") < slugs.index("explicit-yes")
    assert (
        slugs.index("borrower-return")
        < slugs.index("fresh-verification-request")
        < slugs.index("fresh-verification-values")
        < slugs.index("corrected-promise-offer")
        < slugs.index("corrected-readback")
        < slugs.index("explicit-yes")
    )
    assert slugs[-1] == "commitment-confirmed"


@pytest.mark.parametrize(
    "filename",
    [
        "make_demo_video_audio.py",
        "make_multilingual_demo_audio.py",
    ],
)
def test_verification_values_remain_borrower_spoken(filename: str) -> None:
    script = _load_script(filename)
    by_slug = {row[1]: row for row in script}

    for slug in ("verification-request", "fresh-verification-request"):
        row = by_slug[slug]
        text = row[2] if len(row) == 4 else row[3]
        assert row[0] == "agent"
        assert all(
            protected not in text
            for protected in (
                "14",
                "4729",
                "fourteenth",
                "four seven two nine",
                "चौदह",
                "चार सात दो नौ",
            )
        )

    for slug in ("verification-values", "fresh-verification-values"):
        assert by_slug[slug][0] in {"rakesh", "borrower"}
