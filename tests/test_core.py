from pathlib import Path
import json

from configdiff.core import Source, align, atomic_save, backup_paths, block_summary, encode_source_text, open_project, project_bytes, read_source


def test_three_way_alignment_keeps_base_positions():
    a = Source(text="interface A\n old\n!\ninterface B\n yes\n")
    b = Source(text="interface A\n new\n extra\n!\ninterface B\n yes\n")
    c = Source(text="interface A\n!\ninterface B\n changed\n")
    result = align([a, b, c])
    assert [row[0] for row in result.indexes if row[0] is not None] == list(range(5))
    assert any(row[0] is None and row[1] is not None for row in result.indexes)
    assert any("removed" in row for row in result.kinds)


def test_manual_alignment_pairs_different_lines_without_reordering_or_writing():
    a = Source(text="header\npeer A\n description uplink\nfooter\n")
    b = Source(text="header\nextra\npeer A\n description backup\nfooter\n")
    c = Source(text="header\npeer A\nfooter\n")
    result = align([a, b, c], {1: [(2, 3)]})
    assert (2, 3, None) in result.indexes
    assert [row[0] for row in result.indexes if row[0] is not None] == list(range(4))
    assert [row[1] for row in result.indexes if row[1] is not None] == list(range(5))
    assert a.text == "header\npeer A\n description uplink\nfooter\n"
    assert b.text == "header\nextra\npeer A\n description backup\nfooter\n"


def test_manual_alignment_rejects_crossed_lines():
    import pytest
    a = Source(text="a\nb\nc\n")
    b = Source(text="c\nb\na\n")
    with pytest.raises(ValueError, match="same order"):
        align([a, b], {1: [(0, 2), (2, 0)]})


def test_uneven_hunk_does_not_link_removed_peer_to_changed_logging():
    left = Source(text="header\npeer HUB3\n address 10.1.1.1\nlogging buffered 100\n")
    right = Source(text="header\nlogging buffered 200\n")
    result = align([left, right])
    assert result.indexes[-1] == (3, 1)
    assert result.kinds[-1][1] == "changed"
    assert all(row[1] is None for row in result.indexes[1:3])


def test_uneven_hunk_with_blank_config_lines_does_not_crash():
    left = Source(text="version 15.6\n\n!\npeer HUB3\nlogging buffered 100\n")
    right = Source(text="version 15.6\nlogging buffered 200\n")
    result = align([left, right])
    assert result.indexes[-1] == (4, 1)
    assert result.kinds[-1][1] == "changed"


def test_block_changes_and_duplicate_headers():
    before = "route-map X permit 10\n set local-preference 100\n!\nroute-map X permit 20\n set metric 1\n".splitlines()
    after = "route-map X permit 10\n set local-preference 200\n!\nroute-map X permit 20\n set metric 1\n".splitlines()
    summary = block_summary(before, after)
    assert summary[0][1].endswith("Changed")
    assert summary[1][1].endswith("Same")


def test_atomic_backup_rotation_and_restore_data(tmp_path: Path):
    target = tmp_path / "config.txt"
    for i in range(13):
        atomic_save(str(target), str(i).encode())
    assert target.read_text() == "12"
    assert len(backup_paths(str(target))) == 10
    assert backup_paths(str(target))[0].read_text() == "11"


def test_project_roundtrip(tmp_path: Path):
    items = [Source("A.cfg", "/tmp/A.cfg", "hostname A\n", encoding="UTF-8"),
             Source("B.cfg", "/tmp/B.cfg", "hostname B\n", encoding="Latin-1 fallback")]
    target = tmp_path / "test.cdiff"
    atomic_save(str(target), project_bytes(items, 17, "Monaco"))
    result, font_size, font_family = open_project(str(target))
    assert result == items
    assert font_size == 17
    assert font_family == "Monaco"

    previous = json.loads(target.read_text())
    previous.pop("font_family")
    for source in previous["sources"]:
        source.pop("encoding")
    target.write_text(json.dumps(previous))
    old_sources, _, old_font = open_project(str(target))
    assert old_font == "Menlo"
    assert all(source.encoding == "Unknown" for source in old_sources)


def test_file_encoding_labels_match_decoding(tmp_path: Path):
    utf8 = tmp_path / "bom.cfg"
    utf8.write_bytes(b"\xef\xbb\xbfhostname R1\n")
    latin1 = tmp_path / "latin1.cfg"
    latin1.write_bytes(b"description caf\xe9\n")
    assert (read_source(str(utf8)).text, read_source(str(utf8)).encoding) == ("hostname R1\n", "UTF-8 BOM")
    assert (read_source(str(latin1)).text, read_source(str(latin1)).encoding) == ("description café\n", "Latin-1 fallback")
    assert encode_source_text("hostname R2\n", "UTF-8 BOM").startswith(b"\xef\xbb\xbf")
    assert encode_source_text("description café\n", "Latin-1 fallback") == b"description caf\xe9\n"
