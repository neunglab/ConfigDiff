from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import QFileDialog
from PySide6.QtTest import QTest

from configdiff.core import Source
from configdiff.gui import MainWindow


def test_native_copy_has_no_line_numbers_and_zoom_keeps_position(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    text = "\n".join(f"interface Gi{i}\n description A{i}" for i in range(150))
    window.sources = [Source("A.cfg", "", text), Source("B.cfg", "", text.replace("A120", "B120"))]
    window.refresh()
    editor = window.panes[0].viewer
    assert editor.toPlainText().startswith("interface Gi0")
    assert editor.line_map[0] == 0

    selection = editor.textCursor()
    selection.movePosition(QTextCursor.Start)
    selection.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
    editor.setTextCursor(selection)
    editor.copy()  # Same path as the native Copy action / Cmd+C.
    assert app.clipboard().text() == "interface Gi0"

    editor.verticalScrollBar().setValue(120)
    before = editor.firstVisibleBlock().blockNumber()
    window.zoom(1)
    assert window.font_size == 14.5
    assert abs(editor.firstVisibleBlock().blockNumber() - before) <= 1
    window.close()


def test_scroll_sync_coalesces_updates_and_follows_horizontal(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    long_line = " description " + "X" * 400
    text = "\n".join(f"interface Gi{i}\n{long_line}" for i in range(300))
    window.sources = [Source("A.cfg", "", text), Source("B.cfg", "", text.replace("Gi150", "Gi151"))]
    window.refresh()
    left, right = (pane.viewer for pane in window.panes[:2])
    updates = []
    right.verticalScrollBar().valueChanged.connect(updates.append)
    for row in range(10, 100, 5):
        left.verticalScrollBar().setValue(row)
    assert right.verticalScrollBar().value() != 95
    QTest.qWait(30)
    assert right.verticalScrollBar().value() == 95
    assert len(updates) == 1

    left.horizontalScrollBar().setValue(80)
    QTest.qWait(30)
    assert right.horizontalScrollBar().value() == 80
    assert window.map.current == 95
    window.close()


def test_independent_pane_resizing_and_plain_text(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1200, 800)
    window.show()
    app.processEvents()
    window.split.moveSplitter(230, 1)
    assert abs(window.split.sizes()[0] - 230) <= 2

    window.toggle_c()
    app.processEvents()
    window.split.moveSplitter(200, 1)
    left_width = window.split.sizes()[0]
    window.split.moveSplitter(680, 2)
    sizes = window.split.sizes()
    assert abs(sizes[0] - left_width) <= 2
    assert all(size >= 175 for size in sizes)

    raw = "interface Gi0/1\n description <Core & DR>\n password 7 010203\n"
    window.sources = [Source("A.cfg", "", raw), Source("B.cfg", "", raw), Source("C.cfg", "", raw)]
    window.refresh()
    assert "<Core & DR>" in window.panes[0].viewer.toPlainText()
    window.panes[0].viewer.selectAll()
    window.panes[0].viewer.copy()
    assert "<Core & DR>" in app.clipboard().text()
    assert "&lt;" not in app.clipboard().text()
    window.close()


def test_character_highlight_marks_only_added_hostname_suffix(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.sources = [
        Source("A.cfg", "", "version 15.6\nhostname Router-A\nservice password-encryption\n"),
        Source("B.cfg", "", "version 15.6\nhostname Router-A_MODEL2\nservice password-encryption\n"),
    ]
    window.refresh()
    left, right = (pane.viewer for pane in window.panes[:2])
    marked = lambda editor: [selection.cursor.selectedText() for selection in editor.extraSelections()
                             if selection.cursor.hasSelection()]
    assert marked(left) == []
    assert marked(right) == ["_MODEL2"]
    window.close()


def test_read_only_diff_links_follow_changed_rows(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1200, 700)
    window.show()
    left_text = "version 15.6\nhostname Router-A\nservice password-encryption\n"
    right_text = "version 15.6\nhostname Router-A_MODEL2\nservice password-encryption\n"
    window.sources = [Source("A.cfg", "", left_text), Source("B.cfg", "", right_text)]
    window.refresh()
    app.processEvents()
    handle = window.split.handle(1)
    links = handle.visible_links()
    assert len(links) == 1
    start, end, status, top_left, bottom_left, top_right, bottom_right = links[0]
    assert (start, end, status) == (1, 2, "changed")
    assert 0 <= top_left < bottom_left < handle.height()
    assert 0 <= top_right < bottom_right < handle.height()
    handle.repaint()  # Rendering the connector never edits either source.
    assert [source.text for source in window.sources] == [left_text, right_text]
    window.close()


def test_block_link_scales_with_zoom_and_line_numbers_can_hide(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.resize(1200, 700)
    window.show()
    a = "header\npeer A\n address 1\n key 123\nfooter\n"
    b = "header\nfooter\n"
    window.sources = [Source("A.cfg", "", a), Source("B.cfg", "", b)]
    window.refresh()
    app.processEvents()
    handle = window.split.handle(1)
    links = handle.visible_links()
    assert len(links) == 1
    assert links[0][2] == "removed"
    original_height = links[0][4] - links[0][3]
    assert original_height > window.panes[0].viewer.fontMetrics().height() * 2

    window.numbers_btn.click()
    assert all(pane.viewer.gutter_width() == 0 and not pane.viewer.gutter.isVisible()
               for pane in window.panes[:2])
    assert window.panes[0].viewer.toPlainText().splitlines()[1] == "peer A"
    window.zoom(4)
    app.processEvents()
    zoomed = handle.visible_links()
    assert zoomed[0][4] - zoomed[0][3] > original_height
    window.numbers_btn.click()
    assert all(pane.viewer.gutter_width() > 0 and pane.viewer.gutter.isVisible()
               for pane in window.panes[:2])
    window.close()


def test_status_encoding_and_installed_font_selection(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.sources = [Source("A.cfg", "", "hostname R1", encoding="UTF-8 BOM"),
                      Source("B.cfg", "", "hostname R2", encoding="Latin-1 fallback")]
    window.refresh()
    assert window.text_mode.text() == "Plain Text"
    assert window.encoding_status.text() == "A: UTF-8 BOM  ·  B: Latin-1 fallback"
    installed = window.font_choice.itemText(0)
    window.font_choice.setCurrentFont(QFont(installed))
    assert window.panes[0].viewer.font().family() == window.font_family
    assert window.panes[1].viewer.font().family() == window.font_family
    old_size = window.font_size
    window.zoom(1)
    assert window.font_size == old_size + .5
    window.close()


def test_loading_files_with_blank_lines_and_uneven_diff(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    left = tmp_path / "A.cfg"
    right = tmp_path / "B.cfg"
    left.write_text("version 15.6\n\n!\npeer HUB3\nlogging buffered 100\n")
    right.write_text("version 15.6\nlogging buffered 200\n")
    window = MainWindow()
    window.error = lambda exc: (_ for _ in ()).throw(exc)
    window.load_file(0, str(left))
    window.load_file(1, str(right))
    assert window.panes[0].viewer.toPlainText().startswith("version 15.6")
    assert "logging buffered 200" in window.panes[1].viewer.toPlainText()
    assert left.read_text().startswith("version 15.6\n\n")
    window.close()


def test_closing_window_stops_pending_scroll(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.pending_scroll["vertical"] = (0, 5)
    window.scroll_timer.start()
    window.close()
    assert not window.scroll_timer.isActive()
    assert not window.pending_scroll
    assert not window.isVisible()


def test_shared_browse_folder_for_left_and_right_with_empty_default(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    directories = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda parent, title, directory, filters: (
        directories.append(directory) or "", ""))
    window.browse_folder.setText(str(tmp_path))
    window.browse(0)
    window.browse_folder.setText(f"'{tmp_path}'")
    window.browse(1)
    window.browse_folder.setText(f'"{tmp_path}"')
    window.browse(0)
    window.browse_folder.clear()
    window.browse(1)
    assert directories == [str(tmp_path.resolve())] * 3 + [""]
    window.close()


def test_optional_backspace_ignoring_keeps_original_config(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.sources = [Source("A.cfg", "", "hostname R1\n!\n"),
                      Source("B.cfg", "", "hostname R1\n!\b\n")]
    window.refresh()
    assert window.ignore_backspace.isChecked()
    assert window.panes[1].viewer.toPlainText() == "hostname R1\n!"
    assert window.diff_text() == ""
    assert window.map.kinds == [("same", "same"), ("same", "same")]
    assert window.sources[1].text == "hostname R1\n!\b\n"

    window.ignore_backspace.setChecked(False)
    assert window.diff_text() != ""
    assert window.map.kinds[-1][1] == "changed"
    window.close()


def test_comparison_tabs_and_collapsible_top_controls(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    assert window.tabs.count() == 1
    assert not window.controls.isVisible()
    assert window.path_widget.isVisible()
    window.show_folder_action.setChecked(False)
    assert not window.path_widget.isVisible()
    window.show_folder_action.setChecked(True)
    window.show_controls_action.setChecked(True)
    assert window.controls.isVisible()
    window.show_controls_action.setChecked(False)
    assert not window.controls.isVisible()

    window.sources = [Source("Old.cfg", "", "hostname Old\n"), Source("New.cfg", "", "hostname New\n")]
    window.refresh()
    window.new_comparison()
    assert window.tabs.count() == 2
    assert [source.text for source in window.sources] == ["", ""]
    assert all(not pane.viewer.extraSelections() for pane in window.panes[:2])
    window.sources = [Source("A2.cfg", "", "hostname A2\n"), Source("B2.cfg", "", "hostname B2\n")]
    window.refresh()
    window.tabs.setCurrentIndex(0)
    assert [source.name for source in window.sources] == ["Old.cfg", "New.cfg"]
    window.tabs.setCurrentIndex(1)
    assert [source.name for source in window.sources] == ["A2.cfg", "B2.cfg"]
    window.close()


def test_history_restores_tabs_from_paths_and_clear_resets(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    a = tmp_path / "A.cfg"
    b = tmp_path / "B.cfg"
    c = tmp_path / "C.cfg"
    a.write_text("hostname Old\n")
    b.write_text("hostname New\n")
    c.write_text("hostname Third\n")
    window = MainWindow()
    window.load_file(0, str(a))
    window.load_file(1, str(b))
    window.new_comparison()
    window.load_file(0, str(c))
    window.browse_folder.setText(str(tmp_path))
    window.close()

    history = tmp_path / "history.json"
    saved = history.read_text()
    assert str(a) in saved and str(c) in saved
    assert "hostname Old" not in saved
    a.write_text("hostname Updated\n")
    restored = MainWindow()
    assert restored.tabs.count() == 2
    assert restored.tabs.currentIndex() == 1
    assert restored.sources[0].text == "hostname Third\n"
    restored.tabs.setCurrentIndex(0)
    assert restored.sources[0].text == "hostname Updated\n"
    assert restored.browse_folder.text() == str(tmp_path)
    restored.ask = lambda title, message: True
    restored.clear_history()
    assert restored.tabs.count() == 1
    assert all(not source.text for source in restored.sources)
    assert not history.exists()
    restored.close()
    assert not history.exists()


def test_visual_alignment_is_per_tab_and_never_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    a, b = tmp_path / "A.cfg", tmp_path / "B.cfg"
    a.write_text("header\npeer A\n description uplink\nfooter\n")
    b.write_text("header\nextra\npeer A\n description backup\nfooter\n")
    window = MainWindow()
    window.load_file(0, str(a))
    window.load_file(1, str(b))
    for side, source_line in ((0, 2), (1, 3)):
        pane = window.panes[side]
        display_row = pane.line_map.index(source_line)
        pane.viewer.setTextCursor(QTextCursor(pane.viewer.document().findBlockByNumber(display_row)))
        window.mark_alignment_line(side)
    assert window.manual_anchors[1] == [(2, 3)]
    assert (2, 3) in window.alignment.indexes
    assert "manual_anchors" not in window.serialize_session(window.capture_session())
    before = window.diff_text()
    window.new_comparison()
    assert not window.manual_anchors
    window.tabs.setCurrentIndex(0)
    assert window.manual_anchors[1] == [(2, 3)]
    assert window.diff_text() == before
    window.reset_alignment()
    assert not window.manual_anchors
    window.close()
    assert "manual_anchors" not in (tmp_path / "history.json").read_text()
    assert a.read_text() == "header\npeer A\n description uplink\nfooter\n"
    assert b.read_text() == "header\nextra\npeer A\n description backup\nfooter\n"


def test_menu_bar_groups_commands(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert [item.text() for item in window.menuBar().actions()] == ["File", "Compare", "View", "Search"]
    window.close()
