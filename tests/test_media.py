import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.domain import UserError
from app.engine import convert, embed_cover, execute_download, probe, reserve_file

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@pytest.fixture(scope="module")
def source(root, tmp_path_factory):
    ffmpeg = root / "bin" / "ffmpeg.exe"
    if not ffmpeg.exists():
        pytest.skip("Bundled FFmpeg not downloaded yet")
    path = tmp_path_factory.mktemp("media") / "generated.webm"
    subprocess.run([str(ffmpeg), "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=256x144:rate=24", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "1", "-c:v", "libvpx-vp9", "-c:a", "libopus", str(path)], check=True, capture_output=True, creationflags=NO_WINDOW)
    return path


@pytest.mark.integration
@pytest.mark.parametrize("bitrate", [128, 192, 256, 320])
def test_real_mp3_conversion(root, source, tmp_path, bitrate):
    target = tmp_path / "Тест.mp3"
    convert(root, source, target, {"title": "Тест", "channel": "Автор"}, {"output": "mp3", "bitrate": bitrate}, lambda *a, **k: None)
    result = probe(root, target)
    audio = result["streams"][0]
    assert audio["codec_name"] == "mp3" and int(audio["bit_rate"]) == bitrate * 1000
    assert result["format"]["tags"]["title"] == "Тест"


@pytest.mark.integration
@pytest.mark.parametrize("compatible", [False, True])
def test_real_mp4_sound_size_and_framerate(root, source, tmp_path, compatible):
    target = tmp_path / "Тест.mp4"
    convert(root, source, target, {}, {"output": "mp4", "compatible": compatible}, lambda *a, **k: None)
    streams = probe(root, target)["streams"]
    video = next(s for s in streams if s["codec_type"] == "video")
    audio = next(s for s in streams if s["codec_type"] == "audio")
    assert video["width"] == 256 and video["height"] == 144 and video["r_frame_rate"] == "24/1"
    assert video["codec_name"] == ("h264" if compatible else "vp9")
    assert audio["codec_name"] == ("aac" if compatible else "opus")


@pytest.mark.integration
def test_wav(root, source, tmp_path):
    target = tmp_path / "Тест.wav"
    convert(root, source, target, {}, {"output": "wav"}, lambda *a, **k: None)
    assert probe(root, target)["streams"][0]["codec_name"] == "pcm_s16le"


@pytest.mark.integration
def test_real_m4a_remux_and_tags(root, source, tmp_path):
    aac = tmp_path / "source.m4a"
    subprocess.run([str(root / "bin" / "ffmpeg.exe"), "-v", "error", "-i", str(source), "-vn", "-c:a", "aac", str(aac)], check=True, capture_output=True, creationflags=NO_WINDOW)
    target = tmp_path / "Тест.m4a"
    convert(root, aac, target, {"title": "Название", "channel": "Автор"}, {"output": "m4a"}, lambda *a, **k: None)
    media = probe(root, target)
    assert media["streams"][0]["codec_name"] == "aac"
    assert media["format"]["tags"]["title"] == "Название"
    assert media["format"]["tags"]["artist"] == "Автор"


def test_collision_does_not_overwrite(tmp_path):
    (tmp_path / "Файл.mp3").write_bytes(b"original")
    with reserve_file(tmp_path, "Файл", "mp3", "fingerprint", "skip") as (target, receipt, skip):
        assert target.name == "Файл (2).mp3" and not skip
    assert (tmp_path / "Файл.mp3").read_bytes() == b"original"


def test_existing_receipt_skip(tmp_path):
    with reserve_file(tmp_path, "Файл", "mp3", "fingerprint", "skip") as (target, receipt, skip):
        target.write_bytes(b"media")
        receipt.write_text(json.dumps({"fingerprint": "fingerprint"}), encoding="utf-8")
    with reserve_file(tmp_path, "Файл", "mp3", "fingerprint", "skip") as (target, receipt, skip):
        assert skip and target.name == "Файл.mp3"


def test_partial_cover_tag_failure_preserves_original_media(tmp_path, monkeypatch):
    target = tmp_path / "finished.mp3"
    original = b"successfully converted audio"
    target.write_bytes(original)
    cover = tmp_path / "image.jpg"
    cover.write_bytes(b"cover")
    monkeypatch.setattr("app.engine.thumbnail", lambda *args: str(cover))
    monkeypatch.setattr("app.engine.run_ffmpeg", lambda root, args, emit: Path(args[-1]).write_bytes(b"jpeg"))
    import mutagen.id3
    class BrokenTags:
        def __init__(self, path):
            self.path = Path(path)
        def add(self, tag):
            pass
        def save(self, path):
            Path(path).write_bytes(b"partially corrupted tag write")
            raise OSError("Simulated metadata write failure")
    monkeypatch.setattr(mutagen.id3, "ID3", BrokenTags)
    notes = []
    warning = embed_cover(tmp_path, target, {"thumbnail": "https://image"}, lambda kind, **values: notes.append(values))
    assert target.read_bytes() == original
    assert "обложку" in warning and notes
    assert not (tmp_path / "finished.tags.mp3").exists()


