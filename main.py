from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--worker":
        from app.worker import run_worker
        return run_worker(sys.argv[2])
    from app.main import run
    return run()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import os
        import traceback
        from pathlib import Path
        root = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        try:
            folder = root / "data" / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "startup.log").write_text(traceback.format_exc(), encoding="utf-8")
        except OSError:
            pass
        if "--worker" not in sys.argv and "--verify-startup" not in sys.argv and os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "Не удалось запустить приложение. Проверьте полноту portable-папки и доступ к записи. Подробности в data/logs/startup.log.", "СЪЁМ — ошибка запуска", 0x10)
        raise SystemExit(1)
