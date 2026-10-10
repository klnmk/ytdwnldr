import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.domain import State, Task
from app.storage import Storage
from app.ui.chrome import resize_edges
from app.ui.window import MainWindow


@pytest.fixture
def window(qt, tmp_path):
    storage = Storage(tmp_path)
    (storage.root / "bin").mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        (storage.root / "bin" / name).touch()
    item = MainWindow(storage)
    item.resize(1080, 960)
    item.show()
    qt.processEvents()
    yield item
    item.close()
    qt.processEvents()


def playlist(window):
    entries = [{"title": f"Запись {i}", "url": f"url{i}", "duration": 10, "unavailable": i == 4, "qualities": [720], "m4a": True} for i in range(5)]
    window.collections.append({"title": "Плейлист", "channel": "Канал", "playlist": True, "entries": entries})
    window.collection_picker.addItem("Плейлист")
    window.show_collection(0)
    window.playlist_model.select_all(False)


@pytest.mark.parametrize("column", [0, 1, 2])
def test_every_playlist_column_toggles_exactly_once(window, qt, column):
    playlist(window)
    qt.processEvents()
    view = window.playlist_view
    changes = []
    window.playlist_model.selection_changed.connect(lambda: changes.append(True))
    point = view.visualRect(window.playlist_model.index(1, column)).center()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert window.playlist_model.selected == {1} and len(changes) == 1
    assert "1" in window.selected_label.text()
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=point)
    assert not window.playlist_model.selected and len(changes) == 2


def test_playlist_space_bulk_selection_and_unavailable_row(window, qt):
    playlist(window)
    qt.processEvents()
    view = window.playlist_view
    view.setCurrentIndex(window.playlist_model.index(2, 1))
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert window.playlist_model.selected == {2}
    QTest.keyClick(view, Qt.Key.Key_Space)
    assert not window.playlist_model.selected
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(window.playlist_model.index(4, 1)).center())
    assert not window.playlist_model.selected
    window.playlist_model.select_all(True)
    assert window.playlist_model.selected == {0, 1, 2, 3}
    window.playlist_model.select_all(False)
    assert not window.playlist_model.selected


