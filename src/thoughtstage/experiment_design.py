"""Compile researcher-friendly experiment drafts into validated artifacts."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path, PurePosixPath

import yaml
from pydantic import Field, field_validator, model_validator

from thoughtstage.models import ExperimentConfig, StrictModel

MAX_MATERIAL_BYTES = 1_000_000
MAX_TOTAL_MATERIAL_BYTES = 5_000_000


class ExperimentDesignError(ValueError):
    """Raised when a draft cannot be compiled safely."""


class ExperimentAlreadyExistsError(ExperimentDesignError):
    """Raised when a researcher tries to replace an existing experiment."""


class ExperimentMaterial(StrictModel):
    """One UTF-8 research file to place inside the experiment boundary."""

    path: str = Field(min_length=1, max_length=240)
    content: str

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        if "\\" in value:
            raise ValueError("material paths must use forward slashes")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("material paths must remain inside the experiment files directory")
        reserved_names = {"CON", "PRN", "AUX", "NUL"} | {
            f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
        }
        for part in path.parts:
            if part.startswith("."):
                raise ValueError("hidden material paths are not supported")
            if any(character in '<>:"|?*' or ord(character) < 32 for character in part):
                raise ValueError("material paths must be portable across Windows and Linux")
            if part.endswith((" ", ".")) or part.split(".", 1)[0].upper() in reserved_names:
                raise ValueError("material paths must be portable across Windows and Linux")
        return path.as_posix()

    @model_validator(mode="after")
    def validate_size(self) -> ExperimentMaterial:
        if len(self.content.encode("utf-8")) > MAX_MATERIAL_BYTES:
            raise ValueError(f"material files cannot exceed {MAX_MATERIAL_BYTES} UTF-8 bytes")
        return self


class ExperimentDraft(StrictModel):
    """A typed wizard submission that can be rendered without guessing."""

    experiment: ExperimentConfig
    materials: tuple[ExperimentMaterial, ...] = ()

    @model_validator(mode="after")
    def validate_material_contract(self) -> ExperimentDraft:
        paths = [material.path for material in self.materials]
        if len(paths) != len(set(paths)):
            raise ValueError("material paths must be unique")
        if self.materials and self.experiment.files_dir != "files":
            raise ValueError("experiments with wizard materials must declare files_dir: files")
        if not self.materials and self.experiment.files_dir is not None:
            raise ValueError("files_dir must be omitted when no wizard materials are supplied")
        total = sum(len(material.content.encode("utf-8")) for material in self.materials)
        if total > MAX_TOTAL_MATERIAL_BYTES:
            raise ValueError(
                f"combined material files cannot exceed {MAX_TOTAL_MATERIAL_BYTES} UTF-8 bytes"
            )
        return self


class _ReadableYamlDumper(yaml.SafeDumper):
    pass


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_ReadableYamlDumper.add_representer(str, _represent_string)


def render_experiment_yaml(draft: ExperimentDraft) -> str:
    """Render the already-validated experiment contract as readable YAML."""

    payload = draft.experiment.model_dump(mode="json", exclude_none=True)
    return yaml.dump(
        payload,
        Dumper=_ReadableYamlDumper,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )


def artifact_paths(draft: ExperimentDraft) -> tuple[str, ...]:
    paths = ["experiment.yaml"]
    paths.extend(f"files/{material.path}" for material in draft.materials)
    return tuple(paths)


def save_experiment_draft(draft: ExperimentDraft, root: Path) -> Path:
    """Atomically create a new experiment directory without replacing prior work."""

    resolved_root = root.resolve()
    resolved_root.mkdir(parents=True, exist_ok=True)
    target = resolved_root / draft.experiment.id
    if target.exists():
        raise ExperimentAlreadyExistsError(
            f"experiment {draft.experiment.id!r} already exists; choose a new experiment id"
        )

    temporary = Path(tempfile.mkdtemp(prefix=f".{draft.experiment.id}-", dir=resolved_root))
    try:
        (temporary / "experiment.yaml").write_text(
            render_experiment_yaml(draft), encoding="utf-8", newline="\n"
        )
        if draft.materials:
            files_root = temporary / "files"
            for material in draft.materials:
                destination = files_root.joinpath(*PurePosixPath(material.path).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(material.content, encoding="utf-8", newline="\n")
        temporary.replace(target)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target
