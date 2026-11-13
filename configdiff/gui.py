from __future__ import annotations

from pathlib import Path
from difflib import unified_diff, SequenceMatcher
import json
import os

from PySide6.QtCore import QEvent, QRegularExpression, Qt, Signal, QRect, QSize, QTimer, QPoint, QStandardPaths
from PySide6.QtGui import QAction, QColor, QFont, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFontDialog,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QMainWindow, QMenu, QMessageBox,
    QPlainTextEdit, QPushButton, QSizePolicy, QSplitter, QToolButton, QVBoxLayout, QFontComboBox,
    QWidget, QTextEdit, QListWidgetItem, QSplitterHandle, QTabBar)

from .core import Source, align, atomic_save, backup_paths, block_summary, digest, encode_source_text, open_project, parse_blocks, platform, project_bytes, read_source


PALETTE = {"added": "#d8f1df", "removed": "#f8dddd", "changed": "#fff0b8", "same": "#ffffff", "gap": "#f0f2f5"}


def history_path() -> Path:
    override = os.environ.get("CONFIGDIFF_HISTORY_PATH")
    return Path(override) if override else Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation)) / "history.json"


class FileDropEdit(QPlainTextEdit):
    dropped = Signal(str)
    zoomRequested = Signal(int)
    zoomScaleRequested = Signal(float)

    def __init__(self):
        super().__init__()
        self.line_map: list[int | None] = []
        self.line_numbers_visible = True
        self.dark_gutter = False
        self._wheel_delta = 0
        self.gutter = LineNumberArea(self)
        self.viewport().installEventFilter(self)
        self.blockCountChanged.connect(self.update_gutter_width)
        self.updateRequest.connect(self.update_gutter)
        self.update_gutter_width()

    def gutter_width(self):
        if not self.line_numbers_visible:
            return 0
        highest = max((number for number in self.line_map if number is not None), default=0) + 1
        digits = max(3, len(str(highest)))
        return 16 + self.fontMetrics().horizontalAdvance("9") * digits

    def set_line_map(self, line_map: list[int | None]):
        self.line_map = line_map
        self.update_gutter_width()
        self.gutter.update()

    def set_line_numbers_visible(self, visible: bool):
        self.line_numbers_visible = visible
        self.gutter.setVisible(visible)
        self.update_gutter_width()

    def update_gutter_width(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)
        self.gutter.setGeometry(QRect(0, 0, self.gutter_width(), self.height()))

    def update_gutter(self, rect, dy):
        if dy: self.gutter.scroll(0, dy)
        else: self.gutter.update(0, rect.y(), self.gutter.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.gutter.setGeometry(QRect(0, 0, self.gutter_width(), self.height()))

    def paint_gutter(self, event):
        painter = QPainter(self.gutter)
        painter.fillRect(event.rect(), QColor("#303846" if self.dark_gutter else "#f2f5f8"))
        painter.setFont(self.font())
        painter.setPen(QColor("#b5bfcb" if self.dark_gutter else "#657381"))
        block = self.firstVisibleBlock()
        row = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                number = self.line_map[row] if row < len(self.line_map) else None
                if number is not None:
                    painter.drawText(0, top, self.gutter.width()-8, height, Qt.AlignRight | Qt.AlignVCenter, str(number+1))
            block = block.next()
            row += 1
            if block.isValid():
                top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())

    def wheelEvent(self, event):
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            self._wheel_delta += event.angleDelta().y() or event.pixelDelta().y()
            while abs(self._wheel_delta) >= 120:
                step = 1 if self._wheel_delta > 0 else -1
                self.zoomRequested.emit(step)
                self._wheel_delta -= 120 * step
            event.accept()
        else:
            self._wheel_delta = 0
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.modifiers() & (Qt.ControlModifier | Qt.MetaModifier):
            if event.key() in (Qt.Key_Plus, Qt.Key_Equal):
                self.zoomRequested.emit(1); event.accept(); return
            if event.key() == Qt.Key_Minus:
                self.zoomRequested.emit(-1); event.accept(); return
        super().keyPressEvent(event)

    def _gesture_zoom(self, event) -> bool:
        if event.type() == QEvent.NativeGesture and event.gestureType() == Qt.ZoomNativeGesture:
            self.zoomScaleRequested.emit(max(0.5, min(1.5, 1.0 + event.value())))
            event.accept()
            return True
        if event.type() == QEvent.Gesture:
            pinch = event.gesture(Qt.PinchGesture)
            if pinch is not None:
                if pinch.state() == Qt.GestureUpdated and pinch.lastScaleFactor() > 0:
                    self.zoomScaleRequested.emit(pinch.scaleFactor() / pinch.lastScaleFactor())
                event.accept(pinch)
                return True
        return False

    def viewportEvent(self, event):
        if self._gesture_zoom(event): return True
        return super().viewportEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.viewport() and self._gesture_zoom(event): return True
        return super().eventFilter(watched, event)

    def event(self, event):
        if self._gesture_zoom(event): return True
        return super().event(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
        else: event.ignore()

    def dropEvent(self, event):
        files = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if files:
            self.dropped.emit(files[0])
            event.acceptProposedAction()


class LineNumberArea(QWidget):
    def __init__(self, editor: FileDropEdit):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


class DropPane(QWidget):
    dropped = Signal(str)

    def __init__(self, letter: str):
        super().__init__()
        self.letter = letter
        self.setAcceptDrops(True)
        self.setMinimumWidth(175)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.title = QLabel(f"{letter}  ·  Drop config here")
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.browse = QPushButton("Browse")
        self.copy = QAction("Copy original", self)
        self.copy_block = QAction("Copy block", self)
        self.edit = QAction("Edit Source", self)
        menu = QMenu(self)
        menu.addActions((self.copy, self.copy_block, self.edit))
        self.actions = QToolButton()
        self.actions.setText("Actions ▾")
        self.actions.setMenu(menu)
        self.actions.setPopupMode(QToolButton.InstantPopup)
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(self.browse)
        controls.addWidget(self.actions)
        controls.addStretch(1)
        self.viewer = FileDropEdit()
        self.viewer.dropped.connect(self.dropped)
        self.viewer.setReadOnly(True)
        self.viewer.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.viewer.setMinimumWidth(0)
        self.viewer.setPlaceholderText("Drag a .txt or config file here, or click Browse")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.addWidget(self.title)
        layout.addLayout(controls)
        layout.addWidget(self.viewer)
        self.line_map: list[int | None] = []

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths[0])
            event.acceptProposedAction()

    def selected_original(self, source: Source) -> str:
        cursor = self.viewer.textCursor()
        if not cursor.hasSelection():
            return source.text
        return cursor.selectedText().replace("\u2029", "\n")


