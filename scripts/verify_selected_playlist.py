from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    meta = next(e for e in json.loads((ROOT / "artifacts" / "playlist-live.json").read_text(encoding="utf-8")) if e["event"] == "metadata")
    selected = [e for e in meta["entries"] if not e.get("unavailable") and 1 < (e.get("duration") or 0) <= 30][:2]
    assert len(selected) == 2
    release = ROOT / "artifacts" / "relocation-test" / "Съём Portable"
    environment = os.environ.copy()
    environment["PATH"] = os.path.join(os.environ["SystemRoot"], "System32")
    for key in ("PYTHONHOME", "PYTHONPATH"):
        environment.pop(key, None)
    processes = []
    for entry in selected:
        task = {"id": "playlist-" + entry["id"], "url": entry["url"], "title": entry["title"], "playlist": meta["title"], "index": entry["index"], "destination": str(ROOT / "artifacts" / "playlist-downloads"), "options": {"output": "mp3", "bitrate": 192, "playlist_folder": True, "existing": "skip"}}
        job = release / "data" / "jobs" / (task["id"] + ".json")
        job.write_text(json.dumps({"root": str(release), "kind": "download", "task": task}), encoding="utf-8")
        process = subprocess.Popen([str(release / "ytdwnldr.exe"), "--worker", str(job)], cwd=release, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append((entry, process))
    results = []
    for entry, process in processes:
        stdout, stderr = process.communicate(timeout=180)
        events = [json.loads(line) for line in stdout.splitlines() if line.startswith("{")]
        done = next((e for e in events if e.get("event") == "completed"), None)
        result = {"index": entry["index"], "url": entry["url"], "title": entry["title"], "exit_code": process.returncode, "final_event": events[-1] if events else None}
        if done:
            target = Path(done["path"])
            assert target.name.startswith(f"{entry['index']:03d} - ") and target.parent.name == meta["title"]
            probed = subprocess.run([str(release / "bin" / "ffprobe.exe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(target)], capture_output=True, text=True, encoding="utf-8", check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            result["ffprobe"] = json.loads(probed.stdout)
        results.append(result)
        print(json.dumps(result, ensure_ascii=True), flush=True)
    (ROOT / "artifacts" / "playlist-download-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    assert all(r["exit_code"] == 0 and "ffprobe" in r for r in results)


if __name__ == "__main__":
    main()
