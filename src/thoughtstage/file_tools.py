"""Validated, read-only model tools for experiment-scoped files."""

from __future__ import annotations

import hashlib
import json
from typing import Any, ClassVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from thoughtstage.files import ExperimentFileReader, FileAccessError
from thoughtstage.models import FileToolCall, FileToolOperation, ModelUsagePhase


class _ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _ListFilesInput(_ToolInput):
    pattern: str = Field(default="*", min_length=1, max_length=256)


class _FileInfoInput(_ToolInput):
    path: str = Field(min_length=1, max_length=1_024)


class _ReadTextInput(_ToolInput):
    path: str = Field(min_length=1, max_length=1_024)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)


class _SearchTextInput(_ToolInput):
    query: str = Field(min_length=1, max_length=500)
    path: str | None = Field(default=None, min_length=1, max_length=1_024)
    max_results: int = Field(default=20, ge=1, le=100)


_INPUT_MODELS = {
    "list_files": _ListFilesInput,
    "file_info": _FileInfoInput,
    "read_text": _ReadTextInput,
    "search_text": _SearchTextInput,
}


class ExperimentFileTools:
    """Expose safe file reads to providers without exposing the filesystem root."""

    definitions: ClassVar[tuple[dict[str, Any], ...]] = (
        {
            "name": "list_files",
            "description": "List readable experiment files matching an optional glob.",
            "input_schema": {
                "type": "object",
                "properties": {"pattern": {"type": "string", "default": "*"}},
                "additionalProperties": False,
            },
        },
        {
            "name": "file_info",
            "description": "Return size and SHA-256 metadata for an experiment file.",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "read_text",
            "description": "Read a bounded line range from a UTF-8 experiment file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1, "default": 1},
                    "end_line": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "search_text",
            "description": "Search experiment files for case-insensitive text matches.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20,
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    )

    def __init__(self, reader: ExperimentFileReader) -> None:
        self._reader = reader

    @classmethod
    def from_root(cls, root: str) -> ExperimentFileTools:
        return cls(ExperimentFileReader(root))

    @staticmethod
    def _serialize(value: Any) -> tuple[str, str, int]:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True)
        payload = result.encode("utf-8")
        return result, hashlib.sha256(payload).hexdigest(), len(payload)

    def execute(
        self,
        *,
        name: str,
        tool_use_id: str,
        phase: ModelUsagePhase,
        raw_input: Any,
    ) -> tuple[str, FileToolCall]:
        model = _INPUT_MODELS.get(name)
        operation = cast(FileToolOperation, name) if model is not None else "unknown"
        validated: _ToolInput | None = None
        error_code: str | None = None
        try:
            if model is None:
                raise LookupError
            validated = model.model_validate(raw_input)
            if isinstance(validated, _ListFilesInput):
                value = self._reader.list_files(validated.pattern)
            elif isinstance(validated, _FileInfoInput):
                value = self._reader.file_info(validated.path)
            elif isinstance(validated, _ReadTextInput):
                value = self._reader.read_text(
                    validated.path,
                    start_line=validated.start_line,
                    end_line=validated.end_line,
                )
            elif isinstance(validated, _SearchTextInput):
                value = self._reader.search_text(
                    validated.query,
                    path=validated.path,
                    max_results=validated.max_results,
                )
            else:  # pragma: no cover - exhaustive guard
                raise LookupError
            success = True
        except LookupError:
            error_code = "unknown_tool"
            value = {"error": {"code": error_code, "message": "unknown experiment file tool"}}
            success = False
        except ValidationError:
            error_code = "invalid_input"
            value = {"error": {"code": error_code, "message": "invalid tool input"}}
            success = False
            validated = None
        except FileAccessError as exc:
            error_code = "file_access_error"
            value = {"error": {"code": error_code, "message": str(exc)}}
            success = False
            validated = None

        result, digest, size = self._serialize(value)
        fields = validated.model_dump() if success and validated is not None else {}
        return result, FileToolCall(
            phase=phase,
            tool_use_id=tool_use_id,
            operation=operation,
            success=success,
            path=fields.get("path"),
            pattern=fields.get("pattern"),
            query=fields.get("query"),
            start_line=fields.get("start_line"),
            end_line=fields.get("end_line"),
            max_results=fields.get("max_results"),
            result_sha256=digest,
            result_bytes=size,
            error_code=error_code,
        )
