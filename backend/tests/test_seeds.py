"""Tests for deterministic, privacy-separated demo fixtures."""

from collections.abc import Sequence
from datetime import datetime

from app.seeds import (
    CONTACT_CAPPED_CASE,
    DEMO_CASES,
    DEMO_TIME_ANCHOR,
    MOCK_DATA_LABEL,
    RAKESH_CASE,
    MockCaseSeed,
    reset_and_reseed_demo_cases,
)


def test_exactly_two_stable_mock_cases_are_seeded() -> None:
    assert DEMO_CASES == (RAKESH_CASE, CONTACT_CAPPED_CASE)
    assert [case.case_id for case in DEMO_CASES] == [
        "case-rakesh-001",
        "case-capped-001",
    ]
    assert all(case.mock_data_label == MOCK_DATA_LABEL for case in DEMO_CASES)


def test_rakesh_is_eligible_and_control_case_is_blocked_by_contact_cap() -> None:
    assert RAKESH_CASE.borrower_display_name == "Rakesh Yadav"
    assert RAKESH_CASE.eligible
    assert RAKESH_CASE.contact_cap_remaining > 0

    assert CONTACT_CAPPED_CASE.eligible
    assert CONTACT_CAPPED_CASE.contact_cap_remaining == 0


def test_public_summaries_exclude_verification_and_account_values() -> None:
    summary = RAKESH_CASE.public_summary().model_dump()

    assert set(summary) == {
        "api_version",
        "case_id",
        "borrower_display_name",
        "eligible",
        "contact_cap_remaining",
        "mock_data",
    }
    assert summary["mock_data"] is True
    assert "4729" not in repr(summary)
    assert "Sahyog Finance" not in repr(summary)
    assert "outstanding_minor" not in summary


def test_private_values_are_redacted_from_accidental_repr_logging() -> None:
    rendered = repr(RAKESH_CASE)

    assert "4729" not in rendered
    assert "Sahyog Finance" not in rendered
    assert "4738200" not in rendered


def test_seeded_demo_time_is_aware_and_uses_asia_kolkata() -> None:
    assert DEMO_TIME_ANCHOR.utcoffset() is not None
    assert DEMO_TIME_ANCHOR.tzinfo is not None
    assert getattr(DEMO_TIME_ANCHOR.tzinfo, "key", None) == "Asia/Kolkata"
    assert DEMO_TIME_ANCHOR.isoformat() == "2026-07-26T12:00:00+05:30"


def test_mock_accounts_have_positive_minor_units_and_an_emi_schedule() -> None:
    for case in DEMO_CASES:
        assert case.account.outstanding_minor > 0
        assert case.account.emi_schedule
        assert all(installment.amount_minor > 0 for installment in case.account.emi_schedule)


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[MockCaseSeed, ...], datetime]] = []

    def replace_demo_cases(
        self,
        cases: Sequence[MockCaseSeed],
        *,
        demo_time_anchor: datetime,
    ) -> None:
        self.calls.append((tuple(cases), demo_time_anchor))


def test_reset_reseeds_exactly_the_governed_rows_and_anchor() -> None:
    repository = RecordingRepository()

    seeded_ids = reset_and_reseed_demo_cases(repository)

    assert seeded_ids == ("case-rakesh-001", "case-capped-001")
    assert repository.calls == [(DEMO_CASES, DEMO_TIME_ANCHOR)]
