"""Deterministic, backend-only demo case fixtures.

Private verification and account values deliberately live behind nested types
that never participate in the public case summary.  SQLite persistence can
implement :class:`DemoSeedRepository` without coupling this fixture contract
to a particular schema.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from app.protocol import CaseSummary

DEMO_TIME_ZONE = ZoneInfo("Asia/Kolkata")
DEMO_TIME_ANCHOR = datetime(2026, 7, 26, 12, 0, tzinfo=DEMO_TIME_ZONE)
MOCK_DATA_LABEL = "DEMO / MOCK DATA"


@dataclass(frozen=True, slots=True, repr=False)
class VerificationSeed:
    """Expected values compared only by backend verification code."""

    birth_day: int
    birth_month: int
    reference_last4: str

    def __repr__(self) -> str:
        return "VerificationSeed(<redacted>)"


@dataclass(frozen=True, slots=True)
class InstallmentSeed:
    """One entry in a mock EMI schedule."""

    due_date: date
    amount_minor: int
    status: str


@dataclass(frozen=True, slots=True, repr=False)
class MockAccountSeed:
    """Account context that must stay server-side until identity is confirmed."""

    lender_name: str
    outstanding_minor: int
    emi_schedule: tuple[InstallmentSeed, ...]

    def __repr__(self) -> str:
        return "MockAccountSeed(<private account data>)"


@dataclass(frozen=True, slots=True)
class MockCaseSeed:
    """Complete backend fixture for one mock collection case."""

    case_id: str
    borrower_display_name: str
    eligible: bool
    contact_cap_remaining: int
    verification: VerificationSeed = field(repr=False)
    account: MockAccountSeed = field(repr=False)
    mock_data_label: str = MOCK_DATA_LABEL

    def public_summary(self) -> CaseSummary:
        """Return the only case fields safe to expose before verification."""
        return CaseSummary(
            case_id=self.case_id,
            borrower_display_name=self.borrower_display_name,
            eligible=self.eligible,
            contact_cap_remaining=self.contact_cap_remaining,
            mock_data=True,
        )


RAKESH_CASE = MockCaseSeed(
    case_id="case-rakesh-001",
    borrower_display_name="Rakesh Yadav",
    eligible=True,
    contact_cap_remaining=2,
    verification=VerificationSeed(
        birth_day=14,
        birth_month=9,
        reference_last4="4729",
    ),
    account=MockAccountSeed(
        lender_name="Sahyog Finance (Mock)",
        outstanding_minor=4_738_200,
        emi_schedule=(
            InstallmentSeed(date(2026, 4, 15), 789_700, "PAID"),
            InstallmentSeed(date(2026, 5, 15), 789_700, "PAID"),
            InstallmentSeed(date(2026, 6, 15), 789_700, "PAID"),
            InstallmentSeed(date(2026, 7, 15), 789_700, "OVERDUE"),
        ),
    ),
)

CONTACT_CAPPED_CASE = MockCaseSeed(
    case_id="case-capped-001",
    borrower_display_name="Meera Kulkarni",
    eligible=True,
    contact_cap_remaining=0,
    verification=VerificationSeed(
        birth_day=3,
        birth_month=2,
        reference_last4="8136",
    ),
    account=MockAccountSeed(
        lender_name="Sahyog Finance (Mock)",
        outstanding_minor=2_145_000,
        emi_schedule=(
            InstallmentSeed(date(2026, 5, 20), 715_000, "PAID"),
            InstallmentSeed(date(2026, 6, 20), 715_000, "PAID"),
            InstallmentSeed(date(2026, 7, 20), 715_000, "OVERDUE"),
        ),
    ),
)

DEMO_CASES = (RAKESH_CASE, CONTACT_CAPPED_CASE)


class DemoSeedRepository(Protocol):
    """Narrow persistence boundary for the sanctioned demo-only reset."""

    def replace_demo_cases(
        self,
        cases: Sequence[MockCaseSeed],
        *,
        demo_time_anchor: datetime,
    ) -> None:
        """Replace only seeded demo cases and their time anchor."""


def reset_and_reseed_demo_cases(repository: DemoSeedRepository) -> tuple[str, ...]:
    """Reseed exactly the two governed mock cases and return their IDs."""
    repository.replace_demo_cases(DEMO_CASES, demo_time_anchor=DEMO_TIME_ANCHOR)
    return tuple(case.case_id for case in DEMO_CASES)