def test_splitter_drag_collapse_restore_and_persistence(window, qt):
    window.queue.tasks = [Task(f"url{i}", f"Файл {i}", {}, "folder", state=State.FAILED) for i in range(30)]
    window.queue_model.refresh()
    window.queue_summary()
    qt.processEvents()
    handle = window.splitter.handle(1)
    old = window.queue_panel.height()
    point = handle.rect().center()
    QTest.mousePress(handle, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(handle, point - QPoint(0, 60))
    QTest.mouseRelease(handle, Qt.MouseButton.LeftButton, pos=point - QPoint(0, 60))
    qt.processEvents()
    expanded = window.queue_panel.height()
    assert expanded > old and window.splitter.widget(0).geometry().bottom() < window.queue_panel.geometry().top()
    window.queue_view.verticalScrollBar().setValue(100)
    QTest.mouseClick(window.collapse_button, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert window.queue_stack.isHidden() and window.queue_panel.height() == 44
    assert window.storage.load_preferences().queue_collapsed
    QTest.mouseClick(window.collapse_button, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert not window.queue_stack.isHidden() and abs(window.queue_panel.height() - expanded) <= 2
    assert window.queue_view.verticalScrollBar().value() == 100
    window.toggle_queue()
    window.close()
    recovered = MainWindow(window.storage)
    recovered.resize(1080, 960)
    recovered.show()
    qt.processEvents()
    assert recovered.prefs.queue_collapsed and recovered.queue_panel.height() == 44
    recovered.toggle_queue()
    qt.processEvents()
    assert abs(recovered.queue_panel.height() - expanded) <= 2
    recovered.close()


def test_queue_delete_button_and_keyboard_preserve_retry(window, qt):
    tasks = [Task(f"url{i}", f"Ошибка {i}", {}, "folder", state=State.FAILED) for i in range(3)]
    window.queue.tasks = tasks.copy()
    window.queue_model.refresh()
    window.queue_summary()
    qt.processEvents()
    rect = window.queue_view.visualRect(window.queue_model.index(0))
    QTest.mouseClick(window.queue_view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(rect.right() - 25, rect.top() + 34))
    assert window.queue.tasks == tasks[1:] and window.retry_button.isEnabled()
    window.queue_view.setCurrentIndex(window.queue_model.index(0))
    window.queue_view.setFocus()
    QTest.keyClick(window.queue_view, Qt.Key.Key_Delete)
    assert window.queue.tasks == tasks[2:]
    window.clear_queue()
    assert not window.queue.tasks and not window.clear_button.isEnabled()


def test_clear_active_confirmation_can_decline_or_accept(window, monkeypatch):
    task = Task("url", "Загрузка", {}, "folder", state=State.DOWNLOADING)
    window.queue.tasks.append(task)
    window.queue_summary()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    window.clear_queue()
    assert window.queue.tasks == [task]
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    window.clear_queue()
    assert not window.queue.tasks and not window.clear_button.isEnabled()


def test_custom_title_controls_and_double_click(window, qt):
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
    geometry = window.geometry()
    QTest.mouseClick(window.title_bar.minimize, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert window.isMinimized()
    window.showNormal()
    QTest.mouseClick(window.title_bar.maximize, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert window.isMaximized() and window.title_bar.maximize.symbol == "restore"
    assert window.chrome.edges.isHidden()
    QTest.mouseClick(window.title_bar.maximize, Qt.MouseButton.LeftButton)
    qt.processEvents()
    assert not window.isMaximized() and window.geometry() == geometry
    QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 16))
    assert window.isMaximized()
    QTest.mouseDClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 16))
    assert not window.isMaximized()
    QTest.mouseClick(window.title_bar.close_button, Qt.MouseButton.LeftButton)
    assert window.closing and not window.isVisible()


def test_move_and_edge_resize_use_system_apis(window, monkeypatch):
    calls = []
    class Handle:
        def startSystemMove(self):
            calls.append("move")
        def startSystemResize(self, edges):
            calls.append(edges)
    monkeypatch.setattr(window, "windowHandle", lambda: Handle())
    QTest.mouseClick(window.title_bar, Qt.MouseButton.LeftButton, pos=QPoint(300, 16))
    QTest.mouseClick(window.chrome.edges, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
    assert calls == ["move", Qt.Edge.LeftEdge | Qt.Edge.TopEdge]
    assert not resize_edges(QPoint(400, 300), 880, 650)
    assert resize_edges(QPoint(878, 648), 880, 650) == Qt.Edge.RightEdge | Qt.Edge.BottomEdge


def test_executable_verification_helper_runs_complete_fixture(window):
    from app.ui.verification import verify_ui
    result = verify_ui(window)
    assert result["passed"] == 6 and not window.queue.tasks
    assert (window.storage.data / "updated-ui.png").exists()
    assert (window.storage.data / "preserved-file.bin").stat().st_size == 1234


def test_collapsed_queue_keeps_receiving_active_progress(window):
    task = Task("url", "Активная загрузка", {}, "folder", state=State.DOWNLOADING)
    window.queue.tasks.append(task)
    window.queue_model.refresh()
    window.queue_summary()
    window.toggle_queue()
    assert window.queue_stack.isHidden()
    window.queue.handle_event(task, {"event": "progress", "progress": 50, "downloaded_bytes": 1024, "total_bytes": 2048, "stream_label": "Звук"})
    assert task.state == State.DOWNLOADING and task.downloaded_bytes == 1024 and task.progress == 50
    window.toggle_queue()
    assert not window.queue_stack.isHidden() and task.state == State.DOWNLOADING
