from pathlib import Path

from thoughtstage.mcp.files import create_server


def test_file_mcp_can_be_constructed(tmp_path: Path) -> None:
    (tmp_path / "brief.txt").write_text("hello", encoding="utf-8")

    server = create_server(tmp_path)

    assert server.name == "Thoughtstage Experiment Files"
