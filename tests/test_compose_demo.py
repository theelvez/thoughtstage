from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_default_compose_services_have_no_profile() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert set(services) == {"api", "web", "demo"}
    assert "profiles" not in services["api"]
    assert "profiles" not in services["web"]


def test_demo_profile_runs_hello_stage_without_secrets() -> None:
    raw = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    compose = yaml.safe_load(raw)
    demo = compose["services"]["demo"]
    command = demo["command"]
    joined = " ".join(command) if isinstance(command, list) else str(command)

    assert demo["profiles"] == ["demo"]
    assert demo["restart"] == "no"
    assert "examples/hello-stage/run_compose_demo.py" in joined

    web = compose["services"]["web"]
    depends = web["depends_on"]
    assert depends["api"]["condition"] == "service_healthy"
    assert depends["demo"]["condition"] == "service_completed_successfully"
    assert depends["demo"]["required"] is False

    script_path = ROOT / "examples" / "hello-stage" / "run_compose_demo.py"
    script = script_path.read_text(encoding="utf-8")
    assert "examples/hello-stage/experiment.yaml" in script
    assert 'RUN_ID = "hello-stage-demo"' in script
    assert "--run-id" in script
    assert "/?run={RUN_ID}" in script

    for credential_value_name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "OPENAI_API_KEY",
        "AZURE_FOUNDRY_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        assert credential_value_name not in raw
        assert credential_value_name not in script
