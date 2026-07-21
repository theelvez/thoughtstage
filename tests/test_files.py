from __future__ import annotations

from pathlib import Path

import pytest

from thoughtstage.files import ExperimentFileReader, FileAccessError


def test_lists_reads_hashes_and_searches(tmp_path: Path) -> None:
    (tmp_path / "notes").mkdir()
    target = tmp_path / "notes" / "brief.txt"
    target.write_text("First line\nEvidence changes minds\nThird line\n", encoding="utf-8")
    audit: list[tuple[str, dict]] = []
    reader = ExperimentFileReader(
        tmp_path, audit=lambda operation, details: audit.append((operation, details))
    )

    assert reader.list_files("*.txt") == [{"path": "notes/brief.txt", "size": 48}]
    assert reader.file_info("notes/brief.txt")["sha256"]
    assert reader.read_text("notes/brief.txt", 2, 2)["text"] == "Evidence changes minds"
    assert reader.search_text("evidence")[0]["line"] == 2
    assert reader.search_text("third", "notes/brief.txt", 1)[0]["line"] == 3
    assert {operation for operation, _details in audit} == {
        "list_files",
        "file_info",
        "read_text",
        "search_text",
    }


@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", "C:\\Windows\\win.ini"])
def test_rejects_path_escape(tmp_path: Path, path: str) -> None:
    reader = ExperimentFileReader(tmp_path)

    with pytest.raises(FileAccessError):
        reader.read_text(path)


def test_enforces_line_and_size_limits(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    reader = ExperimentFileReader(tmp_path, max_file_bytes=8, max_read_lines=1)

    with pytest.raises(FileAccessError, match="byte"):
        reader.read_text("large.txt")

    reader = ExperimentFileReader(tmp_path, max_file_bytes=100, max_read_lines=1)
    with pytest.raises(FileAccessError, match="at most 1"):
        reader.read_text("large.txt", 1, 2)


def test_rejects_invalid_ranges_and_missing_paths(tmp_path: Path) -> None:
    (tmp_path / "brief.txt").write_text("one\ntwo\n", encoding="utf-8")
    reader = ExperimentFileReader(tmp_path)

    with pytest.raises(FileAccessError, match="start_line"):
        reader.read_text("brief.txt", 0)
    with pytest.raises(FileAccessError, match="end_line"):
        reader.read_text("brief.txt", 2, 1)
    with pytest.raises(FileAccessError, match="does not exist"):
        reader.read_text("missing.txt")
    with pytest.raises(FileAccessError, match="not a file"):
        reader.file_info(".")


def test_rejects_binary_text_and_invalid_search(tmp_path: Path) -> None:
    (tmp_path / "binary.bin").write_bytes(b"\xff\xfe\x00")
    reader = ExperimentFileReader(tmp_path)

    with pytest.raises(FileAccessError, match="UTF-8"):
        reader.read_text("binary.bin")
    with pytest.raises(FileAccessError, match="empty"):
        reader.search_text("")
    with pytest.raises(FileAccessError, match="between 1 and 100"):
        reader.search_text("x", max_results=101)
    assert reader.search_text("not present") == []


def test_rejects_symlink_when_supported(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available")

    with pytest.raises(FileAccessError, match="symlink"):
        ExperimentFileReader(tmp_path).read_text("link.txt")
