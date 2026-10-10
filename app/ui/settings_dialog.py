from dataclasses import asdict

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton, QSpinBox, QVBoxLayout

from app.domain import BITRATES, RESOLUTIONS, Preferences
from app.ui.widgets import label


class SettingsDialog(QDialog):
    def __init__(self, preferences: Preferences, storage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки · СЪЁМ")
        self.setMinimumWidth(560)
        self.storage = storage
        self.original = preferences
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label("ПОД ВАШУ ПАПКУ", "display"))
        layout.addWidget(label("Настройки хранятся рядом с приложением.", "muted"))
        form = QFormLayout()
        form.setSpacing(12)
        folder_row = QHBoxLayout()
        self.folder = QLineEdit(str(storage.folder(preferences.folder)))
        browse = QPushButton("Выбрать")
        browse.clicked.connect(self.browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        form.addRow("Папка загрузок", folder_row)
        self.output = QComboBox()
        for text, value in (("Видео · MP4", "mp4"), ("Аудио · MP3", "mp3"), ("Аудио · M4A", "m4a"), ("Аудио · WAV", "wav")):
            self.output.addItem(text, value)
        self.output.setCurrentIndex(self.output.findData(preferences.output))
        form.addRow("Формат по умолчанию", self.output)
        self.height = QComboBox()
        self.height.addItem("Лучшее доступное", 0)
        for height in RESOLUTIONS:
            self.height.addItem(f"{height}p", height)
        self.height.setCurrentIndex(self.height.findData(preferences.height))
        form.addRow("Качество видео", self.height)
        self.bitrate = QComboBox()
        for bitrate in BITRATES:
            self.bitrate.addItem(f"{bitrate} кбит/с", bitrate)
        self.bitrate.setCurrentIndex(self.bitrate.findData(preferences.bitrate))
        form.addRow("Битрейт MP3", self.bitrate)
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 4)
        self.parallel.setValue(preferences.parallel)
        form.addRow("Одновременных загрузок", self.parallel)
        self.naming = QComboBox()
        for text, value in (("Название видео", "title"), ("Канал — название", "channel"), ("Дата — название", "date")):
            self.naming.addItem(text, value)
        self.naming.setCurrentIndex(self.naming.findData(preferences.naming))
        form.addRow("Имя одиночного файла", self.naming)
        self.existing = QComboBox()
        self.existing.addItem("Пропустить ранее скачанное", "skip")
        self.existing.addItem("Сохранить новую копию", "rename")
        self.existing.setCurrentIndex(self.existing.findData(preferences.existing))
        form.addRow("Если файл уже скачан", self.existing)
        self.playlist_folder = QCheckBox("Создавать папку с названием плейлиста")
        self.playlist_folder.setChecked(preferences.playlist_folder)
        self.compatible = QCheckBox("Совместимое видео · H.264 + AAC")
        self.compatible.setChecked(preferences.compatible)
        form.addRow(self.playlist_folder)
        form.addRow(self.compatible)
        layout.addLayout(form)
        layout.addWidget(label("В плейлистах имена всегда начинаются с номера: 001 - Название.\nЧужие файлы не перезаписываются.", "muted", True))
        controls = QDialogButtonBox()
        controls.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        save = controls.addButton("Сохранить", QDialogButtonBox.ButtonRole.AcceptRole)
        save.setProperty("role", "primary")
        controls.accepted.connect(self.accept)
        controls.rejected.connect(self.reject)
        layout.addWidget(controls)

    def browse(self):
        selected = QFileDialog.getExistingDirectory(self, "Папка загрузок", self.folder.text())
        if selected:
            self.folder.setText(selected)

    def preferences(self) -> Preferences:
        return Preferences.from_dict({**asdict(self.original), "folder": self.storage.folder_value(self.folder.text()) if self.folder.text().strip() else "downloads", "output": self.output.currentData(), "height": self.height.currentData(), "bitrate": self.bitrate.currentData(), "parallel": self.parallel.value(), "playlist_folder": self.playlist_folder.isChecked(), "compatible": self.compatible.isChecked(), "naming": self.naming.currentData(), "existing": self.existing.currentData()})
