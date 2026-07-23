"""Safe, read-only access to experiment-scoped files."""

from __future__ import annotations

import fnmatch
import hashlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any


class FileAccessError(ValueError):
    """Raised when a requested file violates the experiment file policy."""


AuditHook = Callable[[str, dict[str, Any]], None]


class ExperimentFileReader:
    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int = 1_000_000,
        max_read_lines: int = 500,
        audit: AuditHook | None = None,
    ) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise FileAccessError("experiment file root must be a directory")
        self.max_file_bytes = max_file_bytes
        self.max_read_lines = max_read_lines
        self.audit = audit or (lambda _operation, _details: None)

    def _relative_name(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def _resolve(self, user_path: str, *, require_file: bool | None = None) -> Path:
        normalized = user_path.replace("\\", "/")
        logical = PurePosixPath(normalized)
        if logical.is_absolute() or ".." in logical.parts or ":" in normalized:
            raise FileAccessError("path must be relative and may not contain traversal")
        candidate = self.root.joinpath(*logical.parts)

        current = self.root
        for part in logical.parts:
            current = current / part
            if current.is_symlink():
                raise FileAccessError("symlinks are not permitted in experiment files")

        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.root)
        except (OSError, ValueError) as exc:
            raise FileAccessError("path does not exist inside the experiment root") from exc

        if require_file is True and not resolved.is_file():
            raise FileAccessError("path is not a file")
        if require_file is False and not resolved.is_dir():
            raise FileAccessError("path is not a directory")
        return resolved

    def _bounded_text(self, path: Path) -> str:
        size = path.stat().st_size
        if size > self.max_file_bytes:
            raise FileAccessError(f"file exceeds the {self.max_file_bytes}-byte experiment limit")
        try:
            return path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise FileAccessError("file is not valid UTF-8 text") from exc

    def _discovered_files(self, root: Path) -> list[Path]:
        """Return only files that pass the same path policy as direct reads."""

        files: list[Path] = []
        for path in sorted(root.rglob("*")):
            try:
                relative = path.relative_to(self.root).as_posix()
                files.append(self._resolve(relative, require_file=True))
            except (FileAccessError, ValueError):
                continue
        return files

    def list_files(self, pattern: str = "*") -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for path in self._discovered_files(self.root):
            relative = self._relative_name(path)
            if fnmatch.fnmatch(relative, pattern) or fnmatch.fnmatch(path.name, pattern):
                results.append({"path": relative, "size": path.stat().st_size})
        self.audit("list_files", {"pattern": pattern, "result_count": len(results)})
        return results

    def file_info(self, path: str) -> dict[str, Any]:
        resolved = self._resolve(path, require_file=True)
        size = resolved.stat().st_size
        if size > self.max_file_bytes:
            raise FileAccessError(f"file exceeds the {self.max_file_bytes}-byte experiment limit")
        digest = hashlib.sha256()
        with resolved.open("rb") as stream:
            for chunk in iter(lambda: stream.read(64 * 1024), b""):
                digest.update(chunk)
        result = {
            "path": self._relative_name(resolved),
            "size": size,
            "sha256": digest.hexdigest(),
        }
        self.audit("file_info", {"path": result["path"]})
        return result

    def read_text(
        self,
        path: str,
        start_line: int = 1,
        end_line: int | None = None,
    ) -> dict[str, Any]:
        if start_line < 1:
            raise FileAccessError("start_line must be at least 1")
        resolved = self._resolve(path, require_file=True)
        lines = self._bounded_text(resolved).splitlines()
        final_line = len(lines) if end_line is None else end_line
        if final_line < start_line:
            raise FileAccessError("end_line must be greater than or equal to start_line")
        if final_line - start_line + 1 > self.max_read_lines:
            raise FileAccessError(f"a read may return at most {self.max_read_lines} lines")
        selected = lines[start_line - 1 : final_line]
        result = {
            "path": self._relative_name(resolved),
            "start_line": start_line,
            "end_line": start_line + len(selected) - 1,
            "text": "\n".join(selected),
        }
        self.audit(
            "read_text",
            {"path": result["path"], "start_line": start_line, "end_line": final_line},
        )
        return result

    def search_text(
        self,
        query: str,
        path: str | None = None,
        max_results: int = 20,
    ) -> list[dict[str, Any]]:
        if not query:
            raise FileAccessError("query may not be empty")
        if not 1 <= max_results <= 100:
            raise FileAccessError("max_results must be between 1 and 100")

        candidates = [self.root] if path is None else [self._resolve(path)]

        files: list[Path] = []
        for candidate in candidates:
            if candidate.is_file():
                files.append(candidate)
            else:
                files.extend(self._discovered_files(candidate))

        results: list[dict[str, Any]] = []
        folded_query = query.casefold()
        for candidate in files:
            try:
                lines = self._bounded_text(candidate).splitlines()
            except FileAccessError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if folded_query in line.casefold():
                    results.append(
                        {
                            "path": self._relative_name(candidate),
                            "line": line_number,
                            "text": line[:500],
                        }
                    )
                    if len(results) >= max_results:
                        self.audit(
                            "search_text",
                            {"query": query, "path": path, "result_count": len(results)},
                        )
                        return results
        self.audit("search_text", {"query": query, "path": path, "result_count": len(results)})
        return results
