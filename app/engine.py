from __future__ import annotations

import hashlib
import copy
import json
import logging
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable
from urllib.request import Request, urlopen

from app.domain import RESOLUTIONS, State, UserError, sanitize_filename

Emit = Callable[..., None]
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def available_qualities(info: dict) -> list[int]:
    heights = {int(f.get("height") or 0) for f in info.get("formats", []) if f.get("vcodec") != "none" and not f.get("has_drm") and f.get("url")}
    return [h for h in RESOLUTIONS if h in heights]


def choose_format(output: str, height: int = 0, compatible: bool = False) -> str:
    if output == "m4a":
        return "ba[ext=m4a]/b[ext=mp4][vcodec=none]"
    if output in {"mp3", "wav"}:
        return "bestaudio/best"
    if output != "mp4":
        raise UserError("Этот формат не поддерживается.")
    size = f"[height={height}]" if height else ""
    # Prefer H.264 for compatibility; falling back preserves the exact resolution.
    first = f"bv*{size}[vcodec^=avc1]+ba[ext=m4a]/b{size}[vcodec^=avc1]/" if compatible else ""
    return first + f"bv*{size}[ext=mp4]+ba[ext=m4a]/b{size}[ext=mp4]/bv*{size}+ba/b{size}"


def ydl_options(root: Path, logger=None) -> dict:
    return {
        "quiet": True, "no_warnings": False, "logger": logger,
        "ffmpeg_location": str(root / "bin"),
        "js_runtimes": {"deno": {"path": str(root / "bin" / "deno.exe")}},
        "cachedir": str(root / "data" / "cache" / "yt-dlp"),
        "socket_timeout": 25, "retries": 3, "fragment_retries": 3,
        "windowsfilenames": True, "noprogress": True,
        "ignoreconfig": True, "remote_components": [],
    }


class YdlLogger:
    def debug(self, message):
        logging.info(message)

    def warning(self, message):
        logging.warning(message)

    def error(self, message):
        logging.error(message)


def compact_media(info: dict, index: int = 0) -> dict:
    identity = info.get("id", "")
    title = info.get("title") or "Недоступное видео"
    unavailable = not identity or title in {"[Deleted video]", "[Private video]"} or info.get("availability") in {"private", "premium_only", "subscriber_only", "needs_auth"}
    return {
        "id": identity, "title": title,
        "url": f"https://www.youtube.com/watch?v={identity}" if identity else "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "duration": info.get("duration"), "index": index,
        "unavailable": unavailable, "thumbnail": info.get("thumbnail") or "",
        "qualities": available_qualities(info),
        "m4a": any(f.get("ext") == "m4a" and not f.get("has_drm") for f in info.get("formats", [])),
    }


def thumbnail(root: Path, url: str, identity: str) -> str:
    if not url.startswith("https://"):
        return ""
    try:
        cache = root / "data" / "cache" / "thumbnails"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / (hashlib.sha256(identity.encode()).hexdigest()[:24] + ".jpg")
        with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=10) as response:
            content = response.read(2_000_001)
        if len(content) > 2_000_000:
            return ""
        target.write_bytes(content)
        return str(target)
    except Exception:
        logging.warning("Thumbnail unavailable", exc_info=True)
        return ""


def extract_metadata(root: Path, url: str, emit: Emit) -> None:
    from yt_dlp import YoutubeDL

    options = ydl_options(root, YdlLogger())
    options.update({"extract_flat": "in_playlist", "ignoreerrors": True, "skip_download": True})
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise UserError("Видео или плейлист недоступны.")
    playlist = info.get("_type") in {"playlist", "multi_video"}
    entries = list(info.get("entries") or []) if playlist else [info]
    media = [compact_media(item or {}, index + 1 if playlist else 0) for index, item in enumerate(entries)]
    emit("metadata", title=info.get("title") or "Без названия", channel=info.get("channel") or info.get("uploader") or "", playlist=playlist, entries=media)
    thumb_url = info.get("thumbnail") or (media[0].get("thumbnail") if media else "")
    if not thumb_url and playlist and media and media[0].get("id"):
        thumb_url = f"https://i.ytimg.com/vi/{media[0]['id']}/hqdefault.jpg"
    local = thumbnail(root, thumb_url or "", info.get("id") or url)
    if local:
        emit("thumbnail", path=local)