@pytest.mark.integration
@pytest.mark.parametrize("output", ["mp3", "m4a"])
def test_real_cover_transaction(root, source, tmp_path, monkeypatch, output):
    image = tmp_path / "art.jpg"
    ffmpeg = str(root / "bin" / "ffmpeg.exe")
    subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=32x32", "-frames:v", "1", str(image)], check=True, capture_output=True, creationflags=NO_WINDOW)
    input_media = source
    if output == "m4a":
        input_media = tmp_path / "aac.m4a"
        subprocess.run([ffmpeg, "-v", "error", "-i", str(source), "-vn", "-c:a", "aac", str(input_media)], check=True, capture_output=True, creationflags=NO_WINDOW)
    target = tmp_path / ("finished." + output)
    convert(root, input_media, target, {"title": "Тест", "channel": "Автор"}, {"output": output, "bitrate": 192}, lambda *a, **k: None)
    monkeypatch.setattr("app.engine.thumbnail", lambda *args: str(image))
    assert embed_cover(root, target, {"thumbnail": "https://unused"}, lambda *a, **k: None) == ""
    streams = probe(root, target)["streams"]
    assert any(s.get("disposition", {}).get("attached_pic") == 1 for s in streams)
    assert any(s.get("codec_name") == ("mp3" if output == "mp3" else "aac") for s in streams)


@pytest.mark.integration
def test_full_engine_with_generated_media(root, source, tmp_path, monkeypatch):
    import shutil
    import yt_dlp
    class YDL:
        def __init__(self, options):
            self.options = options
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def extract_info(self, url, download=False, process=False):
            assert process is False, "Download planning must not inherit a preselected video result"
            return {"id": "BaW_jenozKc", "title": "Авторский тест", "duration": 1, "formats": [{"height": 1080, "vcodec": "vp9", "url": "https://fake"}]}
        def process_ie_result(self, info, download=True):
            path = Path(self.options["outtmpl"].replace("%(ext)s", "webm"))
            shutil.copy2(source, path)
            return {**info, "filepath": str(path)}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", YDL)
    events = []
    task = {"id": "generated-test", "url": "https://www.youtube.com/watch?v=BaW_jenozKc", "options": {"output": "mp3", "bitrate": 192}, "destination": str(tmp_path), "playlist": "Плейлист", "index": 3}
    execute_download(root, task, lambda kind, **values: events.append({"event": kind, **values}))
    completed = [e for e in events if e["event"] == "completed"]
    assert len(completed) == 1 and Path(completed[0]["path"]).name == "003 - Авторский тест.mp3"
    assert probe(root, Path(completed[0]["path"]))["streams"][0]["codec_name"] == "mp3"
    events.clear()
    execute_download(root, task, lambda kind, **values: events.append({"event": kind, **values}))
    assert "пропущено" in events[-1]["note"]
    task["options"].update(output="mp4", height=720)
    with pytest.raises(UserError, match="720p недоступно"):
        execute_download(root, task, lambda *a, **k: None)


@pytest.mark.integration
@pytest.mark.skipif(os.name != "nt", reason="Windows process tree")
def test_job_cancellation_kills_descendants(tmp_path):
    import psutil
    from app.process import ProcessTree
    child_file = tmp_path / "child.pid"
    code = "import sys,subprocess,time; sys.stdin.readline(); child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); open(sys.argv[1],'w').write(str(child.pid)); time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", code, str(child_file)], stdin=subprocess.PIPE, creationflags=NO_WINDOW)
    tree = ProcessTree(process.pid)
    try:
        assert tree.handle, "Job assignment failed"
        process.stdin.write(b"go\n")
        process.stdin.flush()
        deadline = time.monotonic() + 5
        while not child_file.exists() and time.monotonic() < deadline:
            time.sleep(0.03)
        child_id = int(child_file.read_text())
        tree.close()
        process.wait(timeout=5)
        deadline = time.monotonic() + 3
        while psutil.pid_exists(child_id) and time.monotonic() < deadline:
            time.sleep(0.03)
        assert not psutil.pid_exists(child_id)
    finally:
        tree.close()
        if process.poll() is None:
            process.kill()


@pytest.mark.integration
def test_cancel_worker_during_startup(qt, root):
    from app.process import ManagedProcess
    from app.storage import Storage
    Storage(root)
    process = ManagedProcess(root, {"kind": "metadata", "url": "invalid URL; must never reach extraction"})
    events = []
    process.event.connect(events.append)
    process.start()
    process.cancel()
    assert process.process.waitForFinished(5000)
    qt.processEvents()
    assert process._cancel_requested and not events
    assert not process.job_file.exists()
