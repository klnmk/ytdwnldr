from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QLabel, QSplitter, QSplitterHandle, QStyledItemDelegate, QStyle, QTableView, QToolTip, QWidget

from app.domain import ACTIVE, State, Task, duration_text, task_size_text
from app.ui.theme import CYAN, INK, LIME, PAPER


def label(text: str, role: str = "", wrap: bool = False) -> QLabel:
    item = QLabel(text)
    if role:
        item.setProperty("role", role)
    item.setWordWrap(wrap)
    item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    item.setTextFormat(Qt.TextFormat.PlainText)
    return item


class Canvas(QWidget):
    """Keep the outer scroll viewport from sizing to hidden stacked pages."""
    def hasHeightForWidth(self):
        return False

    def heightForWidth(self, width):
        return -1


class Masthead(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(116)
        self.setMinimumWidth(360)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(QRect(5, 13, 178, 73), QColor(LIME))
        painter.save()
        painter.translate(12, 3)
        painter.rotate(-3)
        painter.setFont(QFont("Oswald", 52, QFont.Weight.Bold))
        painter.setPen(QColor(INK))
        painter.drawText(QRect(0, 0, 215, 90), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "СЪЁМ")
        painter.restore()
        painter.setFont(QFont("Golos Text", 9, QFont.Weight.Medium))
        painter.drawText(8, 107, "YOUTUBE → ВАША ПАПКА")
        painter.setPen(QPen(QColor(INK), 3))
        painter.setBrush(QColor(CYAN))
        painter.drawPolygon(QPolygonF([QPointF(240, 20), QPointF(248, 38), QPointF(273, 32), QPointF(258, 51), QPointF(272, 73), QPointF(247, 65), QPointF(229, 86), QPointF(232, 60), QPointF(212, 50), QPointF(235, 44)]))
        painter.setFont(QFont("Oswald", 12, QFont.Weight.Bold))
        painter.drawText(298, 43, "ВИДЕО.")
        painter.drawText(298, 66, "ЗВУК.")
        painter.drawText(298, 89, "НА ДИСК.")
        # Halftone strip confined to the blank header margin.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(INK))
        for row in range(4):
            for column in range(12):
                painter.drawEllipse(QPointF(self.width() - 110 + column * 8, 93 + row * 6), 0.8, 0.8)


class QueueHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.SplitVCursor)
        self.setToolTip("Потяните, чтобы изменить высоту очереди")
        self.setAccessibleName("Изменить высоту очереди")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#898980"), 1))
        center = self.width() // 2
        painter.drawLine(0, 6, center - 24, 6)
        painter.drawLine(center + 24, 6, self.width(), 6)
        painter.setPen(QPen(QColor(INK), 1.5))
        for y in (3, 6, 9):
            painter.drawLine(center - 12, y, center + 12, y)


class QueueSplitter(QSplitter):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setHandleWidth(12)
        self.setChildrenCollapsible(False)

    def createHandle(self):
        return QueueHandle(self.orientation(), self)


