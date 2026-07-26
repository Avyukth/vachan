"""Shared Tier-2 fixtures for deterministic Vachan controller tests."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator

import pytest

from app.db import EvidenceLedger, connect_database, migrate_schema
from app.seeds import DEMO_TIME_ANCHOR, reset_and_reseed_demo_cases
from tests.fakes import (
    EvidenceAssertions,
    FakeSarvamClient,
    FrozenDemoClock,
    SarvamScenario,
    ScriptedTurn,
)


@pytest.fixture
def db_connection() -> Iterator[sqlite3.Connection]:
    """Return a migrated, seeded, isolated in-memory database."""

    connection = connect_database(":memory:")
    migrate_schema(connection)
    ledger = EvidenceLedger(connection)
    reset_and_reseed_demo_cases(ledger)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def evidence_ledger(db_connection: sqlite3.Connection) -> EvidenceLedger:
    return EvidenceLedger(db_connection)


@pytest.fixture
def frozen_demo_clock() -> FrozenDemoClock:
    return FrozenDemoClock(DEMO_TIME_ANCHOR)


@pytest.fixture
def fake_sarvam_factory() -> Callable[[SarvamScenario], FakeSarvamClient]:
    return FakeSarvamClient


@pytest.fixture
def correct_verification_scenario() -> SarvamScenario:
    """A deterministic caller turn; expected values remain outside model output."""

    return SarvamScenario(
        name="correct_verification",
        turns=(
            ScriptedTurn(
                transcript="मेरा जन्मदिन चौदह सितंबर है और अंतिम चार अंक 4729 हैं।",
                action={"intent": "verification_response"},
            ),
        ),
    )


@pytest.fixture
def evidence_assertions(db_connection: sqlite3.Connection) -> EvidenceAssertions:
    return EvidenceAssertions(db_connection)


@pytest.fixture
def assert_event_sequence(
    evidence_assertions: EvidenceAssertions,
) -> Callable[[str, list[str]], None]:
    return evidence_assertions.assert_event_sequence


@pytest.fixture
def assert_no_disclosure(evidence_assertions: EvidenceAssertions) -> Callable[[str], None]:
    return evidence_assertions.assert_no_disclosure


@pytest.fixture
def assert_single_disposition(evidence_assertions: EvidenceAssertions) -> Callable[[str], None]:
    return evidence_assertions.assert_single_disposition
