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

from pydantic import ValidationError

from thoughtstage import __version__
from thoughtstage.config import LoadedExperiment
from thoughtstage.files import ExperimentFileReader
from thoughtstage.models import FileToolEvent, ModelUsageEvent, PublicPost, Soliloquy


class RunBundleResumeError(ValueError):
    """Raised when an interrupted run cannot be resumed safely."""


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


def _read_jsonl_records(
    path: Path, *, repair_trailing_partial: bool = False
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = path.read_bytes()
    raw_lines = payload.splitlines(keepends=True)
    values: list[dict[str, Any]] = []
    for index, raw_line in enumerate(raw_lines):
        is_final = index == len(raw_lines) - 1
        terminated = raw_line.endswith((b"\n", b"\r"))
        content = raw_line.strip()
        if not content:
            if repair_trailing_partial and is_final and not terminated:
                with path.open("r+b") as stream:
                    stream.truncate(len(payload) - len(raw_line))
            continue
        try:
            line = content.decode("utf-8")
            value = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            if repair_trailing_partial and is_final and not terminated:
                with path.open("r+b") as stream:
                    stream.truncate(len(payload) - len(raw_line))
                return values
            raise RunBundleResumeError("run event stream contains invalid JSON") from exc
        if not isinstance(value, dict):
            raise RunBundleResumeError("run event is not an object")
        values.append(value)
        if repair_trailing_partial and is_final and not terminated:
            with path.open("ab") as stream:
                stream.write(b"\n")
    return values


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

        private_briefings = {
            agent.id: agent.private_briefing
            for agent in loaded.config.agents
            if agent.private_briefing is not None
        }
        private_briefing_inputs = [
            {"agent_id": agent_id, "sha256": sha256_bytes(content.encode("utf-8"))}
            for agent_id, content in private_briefings.items()
        ]
        self._write_json(self.path / "private" / "agent_briefings.json", private_briefings)
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
                "system_prompt": loaded.config.system_prompt,
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
            "inputs": {
                "files": self.files,
                "private_briefings": private_briefing_inputs,
            },
            "counts": {
                "public_posts": 0,
                "soliloquies": 0,
                "model_calls": 0,
                "file_tool_calls": 0,
            },
        }
        self._write_manifest()

    @classmethod
    def resume(cls, loaded: LoadedExperiment, bundle_path: str | Path) -> RunBundleWriter:
        """Open an interrupted bundle after verifying its immutable prefix."""

        try:
            path = Path(bundle_path).resolve(strict=True)
        except FileNotFoundError as exc:
            raise RunBundleResumeError("run bundle was not found") from exc
        if not path.is_dir():
            raise RunBundleResumeError("run bundle must be a directory")
        try:
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            files = json.loads((path / "files.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise RunBundleResumeError("run bundle metadata is missing or invalid") from exc
        if not isinstance(manifest, dict) or not isinstance(files, list):
            raise RunBundleResumeError("run bundle metadata has an invalid shape")
        if manifest.get("status") == "completed":
            raise RunBundleResumeError("run bundle is already completed")
        if manifest.get("run_id") != path.name:
            raise RunBundleResumeError("run id does not match the bundle directory")
        expected_hash = sha256_bytes(loaded.source_bytes)
        if manifest.get("experiment", {}).get("config_sha256") != expected_hash:
            raise RunBundleResumeError("experiment manifest does not match the run bundle")

        self = cls.__new__(cls)
        self.run_id = path.name
        self.path = path
        self.files = files
        self.manifest = manifest
        posts, soliloquies = self.existing_events(repair_trailing_partial=True)
        model_usage = self.existing_model_usage(repair_trailing_partial=True)
        file_tool_events = self.existing_file_tool_events(repair_trailing_partial=True)
        if len(posts) != len(soliloquies):
            raise RunBundleResumeError("public and private event counts do not match")

        resumptions = self.manifest.setdefault("resumptions", [])
        if not isinstance(resumptions, list):
            raise RunBundleResumeError("run bundle resumptions metadata is invalid")
        resumptions.append(
            {
                "resumed_at": datetime.now(UTC).isoformat(),
                "thoughtstage_version": __version__,
                "source_revision": _source_revision(loaded.source_path.parent),
                "completed_prefix": len(posts),
            }
        )
        self.manifest["status"] = "running"
        self.manifest["completed_at"] = None
        self.manifest["counts"] = {
            "public_posts": len(posts),
            "soliloquies": len(soliloquies),
            "model_calls": len(model_usage),
            "file_tool_calls": len(file_tool_events),
        }
        self._write_manifest()
        return self

    def existing_events(
        self,
        *,
        repair_trailing_partial: bool = False,
    ) -> tuple[list[PublicPost], list[Soliloquy]]:
        """Load the typed, append-only event prefix from this bundle."""

        try:
            posts = [
                PublicPost.model_validate(value)
                for value in _read_jsonl_records(
                    self.path / "public.jsonl",
                    repair_trailing_partial=repair_trailing_partial,
                )
            ]
            soliloquies = [
                Soliloquy.model_validate(value)
                for value in _read_jsonl_records(
                    self.path / "private" / "soliloquies.jsonl",
                    repair_trailing_partial=repair_trailing_partial,
                )
            ]
        except ValidationError as exc:
            raise RunBundleResumeError("run event stream violates its schema") from exc
        return posts, soliloquies

    def existing_model_usage(
        self,
        *,
        repair_trailing_partial: bool = False,
    ) -> list[ModelUsageEvent]:
        """Load researcher-private provider usage records from this bundle."""

        try:
            return [
                ModelUsageEvent.model_validate(value)
                for value in _read_jsonl_records(
                    self.path / "private" / "model_usage.jsonl",
                    repair_trailing_partial=repair_trailing_partial,
                )
            ]
        except ValidationError as exc:
            raise RunBundleResumeError("model usage stream violates its schema") from exc

    def existing_file_tool_events(
        self,
        *,
        repair_trailing_partial: bool = False,
    ) -> list[FileToolEvent]:
        """Load researcher-private experiment-file tool records from this bundle."""

        try:
            return [
                FileToolEvent.model_validate(value)
                for value in _read_jsonl_records(
                    self.path / "private" / "file_tools.jsonl",
                    repair_trailing_partial=repair_trailing_partial,
                )
            ]
        except ValidationError as exc:
            raise RunBundleResumeError("file tool stream violates its schema") from exc

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

    def write_model_usage(self, usage: ModelUsageEvent) -> None:
        self._append_jsonl(
            self.path / "private" / "model_usage.jsonl",
            usage.model_dump(mode="json"),
        )

    def write_file_tool_event(self, event: FileToolEvent) -> None:
        self._append_jsonl(
            self.path / "private" / "file_tools.jsonl",
            event.model_dump(mode="json"),
        )

    def finish(
        self,
        *,
        public_posts: int,
        soliloquies: int,
        model_calls: int,
        file_tool_calls: int,
    ) -> None:
        self.manifest["status"] = "completed"
        self.manifest["completed_at"] = datetime.now(UTC).isoformat()
        self.manifest["counts"] = {
            "public_posts": public_posts,
            "soliloquies": soliloquies,
            "model_calls": model_calls,
            "file_tool_calls": file_tool_calls,
        }
        self._write_manifest()