class PlaylistView(QTableView):
    """Own the entire click so the checkbox delegate cannot toggle twice."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._press = None
        self.setMouseTracking(True)
        self.setSelectionMode(QTableView.SelectionMode.NoSelection)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            self._press = (index.row(), event.position().toPoint()) if index.isValid() else None
            if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
                self.setCurrentIndex(index)
                self.setFocus()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            press, self._press = self._press, None
            if press and index.isValid() and press[0] == index.row() and (event.position().toPoint() - press[1]).manhattanLength() < QApplication.startDragDistance():
                self.model().toggle(index.row())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and self.currentIndex().isValid():
            self.model().toggle(self.currentIndex().row())
            event.accept()
            return
        super().keyPressEvent(event)


class PlaylistModel(QAbstractTableModel):
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self.selected: set[int] = set()

    def set_entries(self, entries: list[dict]):
        self.beginResetModel()
        self.entries = entries
        self.selected = {i for i, e in enumerate(entries) if not e.get("unavailable")}
        self.endResetModel()
        self.selection_changed.emit()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 3

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return ("", "ВИДЕО", "ВРЕМЯ")[section]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            return Qt.CheckState.Checked if index.row() in self.selected else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            if index.column() == 1:
                return f"{entry.get('index', index.row() + 1):03d}  {entry['title']}" + (" · недоступно" if entry.get("unavailable") else "")
            if index.column() == 2:
                return duration_text(entry.get("duration"))
        if role == Qt.ItemDataRole.ToolTipRole:
            return entry["title"]
        if role == Qt.ItemDataRole.ForegroundRole and entry.get("unavailable"):
            return QColor("#87877F")
        if role == Qt.ItemDataRole.BackgroundRole and index.row() in self.selected:
            return QColor("#D9EDEE")

    def flags(self, index):
        if not index.isValid() or self.entries[index.row()].get("unavailable"):
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | (Qt.ItemFlag.ItemIsUserCheckable if index.column() == 0 else Qt.ItemFlag.NoItemFlags)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and not self.entries[index.row()].get("unavailable"):
            if value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked:
                self.selected.add(index.row())
            else:
                self.selected.discard(index.row())
            self.dataChanged.emit(self.index(index.row(), 0), self.index(index.row(), 2), [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.BackgroundRole])
            self.selection_changed.emit()
            return True
        return False

    def toggle(self, row: int):
        if 0 <= row < len(self.entries) and not self.entries[row].get("unavailable"):
            self.setData(self.index(row, 0), Qt.CheckState.Unchecked if row in self.selected else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)

    def select_all(self, select=True):
        self.selected = {i for i, e in enumerate(self.entries) if not e.get("unavailable")} if select else set()
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, 2), [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.BackgroundRole])
        self.selection_changed.emit()

    def selected_entries(self):
        return [self.entries[i] for i in sorted(self.selected)]


class QueueModel(QAbstractListModel):
    def __init__(self, queue, parent=None):
        super().__init__(parent)
        self.queue = queue
        queue.changed.connect(self.refresh)
        queue.updated.connect(self.update_task)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.queue.tasks)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        task = self.queue.tasks[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return task.title
        if role == Qt.ItemDataRole.UserRole:
            return task
        if role == Qt.ItemDataRole.ToolTipRole:
            return task.error or task.note or task.title

    def refresh(self):
        self.beginResetModel()
        self.endResetModel()

    def update_task(self, identity):
        for row, task in enumerate(self.queue.tasks):
            if task.id == identity:
                self.dataChanged.emit(self.index(row), self.index(row))
                break


class QueueDelegate(QStyledItemDelegate):
    action = Signal(str)
    remove = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pressed_action = None

    def sizeHint(self, option, index):
        return QSize(600, 76)

    def paint(self, painter: QPainter, option, index):
        task: Task = index.data(Qt.ItemDataRole.UserRole)
        rect = option.rect.adjusted(12, 6, -12, -6)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(option.rect, QColor("#D9EDEE" if option.state & QStyle.StateFlag.State_Selected else "#F8F6F0"))
        painter.setPen(QColor(INK))
        painter.setFont(QFont("Golos Text", 10, QFont.Weight.Medium))
        title_width = max(80, rect.width() - 366)
        title = painter.fontMetrics().elidedText(task.title, Qt.TextElideMode.ElideRight, title_width)
        painter.drawText(QRect(rect.left(), rect.top(), title_width, 22), Qt.AlignmentFlag.AlignVCenter, title)
        painter.setFont(QFont("Golos Text", 8))
        painter.setPen(QColor("#595951"))
        detail = task.error if task.state == State.FAILED else task.note
        if not detail:
            detail = task.options.get("output", "").upper()
            if task.options.get("output") == "mp4":
                detail += " · " + (f"{task.options['height']}p" if task.options.get("height") else "лучшее качество")
            elif task.options.get("output") == "mp3":
                detail += f" · {task.options.get('bitrate', 192)} кбит/с"
        painter.drawText(QRect(rect.left(), rect.top() + 25, title_width, 20), Qt.AlignmentFlag.AlignVCenter, painter.fontMetrics().elidedText(detail, Qt.TextElideMode.ElideRight, title_width))
        size = task_size_text(task)
        painter.drawText(QRect(rect.left(), rect.top() + 44, title_width, 18), Qt.AlignmentFlag.AlignVCenter, painter.fontMetrics().elidedText(size, Qt.TextElideMode.ElideRight, title_width))
        bar = QRect(rect.right() - 352, rect.top() + 28, 190, 7)
        painter.fillRect(bar, QColor("#D8D7D1"))
        if task.progress >= 0:
            painter.fillRect(QRect(bar.left(), bar.top(), int(bar.width() * min(100, task.progress) / 100), bar.height()), QColor(LIME if task.state == State.COMPLETED else "#548F91"))
        else:
            painter.fillRect(QRect(bar.left(), bar.top(), 50, bar.height()), QColor(CYAN))
        painter.setPen(QColor("#A4312D" if task.state == State.FAILED else INK))
        status = task.state.value
        painter.drawText(QRect(bar.left(), rect.top(), 198, 23), Qt.AlignmentFlag.AlignVCenter, status)
        parts = []
        if task.speed:
            parts.append(f"{task.speed / 1048576:.1f} МБ/с")
        if task.eta is not None and task.state == State.DOWNLOADING:
            parts.append("осталось " + duration_text(task.eta))
        if task.playlist:
            parts.append(f"№ {task.index:03d}")
        painter.setPen(QColor("#595951"))
        painter.drawText(QRect(bar.left(), bar.bottom() + 2, 190, 18), Qt.AlignmentFlag.AlignVCenter, " · ".join(parts))
        button = QRect(rect.right() - 137, rect.top() + 13, 100, 30)
        painter.setPen(QPen(QColor(INK), 1))
        painter.setBrush(QColor(CYAN if task.state == State.COMPLETED else PAPER))
        painter.drawRect(button)
        action = "Папка ↗" if task.state == State.COMPLETED else "Повторить ↻" if task.state in {State.FAILED, State.CANCELLED} else "Отменить ×"
        painter.drawText(button, Qt.AlignmentFlag.AlignCenter, action)
        remove = QRect(rect.right() - 31, rect.top() + 13, 30, 30)
        painter.drawRect(remove)
        painter.drawLine(remove.center().x() - 4, remove.center().y() - 4, remove.center().x() + 4, remove.center().y() + 4)
        painter.drawLine(remove.center().x() + 4, remove.center().y() - 4, remove.center().x() - 4, remove.center().y() + 4)
        painter.setPen(QPen(QColor("#D8D7D1"), 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() in (event.Type.MouseButtonPress, event.Type.MouseButtonRelease) and event.button() == Qt.MouseButton.LeftButton:
            rect = option.rect.adjusted(12, 6, -12, -6)
            action = None
            if QRect(rect.right() - 31, rect.top() + 13, 30, 30).contains(event.position().toPoint()):
                action = "remove"
            elif QRect(rect.right() - 137, rect.top() + 13, 100, 30).contains(event.position().toPoint()):
                action = "action"
            identity = index.data(Qt.ItemDataRole.UserRole).id
            if event.type() == event.Type.MouseButtonPress:
                self._pressed_action = (identity, action) if action else None
                return bool(action)
            pressed, self._pressed_action = self._pressed_action, None
            if action and pressed == (identity, action):
                (self.remove if action == "remove" else self.action).emit(identity)
                return True
        return False

    def helpEvent(self, event, view, option, index):
        rect = option.rect.adjusted(12, 6, -12, -6)
        if QRect(rect.right() - 31, rect.top() + 13, 30, 30).contains(event.pos()):
            QToolTip.showText(event.globalPos(), "Убрать из очереди · файл останется на диске · Delete", view)
            return True
        size = task_size_text(index.data(Qt.ItemDataRole.UserRole))
        if size:
            QToolTip.showText(event.globalPos(), (index.data(Qt.ItemDataRole.ToolTipRole) or "") + "\n" + size, view)
            return True
        return super().helpEvent(event, view, option, index)
