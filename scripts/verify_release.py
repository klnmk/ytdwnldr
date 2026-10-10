"""Exercise a relocated frozen release without Python/FFmpeg on PATH."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent


def main():
    source = ROOT / "dist" / "ytdwnldr-portable"
    destination = ROOT / "artifacts" / "relocation-test" / "Съём Portable"
    if destination.exists():
        resolved = destination.resolve()
        assert resolved.is_relative_to((ROOT / "artifacts" / "relocation-test").resolve()) and resolved.name == "Съём Portable"
        shutil.rmtree(resolved)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)
    ready = destination / "data" / "startup-ready.txt"
    ready.unlink(missing_ok=True)
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QTDIR"):
        environment.pop(name, None)
    environment["PATH"] = os.path.join(os.environ["SystemRoot"], "System32")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONIOENCODING"] = "utf-8"
    exe = destination / "ytdwnldr.exe"
    started = time.perf_counter()
    process = subprocess.Popen([str(exe), "--verify-startup"], cwd=destination, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    while not ready.exists() and time.perf_counter() - started < 20:
        if process.poll() is not None:
            raise RuntimeError(f"Startup failed with exit code {process.returncode}")
        time.sleep(0.025)
    if not ready.exists():
        process.kill()
        raise RuntimeError("Startup readiness timed out")
    elapsed = time.perf_counter() - started
    observed = psutil.Process(process.pid)
    ram = observed.memory_info().rss / 1048576
    cpu = observed.cpu_percent(interval=2)
    connections = len(observed.net_connections(kind="inet"))
    process.wait(timeout=15)
    if process.returncode:
        raise RuntimeError(f"Startup check exited with {process.returncode}")
    screenshot = destination / "data" / "startup-verification.png"
    assert screenshot.exists()
    shutil.copy2(screenshot, ROOT / "artifacts" / "ui-packaged.png")
    # Verify the --windowed worker's inherited pipes and bundled EJS/SSL modules.
    job = destination / "data" / "jobs" / "verification.json"
    job.write_text(json.dumps({"root": str(destination), "kind": "metadata", "url": "https://www.youtube.com/watch?v=YE7VzlLtp-4"}), encoding="utf-8")
    worker = subprocess.run([str(exe), "--worker", str(job)], cwd=destination, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
    events = []
    for line in worker.stdout.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            pass
    results = {"relocated_exe": str(exe), "startup_to_rendered_ready_seconds": round(elapsed, 3), "idle_rss_mib": round(ram, 1), "idle_cpu_percent_two_seconds": cpu, "idle_inet_connections": connections, "gui_exit_code": process.returncode, "python_and_ffmpeg_removed_from_path": True, "worker_exit_code": worker.returncode, "worker_events": events, "worker_stderr": worker.stderr[-3000:]}
    (ROOT / "artifacts" / "release-metrics.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=True, indent=2))
    assert worker.returncode == 0 and any(e.get("event") == "metadata" for e in events), "Frozen metadata worker failed; see release-metrics.json"
    assert all(Path(e["path"]).exists() for e in events if e.get("event") == "thumbnail"), "Frozen worker corrupted a Unicode path"
    ui_checks = []
    for platform, scale in (("offscreen", "1"), ("windows", "1"), ("windows", "1.25"), ("windows", "1.5")):
        check_environment = {**environment, "QT_QPA_PLATFORM": platform, "QT_SCALE_FACTOR": scale}
        report = destination / "data" / "ui-verification" / "data" / "verification-result.json"
        report.unlink(missing_ok=True)
        check = subprocess.run([str(exe), "--verify-ui"], cwd=destination, env=check_environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        result = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {"error": "No UI verification result"}
        ui_checks.append({"platform": platform, "qt_scale_factor": scale, "exit_code": check.returncode, **result})
        (ROOT / "artifacts" / "packaged-ui-checks.json").write_text(json.dumps(ui_checks, indent=2), encoding="utf-8")
        assert check.returncode == 0 and "error" not in result and result.get("passed") == 6, f"Frozen UI failed: {ui_checks[-1]}"
        screenshot = report.parent / "updated-ui.png"
        shutil.copy2(screenshot, ROOT / "artifacts" / f"ui-packaged-updated-{platform}-{scale}.png")
    print("Frozen UI: 6 interaction checks passed on offscreen and native Windows at 100%, 125%, 150% Qt scaling.")


if __name__ == "__main__":
    main()
