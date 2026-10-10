"""Live authorized test: real download/conversion through frozen worker processes."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    video_height = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    release = ROOT / "artifacts" / "relocation-test" / "Съём Portable"
    exe = release / "ytdwnldr.exe"
    folder = ROOT / "artifacts" / "live-downloads"
    if len(sys.argv) > 3:
        folder = ROOT / "artifacts" / sys.argv[3]
        if not folder.resolve().is_relative_to((ROOT / "artifacts").resolve()):
            raise SystemExit("Verification downloads must stay inside artifacts.")
    report = folder / "results.json" if len(sys.argv) > 3 else ROOT / "artifacts" / "live-results.json"
    folder.mkdir(exist_ok=True)
    environment = os.environ.copy()
    environment["PATH"] = os.path.join(os.environ["SystemRoot"], "System32")
    for name in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(name, None)
    results = []
    for output, height, bitrate in (("mp4", video_height, 192), ("mp3", 0, 320), ("m4a", 0, 192)):
        task = {"url": url, "title": "Live verification", "id": "verification-" + output, "destination": str(folder), "options": {"output": output, "height": height, "bitrate": bitrate, "compatible": True, "existing": "skip"}}
        job_file = release / "data" / "jobs" / (output + ".json")
        job_file.write_text(json.dumps({"root": str(release), "kind": "download", "task": task}), encoding="utf-8")
        started = time.perf_counter()
        completed = subprocess.run([str(exe), "--worker", str(job_file)], cwd=release, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
        events = []
        for line in completed.stdout.splitlines():
            try:
                events.append(json.loads(line))
            except ValueError:
                pass
        result = {"output": output, "seconds": round(time.perf_counter() - started, 2), "exit_code": completed.returncode, "events": events, "stderr": completed.stderr[-2000:]}
        done = next((e for e in events if e["event"] == "completed"), None)
        if done:
            assert done.get("final_size") == Path(done["path"]).stat().st_size, "Worker did not report the actual output size"
            probed = subprocess.run([str(release / "bin" / "ffprobe.exe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", done["path"]], capture_output=True, text=True, encoding="utf-8", check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            result["ffprobe"] = json.loads(probed.stdout)
        results.append(result)
        report.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"output": output, "exit_code": completed.returncode, "final_event": events[-1] if events else None}, ensure_ascii=True), flush=True)
    assert all(r["exit_code"] == 0 and "ffprobe" in r for r in results), "Live download failed; see artifacts/live-results.json"


if __name__ == "__main__":
    main()
