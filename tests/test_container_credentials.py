from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_bedrock_compose_override_keeps_host_credentials_read_only() -> None:
    override_path = ROOT / "compose.bedrock.yaml"
    raw = override_path.read_text(encoding="utf-8")
    override = yaml.safe_load(raw)

    api = override["services"]["api"]
    assert api["environment"] == {
        "THOUGHTSTAGE_AWS_PROFILE": (
            "${THOUGHTSTAGE_AWS_PROFILE:"
            "?Set THOUGHTSTAGE_AWS_PROFILE to a short-lived AWS profile name}"
        )
    }
    assert api["volumes"] == [
        (
            "${THOUGHTSTAGE_AWS_CONFIG_DIR:"
            "?Set THOUGHTSTAGE_AWS_CONFIG_DIR to the host .aws directory}"
            ":/root/.aws:ro,z"
        )
    ]

    for credential_value_name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ):
        assert credential_value_name not in raw
