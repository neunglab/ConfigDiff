import warnings

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QNativeGestureEvent, QPointingDevice
from PySide6.QtWidgets import QApplication

from configdiff.core import Source
from configdiff.gui import MainWindow


def test_regex_scope_and_hide_sections(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    window.sources = [
        Source("A.cfg", "", "hostname R1\n ip address 10.0.0.1\n"),
        Source("B.cfg", "", "hostname R2\n ip address 10.0.0.2\n"),
    ]
    window.refresh()
    window.search.setText(r"10\.0\.0\.[12]")
    window.search_regex.setChecked(True)
    window.find_next()
    assert len(window.search_matches) == 2
    assert window.search_result.text() == "1 / 2"
    window.find_previous()
    assert window.search_result.text() == "2 / 2"

    window.search_scope.setCurrentIndex(1)
    window.find_next()
    assert len(window.search_matches) == 1
    assert window.search_matches[0][0] == 0
    window.search_scope.setCurrentIndex(2)
    window.find_next()
    assert len(window.search_matches) == 1
    assert window.search_matches[0][0] == 1

    window.search.setText("[")
    window.find_next()
    assert window.search_result.text() == "Invalid regex"
    window.search_regex.setChecked(False)
    window.search.setText("10.0.0.2")
    window.find_next()
    assert window.search_result.text() == "1 / 1"

    window.toggle_c()
    window.sources[2] = Source("C.cfg", "", "hostname R3\n ip address 10.0.0.3\n")
    window.refresh()
    window.search_scope.setCurrentIndex(4)  # C only
    window.search.setText("10.0.0.3")
    window.find_next()
    assert window.search_matches[0][0] == 2
    window.focus_ab.click()
    app.processEvents()
    assert not window.panes[2].isVisible()
    assert window.sources[2].name == "C.cfg"
    assert window.search_scope.count() == 3
    window.focus_ab.click()
    app.processEvents()
    assert window.panes[2].isVisible()
    assert window.sources[2].name == "C.cfg"

    old_width = window.main_split.sizes()[0]
    assert old_width == 0
    window.sections_btn.click()
    app.processEvents()
    assert window.blocks.isVisible()
    assert window.main_split.sizes()[0] >= 130
    window.sections_btn.click()
    app.processEvents()
    assert not window.blocks.isVisible()
    assert window.main_split.sizes()[0] == 0
    window.close()


def test_native_pinch_zoom_changes_both_panes_without_text_changes(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    text = "interface Gi0/0\n description <Core & DR>\n"
    window.sources = [Source("A.cfg", "", text), Source("B.cfg", "", text)]
    window.refresh()
    position = QPointF(20, 20)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        zoom_in = QNativeGestureEvent(Qt.ZoomNativeGesture, QPointingDevice.primaryPointingDevice(),
                                      position, position, position, 0.1, 1, 0)
    QApplication.sendEvent(window.panes[0].viewer.viewport(), zoom_in)
    assert window.font_size == 15.4
    assert all(pane.viewer.font().pointSizeF() == 15.4 for pane in window.panes[:2])
    assert window.panes[0].viewer.toPlainText() == text.rstrip("\n")
    window.close()
