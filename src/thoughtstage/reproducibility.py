"""Create self-describing, secret-free experiment run bundles."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from thoughtstage import __version__
from thoughtstage.config import LoadedExperiment
from thoughtstage.files import ExperimentFileReader
from thoughtstage.models import PublicPost, Soliloquy


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _source_revision(start: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def collect_files(root: Path | None) -> list[dict[str, Any]]:
    if root is None:
        return []
    reader = ExperimentFileReader(root)
    return [reader.file_info(item["path"]) for item in reader.list_files("*")]


class RunBundleWriter:
    def __init__(
        self,
        loaded: LoadedExperiment,
        output_root: str | Path,
        *,
        run_id: str | None = None,
    ) -> None:
        config_hash = sha256_bytes(loaded.source_bytes)
        generated_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-{config_hash[:8]}"
        self.run_id = run_id or generated_id
        self.path = Path(output_root).resolve() / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "private").mkdir()
        (self.path / "experiment.yaml").write_bytes(loaded.source_bytes)

        self.files = collect_files(loaded.files_root)
        self._write_json(self.path / "files.json", self.files)
        self.manifest: dict[str, Any] = {
            "schema_version": "0.1",
            "run_id": self.run_id,
            "status": "running",
            "created_at": datetime.now(UTC).isoformat(),
            "completed_at": None,
            "thoughtstage": {
                "version": __version__,
                "source_revision": _source_revision(loaded.source_path.parent),
            },
            "experiment": {
                "id": loaded.config.id,
                "name": loaded.config.name,
                "config_sha256": config_hash,
            },
            "execution": {
                "rounds": loaded.config.rounds,
                "schedule": loaded.config.schedule.value,
                "turn_order": loaded.config.turn_order.value,
                "private_memory": loaded.config.private_memory.value,
                "seed": loaded.config.seed,
            },
            "agents": [
                {
                    "id": agent.id,
                    "display_name": agent.display_name,
                    "provider": agent.provider,
                    "model": agent.model,
                    "credential_env": agent.credential_env,
                    "temperature": agent.temperature,
                    "parameters": agent.parameters,
                }
                for agent in loaded.config.agents
            ],
            "environment": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
            },
            "inputs": {"files": self.files},
            "counts": {"public_posts": 0, "soliloquies": 0},
        }
        self._write_manifest()

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _append_jsonl(path: Path, value: Any) -> None:
        with path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(value, sort_keys=True, ensure_ascii=False) + "\n")

    def _write_manifest(self) -> None:
        self._write_json(self.path / "manifest.json", self.manifest)

    def write_post(self, post: PublicPost) -> None:
        self._append_jsonl(self.path / "public.jsonl", post.model_dump(mode="json"))

    def write_soliloquy(self, soliloquy: Soliloquy) -> None:
        self._append_jsonl(
            self.path / "private" / "soliloquies.jsonl",
            soliloquy.model_dump(mode="json"),
        )

    def finish(self, *, public_posts: int, soliloquies: int) -> None:
        self.manifest["status"] = "completed"
        self.manifest["completed_at"] = datetime.now(UTC).isoformat()
        self.manifest["counts"] = {
            "public_posts": public_posts,
            "soliloquies": soliloquies,
        }
        self._write_manifest()
