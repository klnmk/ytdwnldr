"""Compact window controls backed by Qt's native system move/resize APIs."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QRegion
from PySide6.QtWidgets import QAbstractButton, QHBoxLayout, QLabel, QWidget

from app.ui.theme import CYAN, INK, PAPER


def resize_edges(point: QPoint, width: int, height: int, border: int = 6):
    edges = Qt.Edge(0)
    if point.x() < border:
        edges |= Qt.Edge.LeftEdge
    elif point.x() >= width - border:
        edges |= Qt.Edge.RightEdge
    if point.y() < border:
        edges |= Qt.Edge.TopEdge
    elif point.y() >= height - border:
        edges |= Qt.Edge.BottomEdge
    return edges


class WindowButton(QAbstractButton):
    def __init__(self, symbol: str, text: str, callback, parent=None):
        super().__init__(parent)
        self.symbol = symbol
        self.setFixedSize(42, 32)
        self.setToolTip(text)
        self.setAccessibleName(text)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.clicked.connect(callback)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        dark = self.isDown() or (self.symbol == "close" and self.underMouse())
        painter.fillRect(self.rect(), QColor(INK if dark else CYAN if self.underMouse() else PAPER))
        painter.setPen(QPen(QColor(PAPER if dark else INK), 1.7))
        x, y = self.width() // 2, self.height() // 2
        if self.symbol == "minimize":
            painter.drawLine(x - 6, y + 3, x + 6, y + 3)
        elif self.symbol == "maximize":
            painter.drawRect(QRect(x - 6, y - 6, 12, 12))
        elif self.symbol == "restore":
            painter.drawRect(QRect(x - 3, y - 7, 10, 10))
            painter.fillRect(QRect(x - 7, y - 3, 10, 10), QColor(INK if dark else CYAN if self.underMouse() else PAPER))
            painter.drawRect(QRect(x - 7, y - 3, 10, 10))
        else:
            painter.drawLine(x - 5, y - 5, x + 5, y + 5)
            painter.drawLine(x + 5, y - 5, x - 5, y + 5)
        if self.hasFocus():
            painter.setPen(QPen(QColor(INK), 1, Qt.PenStyle.DotLine))
            painter.drawRect(self.rect().adjusted(3, 3, -4, -4))


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setFixedHeight(34)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 1, 6, 1)
        layout.setSpacing(0)
        name = QLabel("СЪЁМ  /  видео и звук")
        name.setStyleSheet("font-family: Oswald; font-size: 15px; font-weight: 600;")
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(name)
        layout.addStretch()
        self.minimize = WindowButton("minimize", "Свернуть окно", window.showMinimized, self)
        self.maximize = WindowButton("maximize", "Развернуть окно", self.toggle_maximized, self)
        self.close_button = WindowButton("close", "Закрыть", window.close, self)
        for item in (self.minimize, self.maximize, self.close_button):
            layout.addWidget(item)

    def toggle_maximized(self):
        if self.owner.isMaximized():
            self.owner.showNormal()
        else:
            self.owner.showMaximized()

    def sync(self):
        restored = self.owner.isMaximized()
        self.maximize.symbol = "restore" if restored else "maximize"
        text = "Восстановить размер" if restored else "Развернуть окно"
        self.maximize.setToolTip(text)
        self.maximize.setAccessibleName(text)
        self.maximize.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            self.owner.windowHandle().startSystemMove()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(PAPER))
        painter.setPen(QPen(QColor(INK), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


class FrameEdges(QWidget):
    """A six-pixel input ring; the content remains ordinary Qt widgets."""
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def sync(self):
        self.setGeometry(self.owner.rect())
        self.setMask(QRegion(self.rect()) - QRegion(self.rect().adjusted(6, 6, -6, -6)))
        self.setVisible(not self.owner.isMaximized() and not self.owner.isFullScreen())
        self.raise_()

    def mouseMoveEvent(self, event):
        edges = resize_edges(event.position().toPoint(), self.width(), self.height())
        diagonal_a = Qt.Edge.LeftEdge | Qt.Edge.TopEdge
        diagonal_b = Qt.Edge.RightEdge | Qt.Edge.BottomEdge
        if edges in (diagonal_a, diagonal_b):
            cursor = Qt.CursorShape.SizeFDiagCursor
        elif edges in (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge, Qt.Edge.RightEdge | Qt.Edge.TopEdge):
            cursor = Qt.CursorShape.SizeBDiagCursor
        elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
            cursor = Qt.CursorShape.SizeHorCursor
        else:
            cursor = Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.owner.windowHandle():
            edges = resize_edges(event.position().toPoint(), self.width(), self.height())
            if edges:
                self.owner.windowHandle().startSystemResize(edges)
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(QPen(QColor(INK), 1))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))


class WindowChrome(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        window.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint | Qt.WindowType.WindowMinimizeButtonHint | Qt.WindowType.WindowMaximizeButtonHint)
        self.edges = FrameEdges(window)
        window.installEventFilter(self)
        self.edges.sync()

    def eventFilter(self, watched, event):
        if watched is self.window and event.type() in (QEvent.Type.Resize, QEvent.Type.WindowStateChange, QEvent.Type.Show):
            self.edges.sync()
            self.window.title_bar.sync()
        return False
