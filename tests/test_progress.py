import pytest

from app.domain import State, Task, byte_text, task_size_text
from app.engine import download_progress


@pytest.mark.parametrize("totals, expected, estimated", [({"total_bytes": 1000, "total_bytes_estimate": 1500}, 1000, False), ({"total_bytes_estimate": 1500}, 1500, True), ({}, None, False)])
def test_transfer_size_uses_exact_estimated_or_unknown(totals, expected, estimated):
    progress = download_progress({"status": "downloading", "downloaded_bytes": 500, "info_dict": {"vcodec": "none", "acodec": "opus"}, **totals})
    assert progress["downloaded_bytes"] == 500
    assert progress["total_bytes"] == expected and progress["total_estimated"] == estimated
    assert progress["stream_label"] == "Звук"
    assert progress["progress"] == (min(99, 500 / expected * 100) if expected else -1)


def test_separate_streams_reset_instead_of_accumulating():
    video = download_progress({"downloaded_bytes": 5000, "total_bytes": 10000, "info_dict": {"vcodec": "h264", "acodec": "none"}})
    audio = download_progress({"downloaded_bytes": 100, "total_bytes": 500, "info_dict": {"vcodec": "none", "acodec": "aac"}})
    assert video["stream_label"] == "Видео" and video["progress"] == 50
    assert audio["stream_label"] == "Звук" and audio["downloaded_bytes"] == 100 and audio["progress"] == 20


@pytest.mark.parametrize("value, text", [(0, "0 Б"), (1024, "1.0 КБ"), (2 * 1024**2, "2.0 МБ"), (3 * 1024**3, "3.0 ГБ")])
def test_byte_units(value, text):
    assert byte_text(value) == text


def test_size_copy_distinguishes_source_estimate_and_final_file():
    task = Task("url", "title", {}, "folder", state=State.DOWNLOADING, downloaded_bytes=1024**2, total_bytes=2 * 1024**2, total_estimated=True, stream_label="Видео", progress=50)
    assert task_size_text(task) == "Видео: 1.0 МБ / ~2.0 МБ · 50%"
    task.total_bytes, task.progress = None, -1
    assert task_size_text(task) == "Видео: 1.0 МБ загружено"
    task.state = State.MERGING
    assert task_size_text(task) == "Источник · Видео: 1.0 МБ"
    task.state, task.final_size = State.COMPLETED, 1024
    assert task_size_text(task) == "Файл: 1.0 КБ"