def file_stem(info: dict, options: dict, index: int = 0) -> str:
    title = sanitize_filename(info.get("title") or "Без названия")
    if index:
        return f"{index:03d} - {title}"
    if options.get("naming") == "channel":
        return sanitize_filename((info.get("channel") or info.get("uploader") or "Канал") + " — " + title)
    if options.get("naming") == "date":
        date = info.get("upload_date") or "без даты"
        return sanitize_filename(f"{date} — {title}")
    return title


def run_ffmpeg(root: Path, arguments: list[str], emit: Emit, duration: float = 0) -> None:
    command = [str(root / "bin" / "ffmpeg.exe"), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *arguments]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    # Drain stderr concurrently: FFmpeg can produce long failure logs.
    import threading
    errors: list[str] = []

    def drain():
        for line in process.stderr:
            errors.append(line)
            if len(errors) > 100:
                errors.pop(0)

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    for line in process.stdout:
        if line.startswith("out_time_us=") and duration:
            try:
                percent = min(99, int(line.split("=", 1)[1]) / 1_000_000 / duration * 100)
                emit("progress", progress=percent, speed=0, eta=None)
            except ValueError:
                pass
    returncode = process.wait()
    reader.join(timeout=2)
    if returncode:
        raise RuntimeError("FFmpeg: " + "".join(errors)[-6000:])


def probe(root: Path, media: Path) -> dict:
    completed = subprocess.run([str(root / "bin" / "ffprobe.exe"), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media)], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=NO_WINDOW)
    if completed.returncode:
        raise RuntimeError("ffprobe: " + completed.stderr)
    return json.loads(completed.stdout)


def convert(root: Path, source: Path, target: Path, info: dict, options: dict, emit: Emit) -> None:
    output = options["output"]
    media = probe(root, source)
    streams = media.get("streams", [])
    duration = float(media.get("format", {}).get("duration") or info.get("duration") or 0)
    if output == "mp4":
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        if not video or not audio:
            raise UserError("В исходном видео отсутствует изображение или звук.")
        encode_video = video.get("codec_name") != "h264" or video.get("pix_fmt") not in {"yuv420p", "yuvj420p"}
        if options.get("compatible") and (encode_video or audio.get("codec_name") != "aac"):
            emit("state", state=State.CONVERTING.value, note="H.264 + AAC · без изменения размера")
            run_ffmpeg(root, ["-i", str(source), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "libx264" if encode_video else "copy", *(["-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"] if encode_video else []), "-c:a", "copy" if audio.get("codec_name") == "aac" else "aac", "-movflags", "+faststart", str(target)], emit, duration)
        else:
            emit("state", state=State.MERGING.value, note="MP4 · без перекодирования")
            run_ffmpeg(root, ["-i", str(source), "-map", "0:v:0", "-map", "0:a:0", "-c", "copy", "-movflags", "+faststart", str(target)], emit, duration)
    elif output == "m4a":
        emit("state", state=State.MERGING.value, note="M4A · исходный звук")
        run_ffmpeg(root, ["-i", str(source), "-vn", "-c:a", "copy", "-metadata", "title=" + str(info.get("title") or ""), "-metadata", "artist=" + str(info.get("artist") or info.get("channel") or info.get("uploader") or ""), str(target)], emit, duration)
    else:
        emit("state", state=State.CONVERTING.value, note=f"{output.upper()} · обработка звука")
        codec = ["-c:a", "libmp3lame", "-b:a", f"{options['bitrate']}k"] if output == "mp3" else ["-c:a", "pcm_s16le"]
        run_ffmpeg(root, ["-i", str(source), "-vn", *codec, "-metadata", "title=" + str(info.get("title") or ""), "-metadata", "artist=" + str(info.get("artist") or info.get("channel") or info.get("uploader") or ""), str(target)], emit, duration)
    if not target.exists() or target.stat().st_size == 0:
        raise UserError("Обработка завершилась без выходного файла.")
    probe(root, target)