class MiniMap(QWidget):
    jumped = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFixedWidth(24)
        self.kinds: list[tuple[str, ...]] = []
        self.current = 0
        self._image: QPixmap | None = None

    def set_kinds(self, kinds: list[tuple[str, ...]]):
        self.kinds = kinds
        self._image = None
        self.update()

    def set_current(self, row: int):
        if row != self.current:
            self.current = row
            self.update()

    def resizeEvent(self, event):
        self._image = None
        super().resizeEvent(event)

    def _build_image(self):
        self._image = QPixmap(self.size())
        self._image.fill(QColor("#e7ebf0"))
        painter = QPainter(self._image)
        total = max(1, len(self.kinds))
        for i, row in enumerate(self.kinds):
            kind = "changed" if "changed" in row else "added" if "added" in row else "removed" if "removed" in row else None
            if kind:
                painter.fillRect(QRect(3, int(i*self.height()/total), 18, max(2, int(self.height()/total))), QColor(PALETTE[kind]).darker(145))
        painter.end()

    def paintEvent(self, event):
        if self._image is None or self._image.size() != self.size():
            self._build_image()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._image)
        total = max(1, len(self.kinds))
        painter.setPen(QColor("#2777b9"))
        y = int(self.current*self.height()/total)
        painter.drawRect(1, y, 21, 5)

    def mousePressEvent(self, event):
        self.jumped.emit(min(len(self.kinds)-1, max(0, int(event.position().y() * len(self.kinds) / max(1, self.height())))))


