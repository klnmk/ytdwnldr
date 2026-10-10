from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, QPointF, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QLabel, QStyledItemDelegate, QStyle, QWidget

from app.domain import ACTIVE, State, Task, duration_text
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
            self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
            self.selection_changed.emit()
            return True
        return False

    def select_all(self, select=True):
        self.selected = {i for i, e in enumerate(self.entries) if not e.get("unavailable")} if select else set()
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, 0), [Qt.ItemDataRole.CheckStateRole])
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

    def sizeHint(self, option, index):
        return QSize(600, 68)

    def paint(self, painter: QPainter, option, index):
        task: Task = index.data(Qt.ItemDataRole.UserRole)
        rect = option.rect.adjusted(12, 6, -12, -6)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(option.rect, QColor("#D9EDEE" if option.state & QStyle.StateFlag.State_Selected else "#F8F6F0"))
        painter.setPen(QColor(INK))
        painter.setFont(QFont("Golos Text", 10, QFont.Weight.Medium))
        title_width = max(80, rect.width() - 312)
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
        bar = QRect(rect.right() - 300, rect.top() + 28, 168, 7)
        painter.fillRect(bar, QColor("#D8D7D1"))
        if task.progress >= 0:
            painter.fillRect(QRect(bar.left(), bar.top(), int(bar.width() * min(100, task.progress) / 100), bar.height()), QColor(LIME if task.state == State.COMPLETED else "#548F91"))
        else:
            painter.fillRect(QRect(bar.left(), bar.top(), 50, bar.height()), QColor(CYAN))
        painter.setPen(QColor("#A4312D" if task.state == State.FAILED else INK))
        status = task.state.value
        if task.state == State.DOWNLOADING and task.progress >= 0:
            status += f" · {int(task.progress)}%"
        painter.drawText(QRect(bar.left(), rect.top(), 182, 23), Qt.AlignmentFlag.AlignVCenter, status)
        parts = []
        if task.speed:
            parts.append(f"{task.speed / 1048576:.1f} МБ/с")
        if task.eta is not None and task.state == State.DOWNLOADING:
            parts.append("осталось " + duration_text(task.eta))
        if task.playlist:
            parts.append(f"№ {task.index:03d}")
        painter.setPen(QColor("#595951"))
        painter.drawText(QRect(bar.left(), bar.bottom() + 2, 190, 18), Qt.AlignmentFlag.AlignVCenter, " · ".join(parts))
        button = QRect(rect.right() - 105, rect.top() + 9, 104, 30)
        painter.setPen(QPen(QColor(INK), 1))
        painter.setBrush(QColor(CYAN if task.state == State.COMPLETED else PAPER))
        painter.drawRect(button)
        action = "Папка ↗" if task.state == State.COMPLETED else "Повторить ↻" if task.state in {State.FAILED, State.CANCELLED} else "Отменить ×"
        painter.drawText(button, Qt.AlignmentFlag.AlignCenter, action)
        painter.setPen(QPen(QColor("#D8D7D1"), 1))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == event.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if event.position().x() >= option.rect.right() - 120:
                self.action.emit(index.data(Qt.ItemDataRole.UserRole).id)
                return True
        return False