def embed_cover(root: Path, target: Path, info: dict, emit: Emit) -> str:
    if target.suffix not in {".mp3", ".m4a"}:
        return ""
    tagged = target.with_name(target.stem + ".tags" + target.suffix)
    try:
        image = thumbnail(root, info.get("thumbnail") or "", info.get("id") or target.name)
        if not image:
            return ""
        jpeg = target.parent / "cover.jpg"
        run_ffmpeg(root, ["-i", image, "-frames:v", "1", str(jpeg)], lambda *a, **k: None)
        # Tag a copy: a failed in-place metadata save must preserve the media.
        shutil.copy2(target, tagged)
        if target.suffix == ".mp3":
            from mutagen.id3 import APIC, ID3
            tags = ID3(tagged)
            tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpeg.read_bytes()))
            tags.save(tagged)
        else:
            from mutagen.mp4 import MP4, MP4Cover
            tags = MP4(tagged)
            tags["covr"] = [MP4Cover(jpeg.read_bytes(), imageformat=MP4Cover.FORMAT_JPEG)]
            tags.save()
        probe(root, tagged)
        tagged.replace(target)
    except Exception:
        logging.warning("Cover art could not be embedded; media preserved", exc_info=True)
        message = "Файл готов; обложку добавить не удалось."
        emit("note", note=message)
        return message
    finally:
        try:
            tagged.unlink(missing_ok=True)
        except OSError:
            logging.warning("Could not remove temporary tag copy", exc_info=True)
    return ""


@contextmanager
def reserve_file(folder: Path, stem: str, extension: str, fingerprint: str, existing: str):
    """OS locks release on process termination, including forced cancellation."""
    index_dir = folder / ".syom"
    index_dir.mkdir(exist_ok=True)
    for number in range(1, 10000):
        filename = f"{stem}{'' if number == 1 else f' ({number})'}.{extension}"
        lock_id = hashlib.sha256(filename.casefold().encode()).hexdigest()
        lock = (index_dir / (lock_id + ".lock")).open("a+b")
        lock.seek(0)
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock.close()
            continue
        receipt = index_dir / (lock_id + ".json")
        target = folder / filename
        matches = False
        try:
            matches = json.loads(receipt.read_text(encoding="utf-8")).get("fingerprint") == fingerprint
        except (OSError, ValueError):
            pass
        if target.exists() and not (existing == "skip" and matches):
            lock.close()
            continue
        try:
            yield target, receipt, target.exists() and matches
        finally:
            lock.close()
        return
    raise UserError("Не удалось выбрать свободное имя файла.")


def download_progress(data: dict) -> dict:
    """Report the current transfer only; never add audio and video totals."""
    downloaded = max(0, int(data.get("downloaded_bytes") or 0))
    exact = data.get("total_bytes")
    estimate = data.get("total_bytes_estimate")
    total = int(exact or estimate) if exact or estimate else None
    info = data.get("info_dict") or {}
    video = info.get("vcodec") not in (None, "none")
    audio = info.get("acodec") not in (None, "none")
    stream = "Видео + звук" if video and audio else "Видео" if video else "Звук" if audio else "Поток"
    percent = min(99, downloaded / total * 100) if total else -1
    if data.get("status") == "finished":
        percent = 100
    return {"progress": percent, "speed": data.get("speed") or 0, "eta": data.get("eta"), "downloaded_bytes": downloaded, "total_bytes": total, "total_estimated": not bool(exact) and bool(estimate), "stream_label": stream}


