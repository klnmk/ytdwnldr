from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.domain import Preferences, Task, UserError


def application_root() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


def asset_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", application_root())) / "assets"


class Storage:
    def __init__(self, root: Path | None = None):
        self.root = root or application_root()
        self.data = self.root / "data"
        try:
            self.data.mkdir(parents=True, exist_ok=True)
            probe = self.data / ".write-test"
            probe.write_bytes(b"")
            probe.unlink()
            (self.data / "jobs").mkdir(exist_ok=True)
            (self.data / "logs").mkdir(exist_ok=True)
        except OSError as exc:
            raise UserError("Папка приложения недоступна для записи. Переместите всю папку в доступное место и запустите снова.") from exc

    def configure_logging(self) -> None:
        handler = RotatingFileHandler(self.data / "logs" / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s", force=True)

    def read(self, filename: str, fallback):
        try:
            return json.loads((self.data / filename).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return fallback
        except (OSError, ValueError):
            logging.exception("Cannot read %s", filename)
            damaged = self.data / filename
            try:
                damaged.replace(damaged.with_suffix(".damaged.json"))
            except OSError:
                pass
            return fallback

    def write(self, filename: str, value) -> None:
        target = self.data / filename
        temp = target.with_suffix(".tmp")
        try:
            with temp.open("w", encoding="utf-8") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temp.replace(target)
        except OSError as exc:
            raise UserError("Не удалось сохранить данные в папке приложения. Проверьте доступ к записи и место на диске.") from exc

    def load_preferences(self) -> Preferences:
        raw = self.read("settings.json", {})
        return Preferences.from_dict(raw if isinstance(raw, dict) else {})

    def save_preferences(self, prefs: Preferences) -> None:
        self.write("settings.json", asdict(prefs))

    def folder(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else self.root / path

    def folder_value(self, path: str) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.root.resolve()))
        except ValueError:
            return str(Path(path).resolve())

    def load_history(self) -> list[Task]:
        history = self.read("history.json", [])
        if not isinstance(history, list):
            return []
        tasks = []
        for row in history:
            if not isinstance(row, dict):
                continue
            try:
                tasks.append(Task.from_dict(row))
                for attribute in ("destination", "path"):
                    value = getattr(tasks[-1], attribute)
                    if value and not Path(value).is_absolute():
                        setattr(tasks[-1], attribute, str(self.root / value))
            except (ValueError, TypeError, KeyError):
                logging.warning("Invalid history entry")
        return tasks

    def save_history(self, tasks: list[Task]) -> None:
        rows = []
        from app.domain import ACTIVE, State
        recent_terminal = {t.id for t in tasks if t.state not in ACTIVE and t.state != State.WAITING}
        terminal_order = [t.id for t in tasks if t.id in recent_terminal][-300:]
        retain = set(terminal_order)
        for task in tasks:
            if task.state not in ACTIVE and task.state != State.WAITING and task.id not in retain:
                continue
            row = task.to_dict()
            for attribute in ("destination", "path"):
                if row.get(attribute):
                    try:
                        row[attribute] = str(Path(row[attribute]).resolve().relative_to(self.root.resolve()))
                    except ValueError:
                        pass
            rows.append(row)
        self.write("history.json", rows)
