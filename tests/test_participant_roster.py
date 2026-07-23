from fastapi.testclient import TestClient

from thoughtstage.api import app
from thoughtstage.participant_roster import (
    ParticipantRosterRequest,
    generate_participant_roster,
)


def test_generated_roster_is_seeded_stable_and_explicit() -> None:
    request = ParticipantRosterRequest(count=4, theme="trees", seed=2026)

    first = generate_participant_roster(request)
    second = generate_participant_roster(request)

    assert first == second
    assert first.generator_version == "alias-v1"
    assert [participant.id for participant in first.participants] == [
        "agent-1",
        "agent-2",
        "agent-3",
        "agent-4",
    ]
    assert [participant.display_name for participant in first.participants] == [
        "Linden",
        "Olive",
        "Cedar",
        "Larch",
    ]
    assert len({participant.display_name for participant in first.participants}) == 4


def test_roster_seed_changes_order_without_changing_theme_membership() -> None:
    first = generate_participant_roster(
        ParticipantRosterRequest(count=32, theme="mountains", seed=7)
    )
    second = generate_participant_roster(
        ParticipantRosterRequest(count=32, theme="mountains", seed=8)
    )

    first_names = [participant.display_name for participant in first.participants]
    second_names = [participant.display_name for participant in second.participants]
    assert first_names != second_names
    assert set(first_names) == set(second_names)


def test_neutral_roster_uses_unprimed_numbered_names() -> None:
    roster = generate_participant_roster(
        ParticipantRosterRequest(count=3, theme="neutral", seed=999)
    )

    assert [participant.display_name for participant in roster.participants] == [
        "Participant 01",
        "Participant 02",
        "Participant 03",
    ]


def test_roster_api_rejects_oversized_generation_request() -> None:
    response = TestClient(app).post(
        "/api/participant-rosters",
        json={"count": 33, "theme": "trees", "seed": 42},
    )

    assert response.status_code == 422
    assert "less than or equal to 32" in response.text
