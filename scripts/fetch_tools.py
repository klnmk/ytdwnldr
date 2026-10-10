"""Fetch hash-locked official binaries and open fonts into this project only."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent


def get(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "syom-build/1.0"}), timeout=120) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-lock", action="store_true", help="Explicit maintainer action: recompute source digests")
    args = parser.parse_args()
    lock_path = ROOT / "tools.lock.json"
    manifest = json.loads(lock_path.read_text(encoding="utf-8"))
    cache = ROOT / ".tools-cache"
    cache.mkdir(exist_ok=True)
    for item in manifest["artifacts"]:
        target = cache / item["name"]
        if not target.exists():
            print("Downloading", item["name"], flush=True)
            temporary = target.with_suffix(".download")
            temporary.write_bytes(get(item["url"]))
            temporary.replace(target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if item.get("publisher_sha256") and digest != item["publisher_sha256"]:
            raise RuntimeError(f"Publisher checksum mismatch: {item['name']}")
        if args.refresh_lock:
            item["sha256"] = digest
        elif not item.get("sha256") or digest != item["sha256"]:
            raise RuntimeError(f"SHA-256 mismatch: {item['name']}. Remove the cached file and retry; do not bypass verification.")
        if item.get("zip_members"):
            with zipfile.ZipFile(target) as archive:
                for suffix, relative in item["zip_members"].items():
                    names = [n for n in archive.namelist() if n.endswith(suffix)]
                    if len(names) != 1:
                        raise RuntimeError(f"Unexpected archive member: {suffix}")
                    destination = ROOT / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(archive.read(names[0]))
        elif item.get("destination"):
            destination = ROOT / item["destination"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, destination)
    if args.refresh_lock:
        lock_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Tools and assets verified.")


if __name__ == "__main__":
    main()
