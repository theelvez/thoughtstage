from fastapi.testclient import TestClient

from thoughtstage.api import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_experiment_schema_has_one_shared_prompt() -> None:
    schema = client.get("/api/schema/experiment").json()
    properties = schema["properties"]

    assert "system_prompt" in properties
    assert "stimuli" in properties
    assert "agents" in properties


def test_design_contract_is_explicit() -> None:
    contract = client.get("/api/design-contract").json()

    assert contract["private_channel"] == "soliloquies are researcher-only"
    assert contract["scheduled_stimuli"] == (
        "typed public events declared in the experiment manifest"
    )
    assert contract["default_private_memory"] == "none"
