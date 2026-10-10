import json

from app.domain import UserError
from app.storage import Storage
from app.worker import run_worker


def test_worker_protocol_preserves_cyrillic_with_ascii_json(tmp_path, monkeypatch, capsys):
    storage = Storage(tmp_path)
    job = storage.data / "jobs" / "test.json"
    job.write_text(json.dumps({"root": str(tmp_path), "kind": "metadata", "url": "url"}), encoding="utf-8")
    def fake(root, url, emit):
        emit("metadata", title="Съём — музыка", path="C:/Музыка/Запись.mp3")
    monkeypatch.setattr("app.engine.extract_metadata", fake)
    assert run_worker(str(job)) == 0
    output = capsys.readouterr().out
    assert output.isascii()
    event = json.loads(output)
    assert event["title"] == "Съём — музыка" and event["path"] == "C:/Музыка/Запись.mp3"


def test_worker_failure_is_russian_and_not_a_traceback(tmp_path, monkeypatch, capsys):
    storage = Storage(tmp_path)
    job = storage.data / "jobs" / "test.json"
    job.write_text(json.dumps({"root": str(tmp_path), "kind": "metadata", "url": "url"}), encoding="utf-8")
    def fake(*args):
        raise UserError("Видео недоступно.")
    monkeypatch.setattr("app.engine.extract_metadata", fake)
    assert run_worker(str(job)) == 1
    event = json.loads(capsys.readouterr().out)
    assert event == {"event": "error", "message": "Видео недоступно."}