def execute_download(root: Path, task: dict, emit: Emit) -> None:
    from yt_dlp import YoutubeDL

    options = task["options"]
    output = options["output"]
    height = int(options.get("height") or 0)
    bitrate = int(options.get("bitrate") or 192)
    if output not in {"mp4", "mp3", "m4a", "wav"} or bitrate not in {128, 192, 256, 320} or height not in (0, *RESOLUTIONS):
        raise UserError("Некорректные настройки формата или качества.")
    for binary in ("ffmpeg.exe", "ffprobe.exe", "deno.exe"):
        if not (root / "bin" / binary).is_file():
            raise UserError(f"Не найден bin/{binary}. Скопируйте полную папку приложения.")
    folder = Path(task["destination"])
    if task.get("playlist") and options.get("playlist_folder", True):
        folder /= sanitize_filename(task["playlist"], 70)
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < 64 * 1024 * 1024:
        raise UserError("На диске недостаточно свободного места.")
    emit("state", state=State.METADATA.value)
    base = ydl_options(root, YdlLogger())
    base["noplaylist"] = True
    with YoutubeDL(base) as metadata_ydl:
        # Keep extraction unprocessed. Reusing a preselected video result for an
        # audio-only job leaves inherited video headers/fields on that result.
        info = metadata_ydl.extract_info(task["url"], download=False, process=False)
        cookies = getattr(metadata_ydl, "cookiejar", None)
    if not info or info.get("is_live"):
        raise UserError("Прямой эфир пока не завершён. Добавьте запись после окончания трансляции.")
    if output == "mp4" and height and height not in available_qualities(info):
        available = ", ".join(f"{h}p" for h in available_qualities(info)) or "только лучшее доступное"
        raise UserError(f"Качество {height}p недоступно. Доступно: {available}. Выберите другое качество и добавьте заново.")
    stem = file_stem(info, options, task.get("index", 0))
    fingerprint = hashlib.sha256(json.dumps([task["url"], output, height, bitrate if output == "mp3" else 0, options.get("compatible", False)], sort_keys=True).encode()).hexdigest()
    with reserve_file(folder, stem, output, fingerprint, options.get("existing", "skip")) as (target, receipt, skip):
        if skip:
            emit("completed", path=str(target), note="Уже скачано · пропущено", final_size=target.stat().st_size)
            return
        stage = folder / ".syom" / task["id"]
        stage.mkdir(exist_ok=True)
        last_update = 0.0

        def progress(data):
            nonlocal last_update
            now = time.monotonic()
            if data.get("status") == "downloading" and now - last_update >= 0.15:
                emit("progress", **download_progress(data))
                last_update = now
            elif data.get("status") == "finished":
                emit("progress", **{**download_progress(data), "speed": 0, "eta": 0})

        def postprocess(data):
            if data.get("status") == "started":
                emit("state", state=State.MERGING.value, note="Обработка потоков")

        download = {**base, "format": choose_format(output, height, options.get("compatible", False)), "outtmpl": str(stage / "source.%(ext)s"), "continuedl": True, "overwrites": False, "progress_hooks": [progress], "postprocessor_hooks": [postprocess], "merge_output_format": "mp4" if output == "mp4" else None}
        emit("state", state=State.DOWNLOADING.value, note="")
        with YoutubeDL(download) as ydl:
            if cookies is not None:
                ydl.cookiejar = cookies
            try:
                result = ydl.process_ie_result(copy.deepcopy(info), download=True)
            except Exception as exc:
                # Public HLS formats can remain available when a direct CDN URL
                # refuses a request. Keep exact video resolution, or extract AAC
                # from a combined stream; never change the requested video size.
                hls = [f for f in info.get("formats", []) if str(f.get("protocol", "")).startswith("m3u8") and not f.get("has_drm")]
                if "403" not in str(exc) or not hls:
                    raise
                if output == "mp4":
                    size = f"[height={height}]" if height else ""
                    selector = f"b[protocol^=m3u8]{size}"
                    if height and not any(f.get("height") == height for f in hls):
                        raise
                elif output == "m4a":
                    selector = "ba[protocol^=m3u8][acodec^=mp4a]/b[protocol^=m3u8][acodec^=mp4a]/ba[protocol^=m3u8][acodec=aac]/b[protocol^=m3u8][acodec=aac]"
                else:
                    selector = "ba[protocol^=m3u8]/b[protocol^=m3u8]"
                note = "Пробуем другой доступный поток звука." if output != "mp4" else "Загружаем доступный поток того же качества."
                emit("state", state=State.DOWNLOADING.value, note=note)
                logging.info("Direct stream refused; trying available public HLS format: %s", selector)
                with YoutubeDL({**download, "format": selector}) as fallback:
                    if cookies is not None:
                        fallback.cookiejar = cookies
                    result = fallback.process_ie_result(copy.deepcopy(info), download=True)
                    source = Path(result.get("filepath") or fallback.prepare_filename(result))
            else:
                source = Path(result.get("filepath") or ydl.prepare_filename(result))
        if not source.exists():
            candidates = [p for p in stage.glob("source.*") if p.suffix in {".mp4", ".webm", ".mkv", ".m4a", ".mp3", ".ogg", ".opus"}]
            if not candidates:
                raise UserError("Загрузка не создала медиафайл.")
            source = candidates[0]
        processed = stage / ("finished." + output)
        convert(root, source, processed, info, options, emit)
        warning = embed_cover(root, processed, info, emit)
        # Same-volume atomic move; the reserved final name is never overwritten.
        if target.exists():
            raise UserError("Файл с таким именем появился во время загрузки. Повторите задачу.")
        processed.rename(target)
        try:
            receipt.write_text(json.dumps({"fingerprint": fingerprint, "url": task["url"]}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            logging.warning("Could not save download receipt", exc_info=True)
        shutil.rmtree(stage, ignore_errors=True)
        emit("completed", path=str(target), note=warning, final_size=target.stat().st_size)
