from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4


class UserError(Exception):
    """A message safe to display in the Russian interface."""


class State(StrEnum):
    WAITING = "В очереди"
    METADATA = "Получение данных"
    DOWNLOADING = "Скачивание"
    MERGING = "Объединение"
    CONVERTING = "Конвертация"
    COMPLETED = "Готово"
    FAILED = "Ошибка"
    CANCELLED = "Отменено"


ACTIVE = {State.METADATA, State.DOWNLOADING, State.MERGING, State.CONVERTING}
TERMINAL = {State.COMPLETED, State.FAILED, State.CANCELLED}
RESOLUTIONS = (360, 480, 720, 1080, 1440, 2160)
BITRATES = (128, 192, 256, 320)


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise UserError("Вставьте ссылку на видео или плейлист YouTube.")
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value
    try:
        url = urlparse(value)
        if url.username or url.password or url.port not in (None, 443, 80):
            raise ValueError
    except ValueError:
        raise UserError("Некорректная ссылка YouTube.") from None
    host = (url.hostname or "").lower()
    query = parse_qs(url.query)
    if host == "youtu.be":
        video_id = url.path.strip("/").split("/")[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "www.youtube-nocookie.com", "youtube-nocookie.com"}:
        if url.path in ("/watch", "/playlist") and query.get("list"):
            playlist_id = query["list"][0]
            if not re.fullmatch(r"[A-Za-z0-9_-]{2,150}", playlist_id):
                raise UserError("Некорректный идентификатор плейлиста.")
            return "https://www.youtube.com/playlist?list=" + playlist_id
        video_id = query.get("v", [""])[0] if url.path == "/watch" else ""
        if url.path.startswith(("/shorts/", "/embed/", "/live/")):
            video_id = url.path.split("/")[2]
    else:
        raise UserError("Нужна ссылка с youtube.com или youtu.be.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise UserError("В ссылке нет корректного идентификатора видео.")
    return "https://www.youtube.com/watch?v=" + video_id


def parse_links(text: str) -> list[str]:
    parts = re.split(r"[\s,;]+", text.strip())
    return list(dict.fromkeys(normalize_url(p) for p in parts if p))


def is_playlist(url: str) -> bool:
    return bool(parse_qs(urlparse(url).query).get("list"))


def sanitize_filename(value: str, limit: int = 110) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    clean = re.sub(r"\s+", " ", clean).strip(" .")[:limit].rstrip(" .") or "Без названия"
    if re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", clean, re.I):
        clean = "_" + clean
    return clean


def duration_text(seconds: int | float | None) -> str:
    if not seconds:
        return "—"
    total = int(seconds)
    if total >= 3600:
        return f"{total // 3600}:{total % 3600 // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


def byte_text(value: int | float) -> str:
    size = max(0, value)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024 or unit == "ТБ":
            return f"{int(size)} {unit}" if unit == "Б" else f"{size:.1f} {unit}"
        size /= 1024


def task_size_text(task: Task) -> str:
    if task.state == State.COMPLETED:
        return "Файл: " + byte_text(task.final_size) if task.final_size is not None else "Размер файла неизвестен"
    if task.state not in ACTIVE or not task.stream_label:
        return ""
    prefix = task.stream_label + ": "
    text = prefix + byte_text(task.downloaded_bytes)
    if task.state == State.DOWNLOADING:
        if task.total_bytes is not None:
            text += " / " + ("~" if task.total_estimated else "") + byte_text(task.total_bytes)
        else:
            text += " загружено"
        if task.progress >= 0:
            text += f" · {int(task.progress)}%"
    else:
        text = "Источник · " + text
    return text


def friendly_error(message: str) -> str:
    lower = message.lower()
    for patterns, russian in [
        (("requested format", "format is not available"), "Выбранное качество недоступно. Выберите другое качество."),
        (("private video", "sign in", "login required", "age-restricted"), "YouTube требует входа в аккаунт. Доступ к этому видео недоступен."),
        (("removed", "not available", "unavailable", "video has been"), "Видео удалено или недоступно."),
        (("timed out", "timeout"), "YouTube не ответил вовремя. Попробуйте ещё раз."),
        (("unable to download", "network", "getaddrinfo", "connection", "http error"), "Не удалось получить данные. Проверьте подключение и повторите."),
        (("no space", "disk full", "winerror 112"), "На диске недостаточно свободного места."),
        (("permission", "access is denied", "winerror 5"), "Нет доступа к папке. Выберите доступную папку для загрузки."),
        (("ffmpeg", "ffprobe"), "Ошибка обработки медиа. Проверьте файлы FFmpeg в папке bin."),
        (("drm",), "Видео защищено DRM и не может быть скачано."),
    ]:
        if any(p in lower for p in patterns):
            return russian
    return "Не удалось скачать видео. Подробности сохранены в журнале; попробуйте повторить."


@dataclass
class Preferences:
    folder: str = "downloads"
    output: str = "mp4"
    height: int = 0
    bitrate: int = 192
    compatible: bool = False
    parallel: int = 2
    playlist_folder: bool = True
    naming: str = "title"
    existing: str = "skip"
    queue_height: int = 160
    queue_collapsed: bool = False

    @classmethod
    def from_dict(cls, raw: dict) -> Preferences:
        values = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        obj = cls(**values)
        obj.folder = obj.folder if isinstance(obj.folder, str) and obj.folder.strip() else "downloads"
        obj.output = obj.output if obj.output in {"mp4", "mp3", "m4a", "wav"} else "mp4"
        obj.height = obj.height if type(obj.height) is int and obj.height in (0, *RESOLUTIONS) else 0
        obj.bitrate = obj.bitrate if type(obj.bitrate) is int and obj.bitrate in BITRATES else 192
        obj.parallel = min(4, max(1, obj.parallel)) if type(obj.parallel) is int else 2
        obj.naming = obj.naming if obj.naming in {"title", "channel", "date"} else "title"
        obj.existing = obj.existing if obj.existing in {"skip", "rename"} else "skip"
        obj.compatible = obj.compatible if isinstance(obj.compatible, bool) else False
        obj.playlist_folder = obj.playlist_folder if isinstance(obj.playlist_folder, bool) else True
        obj.queue_height = min(1200, max(120, obj.queue_height)) if type(obj.queue_height) is int else 160
        obj.queue_collapsed = obj.queue_collapsed if isinstance(obj.queue_collapsed, bool) else False
        return obj


@dataclass
class Task:
    url: str
    title: str
    options: dict
    destination: str
    playlist: str = ""
    index: int = 0
    id: str = field(default_factory=lambda: uuid4().hex)
    state: State = State.WAITING
    progress: float = 0
    speed: float = 0
    eta: int | None = None
    error: str = ""
    path: str = ""
    note: str = ""
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    total_estimated: bool = False
    stream_label: str = ""
    final_size: int | None = None

    @property
    def duplicate_key(self) -> tuple:
        return (self.url, self.options.get("output"), self.options.get("height"), self.options.get("bitrate"), self.options.get("compatible"), str(Path(self.destination).resolve()).casefold(), self.playlist, self.index)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["state"] = self.state.value
        return data

    @classmethod
    def from_dict(cls, raw: dict) -> Task:
        task = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
        task.state = State(task.state)
        if task.state in ACTIVE or task.state == State.WAITING:
            task.state = State.CANCELLED
            task.note = "Прервано при закрытии. Нажмите «Повторить»."
        return task