class DiffHandle(QSplitterHandle):
    """Read-only visual link between A and B; the handle remains resizable."""

    def __init__(self, orientation, splitter):
        super().__init__(orientation, splitter)
        self.setToolTip("Difference links only — copy text with Cmd+C; no file is changed")

    def _row_edges(self, viewer, row):
        block = viewer.document().findBlockByNumber(row)
        if not block.isValid():
            return None
        top = viewer.blockBoundingGeometry(block).translated(viewer.contentOffset()).top()
        upper = viewer.viewport().mapToGlobal(QPoint(0, round(top)))
        lower = viewer.viewport().mapToGlobal(QPoint(0, round(top + viewer.blockBoundingRect(block).height())))
        return self.mapFromGlobal(upper).y(), self.mapFromGlobal(lower).y()

    def visible_links(self):
        splitter = self.splitter()
        owner = splitter.owner
        if self is not splitter.handle(1) or len(owner.map.kinds) == 0:
            return []
        left, right = (pane.viewer for pane in owner.panes[:2])
        first = max(0, min(left.firstVisibleBlock().blockNumber(), right.firstVisibleBlock().blockNumber()) - 1)
        last = min(len(owner.map.kinds), max(
            left.firstVisibleBlock().blockNumber() + left.viewport().height() // max(1, left.fontMetrics().height()) + 2,
            right.firstVisibleBlock().blockNumber() + right.viewport().height() // max(1, right.fontMetrics().height()) + 2))
        links = []
        row = first
        while row < last:
            status = owner.map.kinds[row][1]
            if status not in ("changed", "added", "removed"):
                row += 1
                continue
            end = row + 1
            while end < last and owner.map.kinds[end][1] == status:
                end += 1
            a_start, a_end = self._row_edges(left, row), self._row_edges(left, end - 1)
            b_start, b_end = self._row_edges(right, row), self._row_edges(right, end - 1)
            if all(value is not None for value in (a_start, a_end, b_start, b_end)):
                top_a, bottom_a = a_start[0], a_end[1]
                top_b, bottom_b = b_start[0], b_end[1]
                if max(bottom_a, bottom_b) >= 0 and min(top_a, top_b) <= self.height():
                    links.append((row, end, status, top_a, bottom_a, top_b, bottom_b))
            row = end
        return links

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#e7ebf0"))
        if self is not self.splitter().handle(1):
            return
        painter.setRenderHint(QPainter.Antialiasing)
        for _, _, status, top_a, bottom_a, top_b, bottom_b in self.visible_links():
            edge = QColor(PALETTE[status]).darker(140)
            fill = QColor(PALETTE[status])
            path = QPainterPath()
            width = self.width()
            path.moveTo(1, top_a)
            path.cubicTo(width * .42, top_a, width * .58, top_b, width - 1, top_b)
            path.lineTo(width - 1, bottom_b)
            path.cubicTo(width * .58, bottom_b, width * .42, bottom_a, 1, bottom_a)
            path.closeSubpath()
            painter.setBrush(fill)
            painter.setPen(QPen(edge, 1))
            painter.drawPath(path)
            center = (max(0, top_b) + min(self.height(), bottom_b)) / 2
            if center < 0 or center > self.height():
                continue
            painter.setPen(Qt.NoPen)
            painter.setBrush(edge)
            arrow = QPainterPath()
            arrow.moveTo(width - 2, center)
            arrow.lineTo(width - 12, center - 5)
            arrow.lineTo(width - 12, center + 5)
            arrow.closeSubpath()
            painter.drawPath(arrow)


class DiffSplitter(QSplitter):
    def __init__(self, owner):
        super().__init__(Qt.Horizontal)
        self.owner = owner

    def createHandle(self):
        return DiffHandle(self.orientation(), self)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ConfigDiff 1.1 — Cisco config comparison")
        self.resize(1450, 860)
        self.sources = [Source(), Source()]
        self.project_path = ""
        self.font_size = 14
        self.font_family = "Menlo"
        self.alignment = None
        self.manual_anchors: dict[int, list[tuple[int, int]]] = {}
        self.pending_anchor: dict[int, int] = {}
        self.syncing = False
        self.pending_scroll: dict[str, tuple[int, int]] = {}
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.setInterval(16)
        self.scroll_timer.timeout.connect(self.flush_scroll)
        self.panes = [DropPane(x) for x in "ABC"]
        self.search_matches: list[tuple[int, QTextCursor]] = []
        self.search_index = -1
        root = QWidget()
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        bar = QHBoxLayout()
        find_bar = QHBoxLayout()
        file_bar = QHBoxLayout()
        path_bar = QHBoxLayout()
        self.add_c = QPushButton("+ C")
        self.add_c.clicked.connect(self.toggle_c)
        self.focus_ab = QPushButton("Focus A+B")
        self.focus_ab.setCheckable(True)
        self.focus_ab.setEnabled(False)
        self.focus_ab.toggled.connect(self.toggle_focus_ab)
        self.sections_btn = QPushButton("Hide Sections")
        self.sections_btn.setCheckable(True)
        self.sections_btn.toggled.connect(self.toggle_sections)
        self.numbers_btn = QPushButton("Hide Line Numbers")
        self.numbers_btn.setCheckable(True)
        self.numbers_btn.toggled.connect(self.toggle_line_numbers)
        self.swap = QPushButton("Swap A / B")
        self.swap.clicked.connect(self.swap_ab)
        self.mode = QComboBox()
        self.mode.addItems(["Raw Diff", "Structured summary"])
        self.mode.currentIndexChanged.connect(self.refresh)
        self.only = QCheckBox("Changes only")
        self.only.toggled.connect(self.refresh)
        self.ignore_backspace = QCheckBox("Ignore Backspace")
        self.ignore_backspace.setToolTip("Ignore ASCII Backspace (0x08) in the view and diff; original files stay unchanged")
        self.ignore_backspace.setChecked(True)
        self.ignore_backspace.toggled.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search config text")
        self.search.returnPressed.connect(self.find_next)
        self.search.textChanged.connect(self.invalidate_search)
        self.search_regex = QCheckBox("Regex")
        self.search_regex.toggled.connect(self.invalidate_search)
        self.search_scope = QComboBox()
        self.search_scope.currentIndexChanged.connect(self.invalidate_search)
        self.find_prev_btn = QPushButton("Previous")
        self.find_next_btn = QPushButton("Next")
        self.find_prev_btn.clicked.connect(self.find_previous)
        self.find_next_btn.clicked.connect(self.find_next)
        self.search_result = QLabel("")
        self.search_result.setMinimumWidth(85)
        self.update_search_scopes()
        self.browse_folder = QLineEdit()
        self.browse_folder.setPlaceholderText("Optional folder path for Browse A / B / C")
        self.browse_folder.setClearButtonEnabled(True)
        self.find_shortcut = QShortcut(QKeySequence.Find, self, activated=self.open_find)
        self.next_shortcut = QShortcut(QKeySequence.FindNext, self, activated=self.find_next)
        self.previous_shortcut = QShortcut(QKeySequence.FindPrevious, self, activated=self.find_previous)
        self.minus = QPushButton("A−")
        self.plus = QPushButton("A+")
        self.font_choice = QFontComboBox()
        self.font_choice.setToolTip("Choose an installed macOS font for the config panes")
        self.font_choice.setCurrentFont(QFont(self.font_family))
        self.font_choice.currentFontChanged.connect(self.set_font_family)
        self.minus.clicked.connect(lambda: self.zoom(-1))
        self.plus.clicked.connect(lambda: self.zoom(1))
        self.save_btn = QPushButton("Save Project")
        self.save_btn.clicked.connect(self.save_project)
        self.open_btn = QPushButton("Open Project")
        self.open_btn.clicked.connect(self.load_project)
        self.restore_btn = QPushButton("Restore Backup")
        self.restore_btn.clicked.connect(self.restore_backup)
        self.export_btn = QPushButton("Export Diff")
        self.export_btn.clicked.connect(self.export_diff)
        self.copy_diff_btn = QPushButton("Copy Diff")
        self.copy_diff_btn.clicked.connect(self.copy_diff)
        self.dark = QCheckBox("Dark")
        self.dark.toggled.connect(self.set_theme)
        for widget in (self.add_c, self.focus_ab, self.sections_btn, self.numbers_btn, self.swap, self.mode, self.only, self.font_choice, self.minus, self.plus):
            bar.addWidget(widget)
        bar.addStretch(1)
        find_bar.addWidget(QLabel("Find"))
        find_bar.addWidget(self.search, 1)
        for widget in (self.search_regex, self.search_scope, self.find_prev_btn, self.find_next_btn, self.search_result):
            find_bar.addWidget(widget)
        for widget in (self.open_btn, self.save_btn, self.restore_btn, self.export_btn, self.copy_diff_btn, self.dark):
            file_bar.addWidget(widget)
        file_bar.addStretch(1)
        self.tabs = QTabBar()
        self.tabs.setExpanding(False)
        self.tabs.setTabsClosable(True)
        self.new_tab_btn = QPushButton("+ Comparison")
        self.new_tab_btn.clicked.connect(self.new_comparison)
        self.clear_history_btn = QPushButton("Clear History")
        self.clear_history_btn.clicked.connect(self.clear_history)
        tab_row = QHBoxLayout()
        tab_row.addWidget(self.tabs, 1)
        tab_row.addWidget(self.new_tab_btn)
        tab_row.addWidget(self.clear_history_btn)
        page.addLayout(tab_row)
        self.path_widget = QWidget()
        self.path_widget.setLayout(path_bar)
        path_bar.setContentsMargins(0, 0, 0, 0)
        path_bar.addWidget(QLabel("Browse folder"))
        path_bar.addWidget(self.browse_folder, 1)
        page.addWidget(self.path_widget)
        self.controls = QWidget()
        controls_layout = QVBoxLayout(self.controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addLayout(bar)
        controls_layout.addLayout(file_bar)
        page.addWidget(self.controls)
        self.controls.hide()
        self.find_dialog = QDialog(self)
        self.find_dialog.setWindowTitle("Find in comparison")
        self.find_dialog.resize(800, 100)
        find_layout = QVBoxLayout(self.find_dialog)
        find_layout.addLayout(find_bar)
        main = QSplitter(Qt.Horizontal)
        self.main_split = main
        main.setHandleWidth(9)
        main.setChildrenCollapsible(False)
        main.setStyleSheet("QSplitter::handle:horizontal { background: #d7dde5; } QSplitter::handle:horizontal:hover { background: #89acd2; }")
        self.blocks = QListWidget()
        self.blocks.setMinimumWidth(130)
        self.blocks.itemClicked.connect(lambda item: self.jump(item.data(Qt.UserRole)))
        main.addWidget(self.blocks)
        viewer_box = QWidget()
        view_layout = QHBoxLayout(viewer_box)
        view_layout.setContentsMargins(0, 0, 0, 0)
        self.split = DiffSplitter(self)
        self.split.setHandleWidth(48)
        self.split.setChildrenCollapsible(False)
        self.split.setStyleSheet("QSplitter::handle:horizontal { background: #d7dde5; } QSplitter::handle:horizontal:hover { background: #89acd2; }")
        for i, pane in enumerate(self.panes):
            pane.browse.clicked.connect(lambda _, n=i: self.browse(n))
            pane.dropped.connect(lambda path, n=i: self.load_file(n, path))
            pane.copy.triggered.connect(lambda _, n=i: self.copy_original(n))
            pane.copy_block.triggered.connect(lambda _, n=i: self.copy_block(n))
            pane.edit.triggered.connect(lambda _, n=i: self.edit_source(n))
            if i < 2:
                pane.align_line = QAction("Mark line for visual alignment", pane)
                pane.align_line.triggered.connect(lambda _, n=i: self.mark_alignment_line(n))
                pane.actions.menu().addSeparator()
                pane.actions.menu().addAction(pane.align_line)
            pane.viewer.verticalScrollBar().valueChanged.connect(lambda value, n=i: self.scroll(n, value))
            pane.viewer.horizontalScrollBar().valueChanged.connect(lambda value, n=i: self.scroll_horizontal(n, value))
            pane.viewer.zoomRequested.connect(self.zoom)
            pane.viewer.zoomScaleRequested.connect(self.zoom_scale)
            self.split.addWidget(pane)
        self.panes[2].hide()
        view_layout.addWidget(self.split, 1)
        self.map = MiniMap()
        self.map.jumped.connect(self.jump)
        view_layout.addWidget(self.map)
        main.addWidget(viewer_box)
        main.setStretchFactor(1, 5)
        page.addWidget(main, 1)
        self.sections_btn.setChecked(True)
        self.status = QLabel("Drop two configs or use Browse. All processing stays on this computer.")
        bottom = QHBoxLayout()
        bottom.addWidget(self.status, 1)
        self.text_mode = QLabel("Plain Text")
        self.encoding_status = QLabel("")
        self.encoding_status.setToolTip("Encoding used to read each file; Latin-1 fallback does not identify the original codec")
        bottom.addWidget(self.text_mode)
        bottom.addWidget(self.encoding_status)
        page.addLayout(bottom)
        self.setup_menus()
        self.zoom(0)
        self.refresh()
        first = self.tabs.addTab("Comparison 1")
        self._current_session = self.capture_session()
        self._sessions = [self._current_session]
        self.tabs.currentChanged.connect(self.switch_comparison)
        self.tabs.tabCloseRequested.connect(self.close_comparison)
        self.restore_history()

    def active(self):
        return len(self.sources)

    def setup_menus(self):
        file_menu = self.menuBar().addMenu("File")
        self.file_menu = file_menu
        def action(parent, title, callback, shortcut=None):
            item = QAction(title, self)
            if shortcut: item.setShortcut(QKeySequence(shortcut))
            item.triggered.connect(lambda checked=False: callback())
            parent.addAction(item)
            return item

        action(file_menu, "New Comparison Tab", self.new_comparison, "Ctrl+T")
        action(file_menu, "Close Comparison Tab", lambda: self.close_comparison(self.tabs.currentIndex()), "Ctrl+W")
        file_menu.addSeparator()
        for i, letter in enumerate("ABC"):
            action(file_menu, f"Browse {letter}…", lambda n=i: self.browse_in_pane(n))
        file_menu.addSeparator()
        action(file_menu, "Open Project…", self.load_project)
        action(file_menu, "Save Project…", self.save_project)
        action(file_menu, "Restore Backup…", self.restore_backup)
        action(file_menu, "Export Diff…", self.export_diff)
        file_menu.addSeparator()
        action(file_menu, "Clear History…", self.clear_history)

        compare = self.menuBar().addMenu("Compare")
        action(compare, "Mark Current A Line", lambda: self.mark_alignment_line(0))
        action(compare, "Mark Current B Line", lambda: self.mark_alignment_line(1))
        action(compare, "Align Cursor Lines A ↔ B", self.align_cursor_lines)
        action(compare, "Reset Visual Alignment", self.reset_alignment)
        compare.addSeparator()
        action(compare, "Swap A / B", self.swap_ab)
        action(compare, "Show / Hide C", self.toggle_c)
        action(compare, "Focus A+B / Show C", self.focus_ab.click)
        action(compare, "Ignore Backspace", self.ignore_backspace.click)
        action(compare, "Copy Diff", self.copy_diff)

        view = self.menuBar().addMenu("View")
        action(view, "Show / Hide Sections", self.sections_btn.click)
        action(view, "Show / Hide Line Numbers", self.numbers_btn.click)
        action(view, "Changes Only", self.only.click)
        action(view, "Raw Diff Sections", lambda: self.mode.setCurrentIndex(0))
        action(view, "All Sections", lambda: self.mode.setCurrentIndex(1))
        action(view, "Dark Mode", self.dark.click)
        action(view, "Choose Font…", self.choose_font)
        action(view, "Zoom In", lambda: self.zoom(1))
        action(view, "Zoom Out", lambda: self.zoom(-1))
        search_menu = self.menuBar().addMenu("Search")
        action(search_menu, "Find…", self.open_find)
        action(search_menu, "Find Next", self.find_next)
        action(search_menu, "Find Previous", self.find_previous)

        self.show_controls_action = QAction("Show Toolbar", self)
        self.show_controls_action.setCheckable(True)
        self.show_controls_action.toggled.connect(self.controls.setVisible)
        view.addAction(self.show_controls_action)
        self.show_folder_action = QAction("Show Browse Folder", self)
        self.show_folder_action.setCheckable(True)
        self.show_folder_action.setChecked(True)
        self.show_folder_action.toggled.connect(self.path_widget.setVisible)
        view.addAction(self.show_folder_action)

    def browse_in_pane(self, index: int):
        if index == 2 and self.active() == 2:
            self.toggle_c()
        self.browse(index)

    def open_find(self):
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()
        self.search.setFocus()

    def choose_font(self):
        current = QFont(self.font_family)
        current.setPointSizeF(self.font_size)
        font, accepted = QFontDialog.getFont(current, self, "Choose comparison font")
        if accepted:
            self.font_choice.setCurrentFont(font)
            self.font_family = font.family()
            self.set_font_size(font.pointSizeF())

    def capture_session(self):
        return dict(
            sources=list(self.sources), project_path=self.project_path,
            manual_anchors={side: list(pairs) for side, pairs in self.manual_anchors.items()},
            font_size=self.font_size, font_family=self.font_family,
            mode=self.mode.currentIndex(), only=self.only.isChecked(),
            ignore=self.ignore_backspace.isChecked(), dark=self.dark.isChecked(),
            numbers=self.numbers_btn.isChecked(), sections=self.sections_btn.isChecked(),
            focus=self.focus_ab.isChecked(),
            search=self.search.text(), regex=self.search_regex.isChecked(),
            scope=self.search_scope.currentData(),
            scroll=[pane.viewer.verticalScrollBar().value() for pane in self.panes],
        )

    def restore_session(self, session):
        self.scroll_timer.stop()
        self.pending_scroll.clear()
        self.sources = list(session["sources"])
        self.manual_anchors = {int(side): list(pairs) for side, pairs in session.get("manual_anchors", {}).items()}
        self.pending_anchor = {}
        self.project_path = session["project_path"]
        self.font_choice.blockSignals(True)
        self.font_choice.setCurrentFont(QFont(session["font_family"]))
        self.font_choice.blockSignals(False)
        self.font_family = self.font_choice.currentFont().family()
        self.set_font_size(session["font_size"])
        for widget, key in ((self.mode, "mode"), (self.only, "only"),
                            (self.ignore_backspace, "ignore"), (self.dark, "dark"),
                            (self.numbers_btn, "numbers"), (self.sections_btn, "sections"),
                            (self.focus_ab, "focus"), (self.search_regex, "regex")):
            widget.blockSignals(True)
            if widget is self.mode: widget.setCurrentIndex(session[key])
            else: widget.setChecked(session[key])
            widget.blockSignals(False)
        self.panes[2].setVisible(self.active() == 3 and not self.focus_ab.isChecked())
        self.add_c.setText("− C" if self.active() == 3 else "+ C")
        self.focus_ab.setEnabled(self.active() == 3)
        self.focus_ab.setText("Show C" if self.focus_ab.isChecked() else "Focus A+B")
        self.blocks.setVisible(not self.sections_btn.isChecked())
        self.sections_btn.setText("Show Sections" if self.sections_btn.isChecked() else "Hide Sections")
        self.toggle_line_numbers(self.numbers_btn.isChecked())
        self.set_theme(self.dark.isChecked())
        self.update_search_scopes()
        self.search.setText(session["search"])
        for i in range(self.search_scope.count()):
            if self.search_scope.itemData(i) == session["scope"]:
                self.search_scope.setCurrentIndex(i)
                break
        self.refresh()
        self.syncing = True
        for pane, value in zip(self.panes, session["scroll"]):
            pane.viewer.verticalScrollBar().setValue(value)
        self.syncing = False
        self.split.handle(1).update()

    def switch_comparison(self, index: int):
        if index < 0: return
        next_session = self._sessions[index]
        if next_session is self._current_session: return
        self._current_session.update(self.capture_session())
        self._current_session = next_session
        self.restore_session(next_session)

    def new_comparison(self):
        self._current_session.update(self.capture_session())
        blank = self.capture_session()
        blank.update(sources=[Source(), Source()], project_path="", manual_anchors={}, focus=False, search="", scroll=[0, 0, 0])
        self._sessions.append(blank)
        index = self.tabs.addTab(f"Comparison {self.tabs.count() + 1}")
        self.tabs.setCurrentIndex(index)

    def close_comparison(self, index: int):
        if index < 0: return
        if self.tabs.count() == 1:
            self.sources = [Source(), Source()]
            self.manual_anchors.clear()
            self.pending_anchor.clear()
            self.project_path = ""
            self.focus_ab.blockSignals(True)
            self.focus_ab.setChecked(False)
            self.focus_ab.blockSignals(False)
            self.focus_ab.setText("Focus A+B")
            self.panes[2].hide()
            self.add_c.setText("+ C")
            self.focus_ab.setEnabled(False)
            self.update_search_scopes()
            self.refresh()
            return
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self._sessions.pop(index)
        self.tabs.blockSignals(False)
        self.switch_comparison(self.tabs.currentIndex())

    def update_comparison_title(self):
        if not hasattr(self, "_current_session"): return
        index = self.tabs.currentIndex()
        if index < 0: return
        self._current_session["sources"] = list(self.sources)
        title = self.session_title(self._current_session, index)
        self.tabs.setTabText(index, title[:48])
        self.tabs.setTabToolTip(index, title)

    @staticmethod
    def session_title(session, index):
        names = [source.name for source in session["sources"][:2] if source.name]
        return " ↔ ".join(names) if names else f"Comparison {index + 1}"

    @staticmethod
    def serialize_session(session):
        return {key: value for key, value in session.items() if key not in ("sources", "manual_anchors")} | {
            "source_paths": [source.path for source in session["sources"]]
        }

    def deserialize_session(self, saved):
        session = self.capture_session()
        for key in session:
            if key not in ("sources", "scope") and key in saved:
                session[key] = saved[key]
        session["scope"] = tuple(saved.get("scope") or (0, 1))
        paths = saved.get("source_paths", [])
        if not isinstance(paths, list) or not 2 <= len(paths) <= 3:
            raise ValueError("Invalid comparison history")
        project_path = session["project_path"]
        if project_path and Path(project_path).is_file():
            try:
                session["sources"], session["font_size"], session["font_family"] = open_project(project_path)
                return session
            except (OSError, ValueError, TypeError, KeyError):
                pass
        session["project_path"] = ""
        session["sources"] = [read_source(path) if path and Path(path).is_file()
                              else Source(Path(path).name, path) if path else Source()
                              for path in paths]
        return session

    def save_history(self):
        self._current_session.update(self.capture_session())
        sessions = self._sessions
        target = history_path()
        if len(sessions) == 1 and not any(source.path for source in sessions[0]["sources"]) and not sessions[0]["project_path"]:
            target.unlink(missing_ok=True)
            return
        content = {"version": 1, "selected": self.tabs.currentIndex(),
                   "browse_folder": self.browse_folder.text(),
                   "tabs": [self.serialize_session(session) for session in sessions]}
        atomic_save(str(target), json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8"), keep=0)

    def restore_history(self):
        target = history_path()
        if not target.is_file(): return
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("tabs"), list) or not data["tabs"]:
                raise ValueError("Invalid comparison history")
            sessions = [self.deserialize_session(item) for item in data["tabs"]]
            self.browse_folder.setText(data.get("browse_folder", ""))
            self.tabs.blockSignals(True)
            for session in sessions[1:]:
                index = self.tabs.addTab("")
                self.tabs.setTabText(index, self.session_title(session, index)[:48])
            self.tabs.blockSignals(False)
            self._sessions = sessions
            self._current_session = sessions[0]
            self.restore_session(sessions[0])
            selected = max(0, min(self.tabs.count() - 1, int(data.get("selected", 0))))
            self.tabs.setCurrentIndex(selected)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.tabs.blockSignals(False)
            self.status.setText(f"Could not restore comparison history: {exc}")

    def clear_history(self):
        if not self.ask("Clear History", "Close all comparison tabs and clear saved history?\nSource files and saved projects will not be deleted."):
            return
        blank = self.capture_session()
        blank.update(sources=[Source(), Source()], project_path="", manual_anchors={}, focus=False, search="", scroll=[0, 0, 0])
        self.tabs.blockSignals(True)
        while self.tabs.count() > 1:
            self.tabs.removeTab(self.tabs.count() - 1)
        self.tabs.setCurrentIndex(0)
        self.tabs.blockSignals(False)
        self._sessions = [blank]
        self._current_session = blank
        self.browse_folder.clear()
        self.restore_session(blank)
        history_path().unlink(missing_ok=True)
        self.status.setText("History cleared. Drop configs or use Browse to start a new comparison.")

    def ask(self, title: str, message: str) -> bool:
        return QMessageBox.question(self, title, message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes

    def error(self, exc):
        QMessageBox.critical(self, "ConfigDiff", str(exc))

    def toggle_c(self):
        if self.active() == 2:
            self.sources.append(Source())
            self.panes[2].show()
            self.add_c.setText("− C")
            self.focus_ab.setEnabled(True)
        else:
            self.focus_ab.blockSignals(True)
            self.focus_ab.setChecked(False)
            self.focus_ab.blockSignals(False)
            self.focus_ab.setText("Focus A+B")
            self.focus_ab.setEnabled(False)
            self.sources.pop()
            self.panes[2].hide()
            self.add_c.setText("+ C")
        self.update_search_scopes()
        self.refresh()

    def toggle_focus_ab(self, focused: bool):
        if self.active() != 3: return
        self.panes[2].setVisible(not focused)
        self.focus_ab.setText("Show C" if focused else "Focus A+B")
        self.update_search_scopes()
        self.refresh()

    def toggle_sections(self, hidden: bool):
        if hidden:
            self.sections_width = self.main_split.sizes()[0]
        self.blocks.setVisible(not hidden)
        self.sections_btn.setText("Show Sections" if hidden else "Hide Sections")
        if not hidden:
            width = max(130, getattr(self, "sections_width", 210))
            self.main_split.setSizes([width, max(1, self.main_split.width()-width-self.main_split.handleWidth())])

    def toggle_line_numbers(self, hidden: bool):
        for pane in self.panes:
            pane.viewer.set_line_numbers_visible(not hidden)
        self.numbers_btn.setText("Show Line Numbers" if hidden else "Hide Line Numbers")
        self.split.handle(1).update()

    def update_search_scopes(self):
        if not hasattr(self, "search_scope"): return
        old = self.search_scope.currentData()
        self.search_scope.blockSignals(True)
        self.search_scope.clear()
        self.search_scope.addItem("A + B", (0, 1))
        self.search_scope.addItem("A only", (0,))
        self.search_scope.addItem("B only", (1,))
        if self.active() == 3 and not self.focus_ab.isChecked():
            self.search_scope.addItem("A + B + C", (0, 1, 2))
            self.search_scope.addItem("C only", (2,))
        for i in range(self.search_scope.count()):
            if self.search_scope.itemData(i) == old:
                self.search_scope.setCurrentIndex(i)
                break
        self.search_scope.blockSignals(False)
        self.invalidate_search()

    def swap_ab(self):
        self.sources[0], self.sources[1] = self.sources[1], self.sources[0]
        self.reset_alignment(refresh=False)
        self.refresh()

    def cursor_source_line(self, side: int) -> int | None:
        if side >= self.active() or not self.sources[side].text:
            return None
        pane = self.panes[side]
        row = pane.viewer.textCursor().blockNumber()
        return pane.line_map[row] if 0 <= row < len(pane.line_map) else None

    def mark_alignment_line(self, side: int):
        line = self.cursor_source_line(side)
        if line is None:
            self.status.setText(f"Choose a real text line in {'A' if side == 0 else 'B'} first (not a blank alignment gap).")
            return
        self.pending_anchor[side] = line
        if len(self.pending_anchor) == 2:
            self.add_alignment(self.pending_anchor[0], self.pending_anchor[1])
        else:
            other = "B" if side == 0 else "A"
            self.status.setText(f"Marked {self.panes[side].letter} line {line + 1}. Choose a line in {other}, then use Actions > Mark line for visual alignment.")

    def align_cursor_lines(self):
        left, right = self.cursor_source_line(0), self.cursor_source_line(1)
        if left is None or right is None:
            self.status.setText("Place the cursor on a real line in both A and B, then align them.")
            return
        self.add_alignment(left, right)

    def add_alignment(self, left: int, right: int):
        proposed = [pair for pair in self.manual_anchors.get(1, []) if pair[0] != left and pair[1] != right]
        proposed.append((left, right))
        proposed.sort()
        if any(a[0] >= b[0] or a[1] >= b[1] for a, b in zip(proposed, proposed[1:])):
            self.status.setText("Alignment would cross an existing pair. Reset alignment or choose lines in the same order.")
            return
        self.manual_anchors[1] = proposed
        self.pending_anchor.clear()
        if self.only.isChecked():
            self.only.setChecked(False)
        else:
            self.refresh()
        self.status.setText(f"Visually aligned A:{left + 1} ↔ B:{right + 1} ({len(proposed)} pairs). Source files were not changed.")

    def reset_alignment(self, refresh: bool = True):
        self.manual_anchors.clear()
        self.pending_anchor.clear()
        if refresh:
            self.refresh()
            self.status.setText("Visual alignment reset. Source files were not changed.")

    def browse(self, index: int):
        directory = ""
        entered = self.browse_folder.text().strip()
        if entered:
            folder_text = entered[1:-1] if len(entered) >= 2 and entered[0] == entered[-1] and entered[0] in ("'", '"') else entered
            folder = Path(folder_text).expanduser()
            if not folder.is_dir():
                self.error(f"Browse folder not found: {entered}")
                return
            directory = str(folder.resolve())
        path, _ = QFileDialog.getOpenFileName(self, f"Open {self.panes[index].letter}", directory, "Config/text files (*.txt *.cfg *.conf *.config *.log);;All files (*)")
        if path: self.load_file(index, path)

    def load_file(self, index: int, path: str):
        try:
            self.sources[index] = read_source(path)
            self.reset_alignment(refresh=False)
            self.refresh()
        except Exception as exc: self.error(exc)

    def zoom(self, delta: int):
        self.set_font_size(self.font_size + delta * 0.5)

    def zoom_scale(self, scale: float):
        if scale > 0:
            self.set_font_size(self.font_size * scale)

    def set_font_family(self, font: QFont):
        self.font_family = font.family()
        self.set_font_size(self.font_size)

    def set_font_size(self, size: float):
        self.font_size = round(min(30, max(9, size)), 2)
        font = QFont(self.font_family)
        font.setPointSizeF(self.font_size)
        positions = [pane.viewer.firstVisibleBlock().blockNumber() for pane in self.panes]
        self.syncing = True
        for pane in self.panes:
            pane.viewer.setFont(font)
            pane.viewer.update_gutter_width()
        for pane, position in zip(self.panes, positions):
            pane.viewer.verticalScrollBar().setValue(position)
        self.syncing = False
        self.split.handle(1).update()

    def set_theme(self, dark: bool):
        for pane in self.panes:
            pane.viewer.dark_gutter = dark
            pane.viewer.gutter.update()
        if dark:
            self.setStyleSheet("QWidget { background: #20252d; color: #e8ecf2; } QPushButton, QComboBox, QLineEdit, QListWidget { background: #303846; border: 1px solid #586473; padding: 4px; } QPlainTextEdit { background: #20252d; color: #e8ecf2; selection-background-color: #416889; }")
        else:
            self.setStyleSheet("QPlainTextEdit { background: white; color: #17212b; }")

    def comparison_text(self, text: str) -> str:
        return text.replace("\b", "") if self.ignore_backspace.isChecked() else text

    def refresh(self):
        self.invalidate_search()
        self.scroll_timer.stop()
        self.pending_scroll.clear()
        self.syncing = True
        self.encoding_status.setText("  ·  ".join(
            f"{pane.letter}: {source.encoding}" if source.text else f"{pane.letter}: —"
            for pane, source in zip(self.panes[:self.active()], self.sources)
        ))
        for i, pane in enumerate(self.panes[:self.active()]):
            source = self.sources[i]
            label = f"{pane.letter}  ·  {source.name or 'Drop config here'}  ·  {len(source.lines)} lines  ·  {platform(source.text) if source.text else '—'}"
            pane.title.setText(label)
            pane.title.setToolTip(label)
        self.blocks.clear()
        if not self.sources[0].text or not any(s.text for s in self.sources[1:]):
            for pane in self.panes[:self.active()]:
                pane.line_map = list(range(len(self.sources[self.panes.index(pane)].lines)))
                pane.viewer.setPlainText(self.comparison_text(self.sources[self.panes.index(pane)].text))
                pane.viewer.set_line_map(pane.line_map)
                pane.viewer.setExtraSelections([])
            self.map.set_kinds([])
            self.split.handle(1).update()
            self.status.setText("Drop two configs or use Browse. All processing stays on this computer.")
            self.syncing = False
            self.update_comparison_title()
            return
        sources = self.sources if self.active() == 2 or (self.sources[2].text and not self.focus_ab.isChecked()) else self.sources[:2]
        sources = [Source(s.name, s.path, self.comparison_text(s.text), s.disk_hash, s.encoding) for s in sources]
        self.alignment = align(sources, self.manual_anchors)
        rows = list(range(len(self.alignment.indexes)))
        if self.only.isChecked():
            changed = {i for i, statuses in enumerate(self.alignment.kinds) if any(k not in ("same", "gap") for k in statuses[1:]) or (statuses[0] == "same" and "removed" in statuses)}
            rows = sorted({j for i in changed for j in range(max(0, i-2), min(len(self.alignment.indexes), i+3))})
        if self.active() == 3 and len(sources) == 2:
            self.panes[2].viewer.clear()
            self.panes[2].line_map = []
            self.panes[2].viewer.set_line_map([])
        for side, pane in enumerate(self.panes[:len(sources)]):
            pane.line_map = [self.alignment.indexes[row][side] for row in rows]
            output = []
            for row in rows:
                index = self.alignment.indexes[row][side]
                value = sources[side].lines[index] if index is not None else ""
                output.append(value)
            pane.viewer.setPlainText("\n".join(output))
            pane.viewer.set_line_map(pane.line_map)
            selections = []
            for display_row, row in enumerate(rows):
                index = self.alignment.indexes[row][side]
                statuses = self.alignment.kinds[row]
                kind = statuses[side]
                if side == 0 and "removed" in statuses: kind = "removed"
                if side == 0 and "changed" in statuses: kind = "changed"
                if kind == "same": continue
                selection = QTextEdit.ExtraSelection()
                selection.cursor = QTextCursor(pane.viewer.document().findBlockByNumber(display_row))
                selection.format.setBackground(QColor(PALETTE[kind]))
                selection.format.setForeground(QColor("#17212b"))
                selection.format.setProperty(QTextFormat.FullWidthSelection, True)
                selections.append(selection)
                if kind == "changed" and index is not None:
                    peer_side = 0 if side else next((n for n, value in enumerate(statuses[1:], 1) if value == "changed"), None)
                    if peer_side is not None:
                        peer_index = self.alignment.indexes[row][peer_side]
                        if peer_index is not None:
                            value = sources[side].lines[index]
                            peer = sources[peer_side].lines[peer_index]
                            block = pane.viewer.document().findBlockByNumber(display_row)
                            for tag, a1, a2, _, _ in SequenceMatcher(None, value, peer).get_opcodes():
                                if tag == "equal" or a1 == a2: continue
                                mark = QTextEdit.ExtraSelection()
                                mark.cursor = QTextCursor(block)
                                mark.cursor.setPosition(block.position() + a1)
                                mark.cursor.setPosition(block.position() + a2, QTextCursor.KeepAnchor)
                                mark.format.setBackground(QColor("#efbd53"))
                                mark.format.setForeground(QColor("#17212b"))
                                selections.append(mark)
            pane.viewer.setExtraSelections(selections)
        self.map.set_kinds([self.alignment.kinds[i] for i in rows])
        self.split.handle(1).update()
        summary = block_summary(sources[0].lines, sources[1].lines)
        if len(sources) == 3:
            summary += [(c, "C: " + label, pos) for c, label, pos in block_summary(sources[0].lines, sources[2].lines)]
        for category, label, position in summary:
            if self.mode.currentIndex() == 1 or not label.endswith("— Same"):
                item = QListWidgetItem(f"{category} · {label}")
                location = next((n for n, row in enumerate(rows) if self.alignment.indexes[row][0] == position), 0)
                item.setData(Qt.UserRole, location)
                self.blocks.addItem(item)
        added = sum("added" in row for row in self.map.kinds)
        removed = sum("removed" in row for row in self.map.kinds)
        changed = sum("changed" in row for row in self.map.kinds)
        self.status.setText(f"A: {len(sources[0].lines)} lines  ·  Added: {added}  Removed: {removed}  Changed: {changed} display rows  ·  A is the reference")
        self.syncing = False
        self.update_comparison_title()

    def jump(self, row: int):
        if row is None or row < 0: return
        self.scroll_timer.stop()
        self.pending_scroll.clear()
        self.syncing = True
        for pane in self.panes[:self.active()]:
            pane.viewer.verticalScrollBar().setValue(row)
        self.syncing = False
        self.map.set_current(row)
        self.split.handle(1).update()

    def scroll(self, origin: int, value: int):
        if self.syncing: return
        self.pending_scroll["vertical"] = origin, value
        self.map.set_current(value)
        if not self.scroll_timer.isActive(): self.scroll_timer.start()

    def scroll_horizontal(self, origin: int, value: int):
        if self.syncing: return
        self.pending_scroll["horizontal"] = origin, value
        if not self.scroll_timer.isActive(): self.scroll_timer.start()

    def flush_scroll(self):
        self.syncing = True
        try:
            for axis, (origin, value) in self.pending_scroll.items():
                for i, pane in enumerate(self.panes[:self.active()]):
                    if i == origin: continue
                    bar = pane.viewer.verticalScrollBar() if axis == "vertical" else pane.viewer.horizontalScrollBar()
                    bar.setValue(value)
        finally:
            self.pending_scroll.clear()
            self.syncing = False
            self.split.handle(1).update()

    def invalidate_search(self, *_):
        self.search_matches = []
        self.search_index = -1
        self.search_result.setText("")
        self.search_result.setToolTip("")

    def build_search_matches(self) -> bool:
        term = self.search.text()
        if not term:
            self.search_result.setText("Enter text")
            return False
        pattern = term if self.search_regex.isChecked() else QRegularExpression.escape(term)
        expression = QRegularExpression(pattern)
        if not expression.isValid():
            self.search_result.setText("Invalid regex")
            self.search_result.setToolTip(expression.errorString())
            return False
        matches: list[tuple[int, QTextCursor]] = []
        for side in self.search_scope.currentData() or (0, 1):
            if side >= self.active(): continue
            document = self.panes[side].viewer.document()
            position = 0
            while position < document.characterCount() and len(matches) < 10000:
                cursor = document.find(expression, position)
                if cursor.isNull(): break
                matches.append((side, cursor))
                position = max(cursor.selectionEnd(), position + 1)
        matches.sort(key=lambda match: (match[1].blockNumber(), match[0], match[1].selectionStart()))
        self.search_matches = matches
        self.search_result.setText(f"0 / {len(matches)}" if matches else "No matches")
        if len(matches) == 10000:
            self.search_result.setToolTip("Showing the first 10,000 matches")
        return bool(matches)

    def select_search_match(self):
        side, cursor = self.search_matches[self.search_index]
        viewer = self.panes[side].viewer
        viewer.setFocus()
        viewer.setTextCursor(cursor)
        viewer.ensureCursorVisible()
        self.search_result.setText(f"{self.search_index+1} / {len(self.search_matches)}")

    def find_next(self):
        if not self.search_matches and not self.build_search_matches(): return
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        self.select_search_match()

    def find_previous(self):
        if not self.search_matches and not self.build_search_matches(): return
        self.search_index = (self.search_index - 1) % len(self.search_matches)
        self.select_search_match()

    def copy_original(self, index: int):
        QApplication.clipboard().setText(self.panes[index].selected_original(self.sources[index]))

    def copy_block(self, index: int):
        source = self.sources[index]
        row = self.panes[index].viewer.textCursor().blockNumber()
        line = self.panes[index].line_map[row] if row < len(self.panes[index].line_map) else None
        if line is None: return
        block = next((b for b in parse_blocks(source.lines) if b.start <= line < b.start + len(b.lines)), None)
        if block: QApplication.clipboard().setText("\n".join(block.lines))

    def diff_text(self) -> str:
        report = []
        for source in self.sources[1:]:
            if not source.text: continue
            report.extend(unified_diff(self.comparison_text(self.sources[0].text).splitlines(),
                                       self.comparison_text(source.text).splitlines(),
                                       fromfile=self.sources[0].name or "A", tofile=source.name or "B", lineterm=""))
        return "\n".join(report) + ("\n" if report else "")

    def copy_diff(self):
        if self.sources[0].text:
            QApplication.clipboard().setText(self.diff_text())

    def save_project(self):
        path = self.project_path
        if not path:
            path, _ = QFileDialog.getSaveFileName(self, "Save Project", "ConfigDiff.cdiff", "ConfigDiff project (*.cdiff)")
        if not path: return
        if not path.endswith(".cdiff"): path += ".cdiff"
        names = ", ".join(s.name or "empty" for s in self.sources)
        if not self.ask("Confirm Save Project", f"Save {names} into {path}?\nThis project includes full config text, including any secrets."):
            return
        try:
            atomic_save(path, project_bytes(self.sources, self.font_size, self.font_family))
            self.project_path = path
            self.status.setText(f"Saved project: {path}")
        except Exception as exc: self.error(exc)

    def load_project(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Project", "", "ConfigDiff project (*.cdiff)")
        if not path: return
        try:
            self.sources, size, family = open_project(path)
            self.reset_alignment(refresh=False)
            self.project_path = path
            self.font_choice.setCurrentFont(QFont(family))
            self.font_family = self.font_choice.currentFont().family()
            self.set_font_size(size)
            self.focus_ab.setEnabled(self.active() == 3)
            self.focus_ab.setChecked(False)
            self.panes[2].setVisible(self.active() == 3)
            self.add_c.setText("− C" if self.active() == 3 else "+ C")
            self.update_search_scopes()
            self.refresh()
        except Exception as exc: self.error(exc)

    def edit_source(self, index: int):
        source = self.sources[index]
        if not source.path:
            QMessageBox.information(self, "Edit Source", "Load a source file first.")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Edit Source — " + source.name)
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Editing the original file. Saving will create a .bak first."))
        editor = QPlainTextEdit(source.text)
        editor_font = QFont(self.font_family)
        editor_font.setPointSizeF(self.font_size)
        editor.setFont(editor_font)
        layout.addWidget(editor)
        save = QPushButton("Save Source File")
        layout.addWidget(save)
        def commit():
            new_text = editor.toPlainText()
            if new_text == source.text:
                dialog.accept(); return
            target = Path(source.path)
            current = target.read_bytes() if target.exists() else b""
            if digest(current) != source.disk_hash and not self.ask("Source changed on disk", f"{source.name} was changed outside ConfigDiff. Overwrite it and retain a backup?"):
                return
            if not self.ask("Confirm source change", f"Write changes to {source.path}?\nA backup of the existing file will be created first."):
                return
            try:
                data = encode_source_text(new_text, source.encoding)
                atomic_save(source.path, data)
                self.sources[index] = Source(source.name, source.path, new_text, digest(data),
                                             source.encoding if source.encoding != "Unknown" else "UTF-8")
                self.refresh()
                dialog.accept()
            except Exception as exc: self.error(exc)
        save.clicked.connect(commit)
        dialog.exec()

    def restore_backup(self):
        targets = ([self.project_path] if self.project_path else []) + [s.path for s in self.sources if s.path]
        choices = [(p, backup) for p in targets for backup in backup_paths(p)]
        if not choices:
            QMessageBox.information(self, "Restore Backup", "No backups for loaded files or project.")
            return
        from PySide6.QtWidgets import QInputDialog
        labels = [f"{Path(p).name}  ←  {b.name}" for p, b in choices]
        label, ok = QInputDialog.getItem(self, "Restore Backup", "Select backup:", labels, 0, False)
        if not ok: return
        path, backup = choices[labels.index(label)]
        if not self.ask("Confirm Restore", f"Replace {path} with {backup.name}?\nThe current file will be backed up first."):
            return
        try:
            atomic_save(path, backup.read_bytes())
            if path == self.project_path:
                self.sources, size, family = open_project(path)
                self.reset_alignment(refresh=False)
                self.font_choice.setCurrentFont(QFont(family))
                self.font_family = self.font_choice.currentFont().family()
                self.set_font_size(size)
                self.focus_ab.setEnabled(self.active() == 3)
                self.focus_ab.setChecked(False)
                self.panes[2].setVisible(self.active() == 3)
                self.add_c.setText("− C" if self.active() == 3 else "+ C")
                self.update_search_scopes()
            else:
                for i, source in enumerate(self.sources):
                    if source.path == path: self.sources[i] = read_source(path)
                self.reset_alignment(refresh=False)
            self.refresh()
        except Exception as exc: self.error(exc)

    def export_diff(self):
        if not self.sources[0].text: return
        path, _ = QFileDialog.getSaveFileName(self, "Export diff", "comparison.diff", "Unified diff (*.diff *.txt)")
        if not path: return
        if not self.ask("Confirm Export", f"Write full diff to {path}?\nThe report may contain secrets from the source files."):
            return
        try: atomic_save(path, self.diff_text().encode("utf-8"))
        except Exception as exc: self.error(exc)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier and event.key() in (Qt.Key_Plus, Qt.Key_Equal): self.zoom(1)
        elif event.modifiers() & Qt.ControlModifier and event.key() == Qt.Key_Minus: self.zoom(-1)
        else: super().keyPressEvent(event)

    def closeEvent(self, event):
        self.scroll_timer.stop()
        self.pending_scroll.clear()
        try:
            self.save_history()
        except (OSError, ValueError, TypeError) as exc:
            QMessageBox.warning(self, "ConfigDiff", f"Could not save comparison history: {exc}")
        super().closeEvent(event)
