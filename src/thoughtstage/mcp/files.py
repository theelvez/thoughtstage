"""Read-only, experiment-scoped file MCP server."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from thoughtstage.files import ExperimentFileReader

logger = logging.getLogger("thoughtstage.files_mcp")


def create_server(root: str | Path) -> FastMCP:
    def audit(operation: str, details: dict[str, Any]) -> None:
        logger.info("file operation=%s details=%s", operation, details)

    reader = ExperimentFileReader(root, audit=audit)
    server = FastMCP(
        "Thoughtstage Experiment Files",
        instructions=(
            "Read-only access to files explicitly placed in this experiment. "
            "All paths are relative to the experiment file root."
        ),
    )

    @server.tool()
    def list_files(pattern: str = "*") -> list[dict[str, Any]]:
        """List readable files matching a glob-like pattern."""
        return reader.list_files(pattern)

    @server.tool()
    def file_info(path: str) -> dict[str, Any]:
        """Return size and SHA-256 metadata for one experiment file."""
        return reader.file_info(path)

    @server.tool()
    def read_text(path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        """Read a bounded line range from one UTF-8 experiment file."""
        return reader.read_text(path, start_line, end_line)

    @server.tool()
    def search_text(
        query: str, path: str | None = None, max_results: int = 20
    ) -> list[dict[str, Any]]:
        """Case-insensitively search bounded UTF-8 experiment files."""
        return reader.search_text(query, path, max_results)

    return server


def run_server(root: str | Path) -> None:
    logging.basicConfig(level=logging.INFO)
    create_server(root).run(transport="stdio")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "root",
        nargs="?",
        default=os.environ.get("THOUGHTSTAGE_EXPERIMENT_FILES"),
        help="experiment file root (or set THOUGHTSTAGE_EXPERIMENT_FILES)",
    )
    args = parser.parse_args()
    if not args.root:
        parser.error("an experiment file root is required")
    run_server(args.root)


if __name__ == "__main__":
    main()
