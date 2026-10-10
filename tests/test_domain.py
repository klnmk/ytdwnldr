import pytest

from app.domain import Preferences, State, Task, UserError, duration_text, friendly_error, is_playlist, normalize_url, parse_links, sanitize_filename
from app.engine import available_qualities, choose_format, compact_media, file_stem, ydl_options


@pytest.mark.parametrize("url", ["https://youtu.be/BaW_jenozKc?t=10", "youtube.com/watch?v=BaW_jenozKc", "https://m.youtube.com/shorts/BaW_jenozKc", "https://youtube.com/embed/BaW_jenozKc", "https://youtube.com/live/BaW_jenozKc"])
def test_video_recognition(url):
    assert normalize_url(url) == "https://www.youtube.com/watch?v=BaW_jenozKc"


@pytest.mark.parametrize("url", ["", "https://youtube.com.evil.test/watch?v=BaW_jenozKc", "https://example.com", "https://youtube.com/watch?v=x", "https://user:password@youtube.com/watch?v=BaW_jenozKc", "https://youtube.com:999/watch?v=BaW_jenozKc"])
def test_invalid_url(url):
    with pytest.raises(UserError):
        normalize_url(url)


def test_playlist_recognition():
    canonical = normalize_url("https://youtube.com/watch?v=BaW_jenozKc&list=PL12345678&index=2")
    assert canonical == "https://www.youtube.com/playlist?list=PL12345678"
    assert is_playlist(canonical)
    assert not is_playlist(normalize_url("youtu.be/BaW_jenozKc"))


def test_multiple_deduplicated_urls():
    assert len(parse_links("youtu.be/BaW_jenozKc; youtube.com/watch?v=BaW_jenozKc\nhttps://youtube.com/watch?v=jNQXAC9IVRw")) == 2


@pytest.mark.parametrize("source,expected", [("Канал: ночь / музыка?", "Канал_ ночь _ музыка_"), ("CON", "_CON"), ("NUL.txt", "_NUL.txt"), (" .. ", "Без названия"), ("Съём..", "Съём")])
def test_filename_sanitization(source, expected):
    assert sanitize_filename(source) == expected


def test_filename_numbering():
    assert file_stem({"title": "Тест", "channel": "Канал"}, {"naming": "channel"}, 7) == "007 - Тест"
    assert file_stem({"title": "Тест", "channel": "Канал"}, {"naming": "channel"}) == "Канал — Тест"
    assert file_stem({"title": "Тест", "upload_date": "20260101"}, {"naming": "date"}) == "20260101 — Тест"


def test_format_exact_height():
    selector = choose_format("mp4", 1080)
    assert "height=1080" in selector and "height<=" not in selector
    assert all("[height=1080]" in alternative for alternative in selector.split("/"))
    assert "avc1" in choose_format("mp4", 1080, True)
    assert "height=" not in choose_format("mp4")
    assert choose_format("mp3") == "bestaudio/best"
    assert "ext=m4a" in choose_format("m4a")
    with pytest.raises(UserError):
        choose_format("flac")


def test_actual_qualities_only():
    info = {"formats": [{"height": 1080, "vcodec": "avc1", "url": "https://media"}, {"height": 720, "vcodec": "avc1", "has_drm": True, "url": "https://media"}, {"height": 2160, "vcodec": "avc1"}, {"height": 480, "vcodec": "none", "url": "https://media"}]}
    assert available_qualities(info) == [1080]


def test_options_portable(root):
    options = ydl_options(root)
    assert options["ffmpeg_location"] == str(root / "bin")
    assert options["js_runtimes"]["deno"]["path"] == str(root / "bin" / "deno.exe")
    assert options["remote_components"] == []
    assert root in __import__("pathlib").Path(options["cachedir"]).parents


def test_unavailable_entry():
    assert compact_media({"id": "abc", "title": "[Private video]"})["unavailable"]
    assert compact_media({})["unavailable"]
    assert not compact_media({"id": "abc", "title": "Видео"})["unavailable"]


@pytest.mark.parametrize("error,word", [("Private video", "входа"), ("HTTP Error 403", "подключение"), ("no space left", "места"), ("ffmpeg failed", "FFmpeg"), ("unexpected exception", "журнале")])
def test_error_translation(error, word):
    assert word in friendly_error(error)


def test_preferences_validation():
    prefs = Preferences.from_dict({"parallel": 20, "height": 999, "bitrate": "bad", "output": "evil", "compatible": "yes", "unknown": True})
    assert prefs.parallel == 4 and prefs.height == 0 and prefs.bitrate == 192
    assert prefs.output == "mp4" and prefs.compatible is False


def test_interrupted_task_recovery():
    task = Task("url", "title", {}, "folder", state=State.CONVERTING)
    assert Task.from_dict(task.to_dict()).state == State.CANCELLED


def test_duration():
    assert duration_text(3661) == "1:01:01"
    assert duration_text(61) == "1:01"
