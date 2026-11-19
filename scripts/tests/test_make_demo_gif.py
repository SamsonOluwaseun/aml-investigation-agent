"""Unit tests for make_demo_gif pure helpers.

Tests port selection, browser path discovery with candidate lists,
database copying, argument parsing, and animated GIF assembly using Pillow.
These tests do not launch a browser or Streamlit.

Owner: Antigravity · Build plan: item 11 · Issue: #12
"""

from pathlib import Path
import sys

from PIL import Image
import pytest

from scripts.make_demo_gif import (
    assemble_gif,
    copy_db_to_temp,
    find_browser_path,
    get_free_port,
    parse_args,
)


def test_get_free_port() -> None:
    """Verify that get_free_port returns a valid, bindable local port number."""
    port1 = get_free_port()
    port2 = get_free_port()

    assert isinstance(port1, int)
    assert isinstance(port2, int)
    assert 1024 < port1 <= 65535
    assert 1024 < port2 <= 65535


def test_find_browser_path_override_found(tmp_path: Path) -> None:
    """Verify that an existing explicit browser path override is returned."""
    mock_browser = tmp_path / "mock_chrome.exe"
    mock_browser.write_text("mock executable content", encoding="utf-8")

    resolved = find_browser_path(override=str(mock_browser))
    assert resolved == str(mock_browser.resolve())


def test_find_browser_path_override_missing(tmp_path: Path) -> None:
    """Verify that a missing browser path override raises FileNotFoundError."""
    missing = tmp_path / "nonexistent_browser.exe"

    with pytest.raises(FileNotFoundError, match="Specified browser executable not found"):
        find_browser_path(override=str(missing))


def test_find_browser_path_candidate_list(tmp_path: Path) -> None:
    """Verify candidate search selects the first existing browser executable."""
    missing1 = tmp_path / "edge_missing.exe"
    mock_edge = tmp_path / "msedge.exe"
    mock_edge.write_text("mock edge executable", encoding="utf-8")
    missing2 = tmp_path / "chrome_missing.exe"

    candidates = [str(missing1), str(mock_edge), str(missing2)]
    resolved = find_browser_path(override=None, candidate_paths=candidates)

    assert resolved == str(mock_edge.resolve())


def test_find_browser_path_candidate_list_none_found(tmp_path: Path) -> None:
    """Verify that FileNotFoundError is raised if no candidates exist."""
    missing1 = tmp_path / "missing_edge.exe"
    missing2 = tmp_path / "missing_chrome.exe"

    candidates = [str(missing1), str(missing2)]
    with pytest.raises(FileNotFoundError, match="No Chromium browser"):
        find_browser_path(override=None, candidate_paths=candidates)


def test_copy_db_to_temp(tmp_path: Path) -> None:
    """Verify that the source database is copied to a temporary bank.db destination."""
    source_db = tmp_path / "original_bank.db"
    source_db.write_bytes(b"SQLite format 3\x00synthetic data")

    temp_dir = tmp_path / "isolated_env"
    copied = copy_db_to_temp(source_db, temp_dir)

    assert copied.is_file()
    assert copied.name == "bank.db"
    assert copied.read_bytes() == b"SQLite format 3\x00synthetic data"
    assert copied.parent == temp_dir.resolve()
    # Ensure source was not altered or deleted
    assert source_db.is_file()


def test_assemble_gif(tmp_path: Path) -> None:
    """Verify assembly of an animated GIF from two generated Pillow images."""
    img1 = Image.new("RGB", (1200, 800), color=(40, 80, 160))
    img2 = Image.new("RGB", (1200, 800), color=(180, 40, 60))

    out_gif = tmp_path / "test_demo.gif"
    saved_path = assemble_gif([img1, img2], out_gif, target_width=1000, duration_ms=2500)

    assert saved_path == out_gif.resolve()
    assert saved_path.is_file()
    assert saved_path.stat().st_size > 0

    # Inspect generated GIF metadata and structure
    with Image.open(saved_path) as gif:
        assert getattr(gif, "is_animated", False)
        assert gif.n_frames == 2
        assert gif.size[0] == 1000
        # Height scaled proportionally: 800 * (1000 / 1200) = 667
        assert gif.size[1] == int(round(800 * (1000 / 1200)))
        assert gif.info.get("loop") == 0


def test_assemble_gif_empty_list(tmp_path: Path) -> None:
    """Verify that assembling with no images raises ValueError."""
    with pytest.raises(ValueError, match="At least one image is required"):
        assemble_gif([], tmp_path / "empty.gif")


def test_parse_args_defaults() -> None:
    """Verify default CLI argument values."""
    args = parse_args([])
    assert args.db == "bank/bank.db"
    assert args.cases == "docs/samples/cases"
    assert args.usage == "docs/samples/usage.sample.jsonl"
    assert args.out == "docs/demo/demo.gif"
    assert args.browser is None


def test_parse_args_custom() -> None:
    """Verify parsing of custom CLI flags."""
    custom = [
        "--db", "custom/test.db",
        "--cases", "custom/cases",
        "--usage", "custom/usage.jsonl",
        "--out", "output/preview.gif",
        "--browser", "C:\\Custom\\browser.exe",
    ]
    args = parse_args(custom)
    assert args.db == "custom/test.db"
    assert args.cases == "custom/cases"
    assert args.usage == "custom/usage.jsonl"
    assert args.out == "output/preview.gif"
    assert args.browser == "C:\\Custom\\browser.exe"
