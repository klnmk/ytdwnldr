from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from app.domain import UserError, friendly_error


def run_worker(job_path: str) -> int:
    # Windowed frozen builds need to bind Python streams to inherited OS pipes.
    if os.name == "nt":
        import ctypes
        import msvcrt
        kernel = ctypes.WinDLL("kernel32")
        kernel.GetStdHandle.restype = ctypes.c_void_p
        for name, handle_id, mode, flags in (("stdin", -10, "r", os.O_RDONLY), ("stdout", -11, "w", os.O_WRONLY), ("stderr", -12, "w", os.O_WRONLY)):
            if getattr(sys, name) is None:
                handle = kernel.GetStdHandle(handle_id)
                fd = msvcrt.open_osfhandle(handle, flags)
                setattr(sys, name, open(fd, mode, encoding="utf-8", buffering=1))
    job = json.loads(Path(job_path).read_text(encoding="utf-8"))
    root = Path(job["root"])
    if job.get("guarded"):
        if sys.stdin.readline().strip() != "go":
            return 2
    os.environ["DENO_DIR"] = str(root / "data" / "cache" / "deno")
    os.environ["DENO_NO_UPDATE_CHECK"] = "1"
    logging.basicConfig(level=logging.INFO, filename=root / "data" / "logs" / "workers.log", encoding="utf-8", format="%(asctime)s %(process)d %(levelname)s %(message)s")

    def emit(kind, **values):
        # ASCII JSON survives the Windows GUI bootloader's inherited ANSI streams.
        print(json.dumps({"event": kind, **values}, ensure_ascii=True), flush=True)

    try:
        from app.engine import execute_download, extract_metadata
        if job["kind"] == "metadata":
            extract_metadata(root, job["url"], emit)
        elif job["kind"] == "download":
            execute_download(root, job["task"], emit)
        else:
            raise UserError("Неизвестная операция.")
        return 0
    except Exception as exc:
        logging.exception("Worker failed")
        emit("error", message=str(exc) if isinstance(exc, UserError) else friendly_error(str(exc)))
        return 1
