from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPalette, QPixmap, QShortcut
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLayout, QLineEdit, QListView, QMainWindow, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter, QStackedWidget, QTableView, QVBoxLayout, QWidget

from app import __version__
from app.domain import ACTIVE, BITRATES, RESOLUTIONS, State, Task, UserError, duration_text, parse_links
from app.process import ManagedProcess
from app.queue import DownloadQueue
from app.storage import Storage, asset_root
from app.ui.settings_dialog import SettingsDialog
from app.ui.widgets import Canvas, Masthead, PlaylistModel, QueueDelegate, QueueModel, label


def button(text, callback=None, role=""):
    widget = QPushButton(text)
    if callback:
        widget.clicked.connect(callback)
    if role:
        widget.setProperty("role", role)
    return widget


class MainWindow(QMainWindow):
    def __init__(self, storage: Storage):
        super().__init__()
        self.storage = storage
        self.prefs = storage.load_preferences()
        self.queue = DownloadQueue(storage, self.prefs.parallel, self)
        self.collections: list[dict] = []
        self.metadata_waiting: list[str] = []
        self.metadata_urls: set[str] = set()
        self.metadata_process = None
        self.current_metadata_url = ""
        self.meta_result = None
        self.meta_cancelled = False
        self.closing = False
        self.setWindowTitle("СЪЁМ · видео и звук")
        self.setWindowIcon(QIcon(str(asset_root() / "icon.svg")))
        self.setMinimumSize(880, 520)
        screen = QApplication.primaryScreen()
        if screen:
            available = screen.availableGeometry()
            self.resize(max(880, min(1080, available.width() - 24)), max(520, min(850, available.height() - 48)))
        else:
            self.resize(1080, 850)
        self.build_ui()
        self.install_shortcuts()
        self.queue.changed.connect(self.queue_summary)
        self.queue.updated.connect(self.queue_summary)
        self.queue.error.connect(self.show_error)
        self.queue_summary()
        for name in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
            if not (storage.root / "bin" / name).is_file():
                QTimer.singleShot(0, lambda: self.show_error("Не хватает инструментов в bin. Запустите build.bat или используйте полную portable-папку."))
                break

    def build_ui(self):
        body = Canvas()
        palette = body.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#F0EDE5"))
        body.setPalette(palette)
        body.setAutoFillBackground(True)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(body)
        self.setCentralWidget(self.scroll)
        layout = QVBoxLayout(body)
        # Let the scroll canvas grow with the styled controls' real minimums.
        # A smaller fixed minimum lets QSplitter overlap its child panels.
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(26, 12, 26, 16)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.addWidget(Masthead(), 1)
        corner = QVBoxLayout()
        corner.addWidget(label("НЕЗАВИСИМАЯ УТИЛИТА  /  " + __version__, "muted"), 0, Qt.AlignmentFlag.AlignRight)
        corner.addWidget(button("Настройки  ↗", self.settings), 0, Qt.AlignmentFlag.AlignRight)
        corner.addStretch()
        header.addLayout(corner)
        layout.addLayout(header)
        input_header = QHBoxLayout()
        input_header.addWidget(label("01  /  ДОБАВЬТЕ ССЫЛКУ", "section"))
        input_header.addStretch()
        input_header.addWidget(label("Видео, Shorts или целый плейлист", "muted"))
        layout.addLayout(input_header)
        link_row = QHBoxLayout()
        link_row.setSpacing(8)
        self.link = QLineEdit()
        self.link.setPlaceholderText("Ссылка YouTube · несколько ссылок через пробел")
        self.link.setAccessibleName("Ссылка YouTube")
        self.link.setMinimumHeight(32)
        self.link.returnPressed.connect(self.add_links)
        self.paste_button = button("Вставить", self.paste, "cyan")
        self.paste_button.setToolTip("Вставить из буфера обмена · Ctrl+Shift+V")
        self.add_button = button("Добавить  +", self.add_links, "primary")
        link_row.addWidget(self.link, 1)
        link_row.addWidget(self.paste_button)
        link_row.addWidget(self.add_button)
        layout.addLayout(link_row)
        message_row = QHBoxLayout()
        self.message = label("Вставьте ссылку — информация загрузится автоматически.", "muted", True)
        message_row.addWidget(self.message, 1)
        self.cancel_metadata = button("Отменить загрузку данных", self.cancel_meta, "plain")
        self.cancel_metadata.hide()
        message_row.addWidget(self.cancel_metadata)
        layout.addLayout(message_row)
        self.detect_timer = QTimer(self)
        self.detect_timer.setSingleShot(True)
        self.detect_timer.setInterval(800)
        self.detect_timer.timeout.connect(self.detect_link)
        self.link.textChanged.connect(lambda: self.detect_timer.start())

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        center = QWidget()
        center.setMinimumHeight(350)
        center_layout = QHBoxLayout(center)
        center_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(16)
        preview_panel = QFrame()
        preview_panel.setProperty("role", "panel")
        pv = QVBoxLayout(preview_panel)
        pv.setContentsMargins(18, 14, 18, 14)
        pv.setSpacing(10)
        preview_header = QHBoxLayout()
        preview_header.addWidget(label("02  /  МАТЕРИАЛ", "section"))
        preview_header.addStretch()
        self.collection_picker = QComboBox()
        self.collection_picker.setMaximumWidth(220)
        self.collection_picker.hide()
        self.collection_picker.currentIndexChanged.connect(self.show_collection)
        preview_header.addWidget(self.collection_picker)
        pv.addLayout(preview_header)
        self.preview_stack = QStackedWidget()
        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.setSpacing(6)
        art = QSvgWidget(str(asset_root() / "record.svg"))
        art.setFixedSize(230, 166)
        empty_layout.addWidget(art, 0, Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(label("ССЫЛКА — И ПОЕХАЛИ.", "display"), 0, Qt.AlignmentFlag.AlignHCenter)
        empty_description = label("Выберите видео или плейлист.\nФайлы останутся в вашей папке.", "muted", True)
        empty_description.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        empty_layout.addWidget(empty_description)
        empty_layout.addStretch(1)
        self.preview_stack.addWidget(empty)
        ready = QWidget()
        ready_layout = QVBoxLayout(ready)
        ready_layout.setContentsMargins(0, 0, 0, 0)
        ready_layout.setSpacing(10)
        info = QHBoxLayout()
        self.thumbnail = QLabel("ПРЕВЬЮ")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setFixedSize(174, 98)
        self.thumbnail.setStyleSheet("background: #A8DFE1; border: 1px solid #171717; font-family: Oswald; font-size: 18px;")
        info.addWidget(self.thumbnail)
        text = QVBoxLayout()
        self.media_type = label("ВИДЕО", "muted")
        self.media_title = label("", "", True)
        self.media_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.media_title.setMaximumHeight(75)
        self.media_channel = label("", "muted", True)
        text.addWidget(self.media_type)
        text.addWidget(self.media_title)
        text.addWidget(self.media_channel)
        text.addStretch()
        info.addLayout(text, 1)
        ready_layout.addLayout(info)
        playlist_actions = QHBoxLayout()
        self.select_all = button("Выбрать всё", lambda: self.playlist_model.select_all(True), "plain")
        self.deselect_all = button("Снять всё", lambda: self.playlist_model.select_all(False), "plain")
        self.selected_label = label("", "muted")
        self.playlist_progress = label("", "muted")
        playlist_actions.addWidget(self.select_all)
        playlist_actions.addWidget(self.deselect_all)
        playlist_actions.addStretch()
        playlist_actions.addWidget(self.selected_label)
        ready_layout.addLayout(playlist_actions)
        ready_layout.addWidget(self.playlist_progress)
        self.playlist_progress.hide()
        self.playlist_model = PlaylistModel(self)
        self.playlist_model.selection_changed.connect(self.selection_changed)
        self.playlist_view = QTableView()
        self.playlist_view.setModel(self.playlist_model)
        self.playlist_view.setAlternatingRowColors(True)
        self.playlist_view.setShowGrid(False)
        self.playlist_view.verticalHeader().hide()
        self.playlist_view.verticalHeader().setDefaultSectionSize(33)
        self.playlist_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.playlist_view.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.playlist_view.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.playlist_view.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.playlist_view.setColumnWidth(0, 30)
        self.playlist_view.setColumnWidth(2, 70)
        self.playlist_view.setMinimumHeight(105)
        ready_layout.addWidget(self.playlist_view, 1)
        self.single_note = label("", "muted", True)
        ready_layout.addWidget(self.single_note)
        ready_layout.addStretch()
        self.preview_stack.addWidget(ready)
        pv.addWidget(self.preview_stack, 1)
        center_layout.addWidget(preview_panel, 3)

        settings_panel = QFrame()
        settings_panel.setProperty("role", "panel")
        settings_panel.setMinimumWidth(300)
        settings_panel.setMaximumWidth(345)
        settings_layout = QVBoxLayout(settings_panel)
        settings_layout.setContentsMargins(18, 14, 18, 16)
        settings_layout.setSpacing(10)
        settings_layout.addWidget(label("03  /  ФОРМАТ", "section"))
        modes = QHBoxLayout()
        modes.setSpacing(0)
        self.video_mode = button("Видео", role="mode")
        self.audio_mode = button("Аудио", role="mode")
        for widget in (self.video_mode, self.audio_mode):
            widget.setCheckable(True)
            modes.addWidget(widget)
        group = QButtonGroup(self)
        group.addButton(self.video_mode)
        group.addButton(self.audio_mode)
        self.video_mode.setChecked(self.prefs.output == "mp4")
        self.audio_mode.setChecked(self.prefs.output != "mp4")
        self.video_mode.clicked.connect(lambda: self.change_mode(True))
        self.audio_mode.clicked.connect(lambda: self.change_mode(False))
        settings_layout.addLayout(modes)
        self.format = QComboBox()
        self.format.setAccessibleName("Выходной формат")
        settings_layout.addWidget(self.format)
        self.quality_label = label("Качество", "muted")
        settings_layout.addWidget(self.quality_label)
        self.quality = QComboBox()
        self.quality.setAccessibleName("Качество видео или битрейт аудио")
        settings_layout.addWidget(self.quality)
        self.compatible = QCheckBox("Совместимый MP4")
        self.compatible.setChecked(self.prefs.compatible)
        self.compatible.setToolTip("H.264 + AAC. Конвертация, если исходные кодеки отличаются.")
        settings_layout.addWidget(self.compatible)
        self.format_note = label("", "muted", True)
        self.format_note.setMinimumHeight(52)
        settings_layout.addWidget(self.format_note)
        settings_layout.addStretch()
        destination_row = QHBoxLayout()
        self.folder_label = label("", "muted")
        self.folder_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.folder_label.setMinimumWidth(40)
        destination_row.addWidget(self.folder_label, 1)
        destination_row.addWidget(button("Изменить", self.choose_folder, "plain"))
        settings_layout.addLayout(destination_row)
        self.download = button("Скачать  ↓", self.start_download, "primary")
        self.download.setMinimumHeight(38)
        self.download.setStyleSheet("font-family: Oswald; font-size: 24px; font-weight: 600;")
        self.download.setEnabled(False)
        settings_layout.addWidget(self.download)
        center_layout.addWidget(settings_panel, 2)
        self.splitter.addWidget(center)

        queue_panel = QWidget()
        queue_panel.setMinimumHeight(118)
        queue_layout = QVBoxLayout(queue_panel)
        queue_layout.setContentsMargins(0, 8, 0, 0)
        queue_layout.setSpacing(8)
        queue_header = QHBoxLayout()
        queue_header.addWidget(label("04  /  ОЧЕРЕДЬ", "section"))
        self.queue_count = label("", "muted")
        queue_header.addWidget(self.queue_count)
        queue_header.addStretch()
        self.retry_button = button("Повторить ошибки", self.queue.retry_failed, "plain")
        self.clear_button = button("Убрать готовые", self.queue.clear_finished, "plain")
        queue_header.addWidget(self.retry_button)
        queue_header.addWidget(self.clear_button)
        queue_layout.addLayout(queue_header)
        self.queue_stack = QStackedWidget()
        queue_empty = QFrame()
        queue_empty.setStyleSheet("background: #E7E4DB; border: 1px dashed #898980;")
        qe = QHBoxLayout(queue_empty)
        qe.addWidget(label("Пока пусто. Добавьте материал и нажмите «Скачать».", "muted"))
        self.queue_stack.addWidget(queue_empty)
        self.queue_view = QListView()
        self.queue_view.setUniformItemSizes(True)
        self.queue_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.queue_model = QueueModel(self.queue, self)
        self.queue_view.setModel(self.queue_model)
        self.queue_delegate = QueueDelegate(self.queue_view)
        self.queue_delegate.action.connect(self.queue_action)
        self.queue_view.setItemDelegate(self.queue_delegate)
        self.queue_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.queue_view.customContextMenuRequested.connect(self.queue_context_menu)
        self.queue_view.activated.connect(lambda idx: self.queue_action(idx.data(Qt.ItemDataRole.UserRole).id))
        self.queue_stack.addWidget(self.queue_view)
        queue_layout.addWidget(self.queue_stack, 1)
        self.splitter.addWidget(queue_panel)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([380, 120])
        layout.addWidget(self.splitter, 1)
        footer = QHBoxLayout()
        self.summary = label("Всё готово к работе", "muted")
        footer.addWidget(self.summary, 1)
        footer.addWidget(button("Открыть папку  ↗", self.open_destination, "plain"))
        footer.addWidget(button("Журнал", lambda: self.open_path(self.storage.data / "logs"), "plain"))
        layout.addLayout(footer)
        self.change_mode(self.prefs.output == "mp4", initial=True)
        self.folder_display()
        self.format.currentIndexChanged.connect(self.format_changed)
        self.quality.currentIndexChanged.connect(self.quality_changed)
        self.compatible.toggled.connect(self.compatibility_changed)

    def install_shortcuts(self):
        for key, callback in (("Ctrl+L", lambda: (self.link.setFocus(), self.link.selectAll())), ("Ctrl+Shift+V", self.paste), ("Ctrl+Return", self.start_download), ("Ctrl+,", self.settings)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)
        self.link.setFocus()

    def save_preferences(self):
        try:
            self.storage.save_preferences(self.prefs)
        except UserError as exc:
            self.show_error(str(exc))

    def paste(self):
        self.link.setText(QApplication.clipboard().text().strip())
        self.link.setFocus()
        self.add_links()

    def detect_link(self):
        try:
            urls = parse_links(self.link.text())
        except UserError:
            return
        if urls:
            self.add_links()

    def add_links(self):
        self.detect_timer.stop()
        try:
            urls = parse_links(self.link.text())
            if not urls:
                raise UserError("Вставьте ссылку на YouTube.")
        except UserError as exc:
            self.show_error(str(exc))
            return
        for url in urls:
            if url in self.metadata_urls:
                for i, collection in enumerate(self.collections):
                    if collection.get("source_url") == url:
                        self.collection_picker.setCurrentIndex(i)
                continue
            self.metadata_urls.add(url)
            self.metadata_waiting.append(url)
        self.next_metadata()

    def next_metadata(self):
        if self.closing or self.metadata_process or not self.metadata_waiting:
            return
        url = self.metadata_waiting.pop(0)
        self.current_metadata_url = url
        self.meta_result = None
        self.meta_cancelled = False
        self.message.setText(f"Получаем информацию… Ссылок в ожидании: {len(self.metadata_waiting)}")
        self.message.setStyleSheet("color: #37666B;")
        self.cancel_metadata.show()
        try:
            self.metadata_process = ManagedProcess(self.storage.root, {"kind": "metadata", "url": url}, self)
        except OSError:
            self.metadata_urls.discard(url)
            self.show_error("Нет доступа к папке приложения для сохранения данных.")
            self.cancel_metadata.hide()
            QTimer.singleShot(0, self.next_metadata)
            return
        self.metadata_process.event.connect(self.metadata_event)
        self.metadata_process.done.connect(self.metadata_done)
        self.metadata_process.start()

    def metadata_event(self, event):
        if self.meta_cancelled:
            return
        if event["event"] == "metadata":
            event["source_url"] = self.current_metadata_url
            self.meta_result = event
            self.collections.append(event)
            self.collection_picker.blockSignals(True)
            self.collection_picker.addItem(event["title"])
            self.collection_picker.setCurrentIndex(len(self.collections) - 1)
            self.collection_picker.blockSignals(False)
            self.collection_picker.setVisible(len(self.collections) > 1)
            self.show_collection(len(self.collections) - 1)
            self.message.setText("Материал добавлен. Выберите формат и нажмите «Скачать».")
            self.message.setStyleSheet("")
        elif event["event"] == "thumbnail" and self.meta_result:
            self.meta_result["thumbnail_path"] = event["path"]
            if self.current_collection() is self.meta_result:
                self.set_thumbnail(event["path"])
        elif event["event"] == "error":
            self.show_error(event["message"])

    def metadata_done(self, code):
        if not self.meta_result:
            self.metadata_urls.discard(self.current_metadata_url)
            if code != 0 and not self.meta_cancelled and not self.message.text().startswith("Ошибка"):
                self.show_error("Не удалось загрузить информацию. Попробуйте повторить; подробности в журнале.")
        process = self.metadata_process
        self.metadata_process = None
        self.cancel_metadata.hide()
        if process:
            process.deleteLater()
        QTimer.singleShot(0, self.next_metadata)

    def cancel_meta(self):
        self.meta_cancelled = True
        self.metadata_waiting.clear()
        self.metadata_urls = {c["source_url"] for c in self.collections}
        if self.metadata_process:
            self.metadata_process.cancel()
        self.message.setText("Загрузка данных отменена. Можно добавить ссылку снова.")

    def current_collection(self):
        index = self.collection_picker.currentIndex()
        return self.collections[index] if 0 <= index < len(self.collections) else None

    def show_collection(self, index):
        if not 0 <= index < len(self.collections):
            return
        collection = self.collections[index]
        self.preview_stack.setCurrentIndex(1)
        playlist = collection["playlist"]
        entries = collection["entries"]
        available = sum(not e.get("unavailable") for e in entries)
        self.media_type.setText(f"ПЛЕЙЛИСТ · {available} из {len(entries)} доступно" if playlist else "ВИДЕО · " + duration_text(entries[0].get("duration") if entries else None))
        self.media_title.setText(collection["title"])
        self.media_title.setToolTip(collection["title"])
        self.media_channel.setText(collection.get("channel") or "YouTube")
        self.set_thumbnail(collection.get("thumbnail_path", ""))
        self.playlist_model.set_entries(entries)
        for widget in (self.playlist_view, self.select_all, self.deselect_all, self.selected_label):
            widget.setVisible(playlist)
        self.single_note.setVisible(not playlist)
        self.single_note.setText("Доступное качество проверено по исходным потокам.\nЗвук и изображение будут объединены в один файл.")
        self.refresh_quality()
        self.selection_changed()
        self.queue_summary()

    def set_thumbnail(self, filename):
        pixmap = QPixmap(filename) if filename else QPixmap()
        if pixmap.isNull():
            self.thumbnail.setPixmap(QPixmap())
            self.thumbnail.setText("ПРЕВЬЮ")
        else:
            self.thumbnail.setPixmap(pixmap.scaled(self.thumbnail.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def selection_changed(self):
        count = len(self.playlist_model.selected)
        self.selected_label.setText(f"Выбрано: {count}")
        collection = self.current_collection()
        self.download.setText(f"Скачать {count}  ↓" if collection and collection["playlist"] else "Скачать  ↓")
        self.update_download_enabled()

    def change_mode(self, video: bool, initial=False):
        previous = self.prefs.output
        self.format.blockSignals(True)
        self.format.clear()
        if video:
            self.format.addItem("MP4 · видео со звуком", "mp4")
        else:
            for text, output in (("MP3 · с конвертацией", "mp3"), ("M4A · исходный звук", "m4a"), ("WAV · без сжатия", "wav")):
                self.format.addItem(text, output)
            self.format.setCurrentIndex(max(0, self.format.findData(previous)))
        self.format.blockSignals(False)
        self.prefs.output = self.format.currentData()
        self.format_changed()
        if not initial:
            self.save_preferences()

    def format_changed(self):
        if self.format.currentData():
            self.prefs.output = self.format.currentData()
        self.compatible.setVisible(self.prefs.output == "mp4")
        self.refresh_quality()

    def refresh_quality(self):
        self.quality.blockSignals(True)
        self.quality.clear()
        output = self.prefs.output
        collection = self.current_collection()
        if output == "mp4":
            self.quality_label.setText("Качество видео")
            self.quality.addItem("Лучшее доступное", 0)
            qualities = RESOLUTIONS if not collection or collection["playlist"] else (collection["entries"][0]["qualities"] if collection["entries"] else [])
            for height in qualities:
                self.quality.addItem(f"{height}p" + (" · проверка каждого" if collection and collection["playlist"] else ""), height)
            if self.prefs.height and self.prefs.height not in qualities:
                self.quality.addItem(f"{self.prefs.height}p · недоступно", self.prefs.height)
            self.quality.setCurrentIndex(max(0, self.quality.findData(self.prefs.height)))
        elif output == "mp3":
            self.quality_label.setText("Битрейт MP3")
            for bitrate in BITRATES:
                self.quality.addItem(f"{bitrate} кбит/с", bitrate)
            self.quality.setCurrentIndex(self.quality.findData(self.prefs.bitrate))
        else:
            self.quality_label.setText("Качество звука")
            self.quality.addItem("Исходный AAC · без конвертации" if output == "m4a" else "PCM · 16 бит", 0)
        self.quality.setEnabled(output in {"mp4", "mp3"})
        self.quality.blockSignals(False)
        self.format_explanation()
        self.update_download_enabled()

    def format_explanation(self):
        output = self.prefs.output
        if output == "mp4":
            text = "H.264 + AAC. Если кодеки отличаются, потребуется конвертация." if self.prefs.compatible else "Быстрый MP4 без перекодирования. AV1/VP9 доступны не на всех устройствах."
            if "недоступно" in self.quality.currentText():
                text = "Этого качества нет в видео. Выберите доступное разрешение."
        elif output == "mp3":
            text = "При необходимости звук извлекается из видео. 320 кбит/с не улучшает источник."
        elif output == "m4a":
            text = "Только исходный AAC. Если такого потока нет, задача сообщит об ошибке."
        else:
            text = "Несжатый звук. Файлы будут заметно больше; качество источника сохраняется."
        self.format_note.setText(text)

    def quality_changed(self):
        if self.prefs.output == "mp4":
            self.prefs.height = self.quality.currentData() or 0
        elif self.prefs.output == "mp3":
            self.prefs.bitrate = self.quality.currentData() or 192
        self.format_explanation()
        self.update_download_enabled()

    def compatibility_changed(self, enabled):
        self.prefs.compatible = enabled
        self.format_explanation()

    def update_download_enabled(self):
        enabled = bool(self.current_collection() and self.playlist_model.selected)
        if self.prefs.output == "mp4" and "недоступно" in self.quality.currentText():
            enabled = False
        collection = self.current_collection()
        if self.prefs.output == "m4a" and collection and not collection["playlist"] and collection["entries"] and not collection["entries"][0].get("m4a"):
            enabled = False
            self.format_note.setText("В этом видео нет исходного M4A. Выберите MP3 или WAV.")
        self.download.setEnabled(enabled)

    def start_download(self):
        collection = self.current_collection()
        if not collection or not self.download.isEnabled():
            return
        try:
            destination = self.storage.folder(self.prefs.folder)
            destination.mkdir(parents=True, exist_ok=True)
            probe = destination / ".syom-write-test"
            probe.write_bytes(b"")
            probe.unlink()
        except OSError:
            self.show_error("Папка загрузок недоступна для записи. Выберите другую папку.")
            return
        options = asdict(self.prefs)
        tasks = [Task(url=e["url"], title=e["title"], options=options.copy(), destination=str(destination), playlist=collection["title"] if collection["playlist"] else "", index=e.get("index", 0)) for e in self.playlist_model.selected_entries()]
        added, duplicates = self.queue.add(tasks)
        self.save_preferences()
        self.message.setText(f"Добавлено в очередь: {added}." + (f" Уже в очереди: {duplicates}." if duplicates else ""))
        self.message.setStyleSheet("")
        if self.queue.tasks:
            self.queue_view.scrollTo(self.queue_model.index(len(self.queue.tasks) - 1))

    def choose_folder(self):
        value = QFileDialog.getExistingDirectory(self, "Папка загрузок", str(self.storage.folder(self.prefs.folder)))
        if value:
            self.prefs.folder = self.storage.folder_value(value)
            self.folder_display()
            self.save_preferences()

    def folder_display(self):
        folder = self.storage.folder(self.prefs.folder)
        self.folder_label.setText("Папка: " + (folder.name or str(folder)))
        self.folder_label.setToolTip(str(folder))

    def settings(self):
        dialog = SettingsDialog(self.prefs, self.storage, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.prefs = dialog.preferences()
            self.queue.parallel = self.prefs.parallel
            self.queue.pump()
            self.compatible.blockSignals(True)
            self.compatible.setChecked(self.prefs.compatible)
            self.compatible.blockSignals(False)
            self.video_mode.setChecked(self.prefs.output == "mp4")
            self.audio_mode.setChecked(self.prefs.output != "mp4")
            self.change_mode(self.prefs.output == "mp4", initial=True)
            self.folder_display()
            self.save_preferences()

    def queue_action(self, identity):
        task = next((t for t in self.queue.tasks if t.id == identity), None)
        if not task:
            return
        if task.state == State.COMPLETED:
            if Path(task.path).is_file():
                self.open_path(Path(task.path).parent)
            else:
                self.show_error("Файл перемещён или удалён. Вы можете скачать его снова.")
        elif task.state in {State.FAILED, State.CANCELLED}:
            self.queue.retry(task)
        else:
            self.queue.cancel(task)

    def queue_context_menu(self, position):
        index = self.queue_view.indexAt(position)
        if not index.isValid():
            return
        task = index.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        menu.addAction("Копировать ссылку", lambda: QApplication.clipboard().setText(task.url))
        if task.state == State.COMPLETED:
            menu.addAction("Открыть файл", lambda: self.open_path(Path(task.path)))
            menu.addAction("Открыть папку", lambda: self.queue_action(task.id))
        elif task.state in {State.FAILED, State.CANCELLED}:
            menu.addAction("Повторить", lambda: self.queue.retry(task))
        else:
            menu.addAction("Отменить", lambda: self.queue.cancel(task))
        if task.error:
            menu.addAction("Показать ошибку", lambda: QMessageBox.information(self, "Не удалось скачать", task.error))
        menu.exec(self.queue_view.viewport().mapToGlobal(position))

    def queue_summary(self, *_):
        tasks = self.queue.tasks
        completed = sum(t.state == State.COMPLETED for t in tasks)
        failed = sum(t.state == State.FAILED for t in tasks)
        active = sum(t.state in ACTIVE for t in tasks)
        waiting = sum(t.state == State.WAITING for t in tasks)
        cancelled = sum(t.state == State.CANCELLED for t in tasks)
        self.queue_count.setText(f"{len(tasks)} файлов" if tasks else "")
        self.queue_stack.setCurrentIndex(1 if tasks else 0)
        self.retry_button.setEnabled(bool(failed))
        self.clear_button.setEnabled(bool(completed))
        self.summary.setText(f"Готово {completed} из {len(tasks)}  ·  Скачивается {active}  ·  Ожидает {waiting}  ·  Ошибок {failed}  ·  Отменено {cancelled}" if tasks else "Без рекламы. Файлы и настройки — у вас.")
        collection = self.current_collection()
        related = [t for t in tasks if collection and collection["playlist"] and t.playlist == collection["title"]]
        self.playlist_progress.setVisible(bool(related))
        if related:
            done = sum(t.state == State.COMPLETED for t in related)
            errors = sum(t.state == State.FAILED for t in related)
            self.playlist_progress.setText(f"Плейлист: готово {done} из {len(related)} · ошибок {errors}")

    def show_error(self, message):
        self.message.setText("Ошибка: " + message)
        self.message.setStyleSheet("color: #A4312D;")
        logging.warning(message)

    def open_path(self, path: Path):
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
            self.show_error("Не удалось открыть файл или папку.")

    def open_destination(self):
        try:
            folder = self.storage.folder(self.prefs.folder)
            folder.mkdir(parents=True, exist_ok=True)
            self.open_path(folder)
        except OSError:
            self.show_error("Папка недоступна. Выберите другое расположение.")

    def closeEvent(self, event):
        self.closing = True
        self.detect_timer.stop()
        self.metadata_waiting.clear()
        if self.metadata_process:
            self.metadata_process.shutdown()
        self.queue.shutdown()
        self.save_preferences()
        event.accept()
