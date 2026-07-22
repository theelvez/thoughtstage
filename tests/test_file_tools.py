from __future__ import annotations

import json
from pathlib import Path

from thoughtstage.file_tools import ExperimentFileTools
from thoughtstage.files import ExperimentFileReader


def _tools(root: Path) -> ExperimentFileTools:
    return ExperimentFileTools(ExperimentFileReader(root))


def test_read_text_returns_content_but_audit_records_only_metadata(tmp_path: Path) -> None:
    (tmp_path / "submission.py").write_text("def answer():\n    return 42\n", encoding="utf-8")

    result, audit = _tools(tmp_path).execute(
        name="read_text",
        tool_use_id="read-1",
        phase="private",
        raw_input={"path": "submission.py", "start_line": 1, "end_line": 2},
    )

    assert json.loads(result)["text"] == "def answer():\n    return 42"
    assert audit.success is True
    assert audit.path == "submission.py"
    assert audit.start_line == 1
    assert audit.end_line == 2
    assert "return 42" not in audit.model_dump_json()
    assert str(tmp_path) not in audit.model_dump_json()


def test_traversal_and_absolute_paths_return_safe_errors(tmp_path: Path) -> None:
    (tmp_path / "inside.txt").write_text("inside", encoding="utf-8")

    for requested in ("../outside.txt", "C:/outside.txt", "/outside.txt"):
        result, audit = _tools(tmp_path).execute(
            name="read_text",
            tool_use_id="read-bad",
            phase="public",
            raw_input={"path": requested},
        )

        assert json.loads(result)["error"]["code"] == "file_access_error"
        assert audit.success is False
        assert audit.path is None
        assert requested not in audit.model_dump_json()


def test_unknown_tool_and_invalid_input_do_not_escape_validation(tmp_path: Path) -> None:
    unknown_result, unknown_audit = _tools(tmp_path).execute(
        name="delete_file",
        tool_use_id="unknown-1",
        phase="private",
        raw_input={"path": "anything"},
    )
    invalid_result, invalid_audit = _tools(tmp_path).execute(
        name="read_text",
        tool_use_id="invalid-1",
        phase="private",
        raw_input={"path": "file.txt", "unexpected": True},
    )

    assert json.loads(unknown_result)["error"]["code"] == "unknown_tool"
    assert unknown_audit.operation == "unknown"
    assert json.loads(invalid_result)["error"]["code"] == "invalid_input"
    assert invalid_audit.operation == "read_text"
    assert invalid_audit.path is None

    wildcard_result, wildcard_audit = _tools(tmp_path).execute(
        name="search_text",
        tool_use_id="tool-wildcard",
        phase="private",
        raw_input={"query": "evidence", "path": "*"},
    )
    assert json.loads(wildcard_result) == {
        "error": {
            "code": "file_access_error",
            "message": "path does not exist inside the experiment root",
        }
    }
    assert wildcard_audit.success is False
    assert wildcard_audit.error_code == "file_access_error"
    assert wildcard_audit.path is None
