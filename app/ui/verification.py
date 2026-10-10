"""Opt-in, isolated executable checks. No fixtures run in normal app usage."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from app.domain import State, Task, task_size_text


def click(widget, point=None):
    point = point or widget.rect().center()
    global_position = QPointF(widget.mapToGlobal(point))
    for kind, buttons in ((QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton), (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        event = QMouseEvent(kind, QPointF(point), global_position, Qt.MouseButton.LeftButton, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(widget, event)
    QApplication.processEvents()


def verify_ui(window) -> dict:
    checks = []
    window.queue.closing = True  # Fixture jobs never launch network workers.
    window.resize(1080, 960)
    QApplication.processEvents()
    window.message.setStyleSheet("")
    window.message.setText("Проверка интерфейса · тестовые данные")
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    checks.append("frameless_window")
    geometry = window.geometry()
    click(window.title_bar.minimize)
    assert window.isMinimized()
    window.showNormal()
    QApplication.processEvents()
    click(window.title_bar.maximize)
    assert window.isMaximized() and window.title_bar.maximize.symbol == "restore"
    work_area = window.screen().availableGeometry()
    native = QApplication.platformName() == "windows"
    if native:
        assert work_area.contains(window.geometry()), f"Maximized window {window.geometry()} exceeds work area {work_area}"
    click(window.title_bar.maximize)
    assert window.geometry() == geometry
    checks.append("minimize_maximize_restore" + ("_windows_work_area" if native else "_offscreen"))

    entries = [{"url": f"fixture{i}", "title": f"Проверка строки {i}", "duration": 60 + i, "unavailable": False, "qualities": [720], "m4a": True} for i in range(4)]
    window.collections.append({"title": "Проверка интерфейса", "channel": "СЪЁМ", "playlist": True, "entries": entries})
    window.collection_picker.addItem("Проверка интерфейса")
    window.show_collection(0)
    window.playlist_model.select_all(False)
    QApplication.processEvents()
    for column in (1, 2, 0):
        point = window.playlist_view.visualRect(window.playlist_model.index(1, column)).center()
        click(window.playlist_view.viewport(), point)
        assert window.playlist_model.selected == {1}
        click(window.playlist_view.viewport(), point)
        assert not window.playlist_model.selected
    checks.append("playlist_title_duration_checkbox_single_toggle")
    window.playlist_model.select_all(True)
    tasks = [Task(f"fixture{i}", f"Проверка очереди {i}", {}, "folder", state=State.FAILED) for i in range(12)]
    window.queue.tasks = tasks.copy()
    window.queue_model.refresh()
    window.queue_summary()
    QApplication.processEvents()
    window.splitter.moveSplitter(window.splitter.widget(0).height() - 35, 1)
    expanded = window.queue_panel.height()
    window.queue_view.verticalScrollBar().setValue(80)
    click(window.collapse_button)
    assert window.queue_panel.height() == 44 and window.queue_stack.isHidden()
    click(window.collapse_button)
    assert abs(window.queue_panel.height() - expanded) <= 2 and window.queue_view.verticalScrollBar().value() == 80
    assert window.storage.load_preferences().queue_height == expanded
    checks.append("queue_resize_collapse_restore_scroll_persistence")

    window.queue_view.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    rect = window.queue_view.visualRect(window.queue_model.index(0))
    click(window.queue_view.viewport(), QPoint(rect.right() - 25, rect.top() + 34))
    assert len(window.queue.tasks) == 11 and tasks[0] not in window.queue.tasks
    window.queue.retry(tasks[1])
    assert tasks[1].state == State.WAITING
    window.queue.remove(tasks[1])
    assert tasks[1] not in window.queue.tasks
    checks.append("failed_remove_and_retry_pending_remove")
    media = window.storage.data / "preserved-file.bin"
    media.write_bytes(b"x" * 1234)
    completed = Task("fixture", "Размер готового файла", {}, "folder", state=State.COMPLETED, path=str(media), final_size=media.stat().st_size)
    window.queue.tasks.append(completed)
    assert task_size_text(completed) == "Файл: 1.2 КБ"
    window.queue_model.refresh()
    window.queue_summary()
    window.grab().save(str(window.storage.data / "updated-ui.png"))
    window.clear_queue()
    assert not window.queue.tasks and media.stat().st_size == 1234 and not window.storage.load_history()
    checks.append("clear_all_keeps_output_file_and_persists")
    return {"checks": checks, "native_windows": native, "work_area": [work_area.x(), work_area.y(), work_area.width(), work_area.height()], "passed": len(checks)}
