import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
DEV_PS1 = ROOT / "scripts" / "dev.ps1"
DEV_SH = ROOT / "scripts" / "dev.sh"
GITIGNORE = ROOT / ".gitignore"

REQUIRED_NAMES = (
    "AZURE_FOUNDRY_ENDPOINT",
    "THOUGHTSTAGE_AWS_PROFILE",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
)

FORBIDDEN_VALUES = (
    "latentspace-resource",
    "sk-",
    "SECRET",
    "AKIA",
    "aws_secret_access_key",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
)


def test_env_is_gitignored_and_example_has_names_only() -> None:
    ignored = GITIGNORE.read_text(encoding="utf-8")
    example = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert ".env" in ignored.splitlines() or ignored.startswith(".env")
    for name in REQUIRED_NAMES:
        assert name in example
        assert f"{name}=" in example
    for forbidden in FORBIDDEN_VALUES:
        assert forbidden not in example
    assert "https://" not in example
    for line in example.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        assert name in REQUIRED_NAMES
        assert value == ""


def test_dev_scripts_share_one_serve_process_and_print_wizard_url() -> None:
    powershell = DEV_PS1.read_text(encoding="utf-8")
    posix = DEV_SH.read_text(encoding="utf-8")

    for script in (powershell, posix):
        assert "thoughtstage serve" in script
        assert "pnpm --dir web dev" in script
        assert "http://127.0.0.1:5173/?view=builder" in script
        assert ".env" in script
        assert ".venv" in script
        assert "docker" not in script.lower()
        for forbidden in FORBIDDEN_VALUES:
            assert forbidden not in script
        assert "https://" not in script.replace("http://127.0.0.1", "")


def test_dev_scripts_do_not_assign_provider_env_values() -> None:
    for path in (DEV_PS1, DEV_SH):
        text = path.read_text(encoding="utf-8")
        assignment = re.compile(
            r"(?im)^(?:export\s+)?(?:openai_api_key|azure_foundry_endpoint|"
            r"thoughtstage_aws_profile|openai_base_url)\s*="
        )
        assert assignment.search(text) is None, (
            f"{path.name} must load .env at launch, not assign provider values"
        )
        assert "password" not in text.lower()
