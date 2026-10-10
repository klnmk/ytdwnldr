"""Sync reviewed documentation and create a checked portable ZIP after a build."""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from build import ROOT, bundle_sources


def main():
    release = ROOT / "dist" / "ytdwnldr-portable"
    if not (release / "ytdwnldr.exe").is_file():
        raise SystemExit("Build the Windows executable first.")
    if "Results are updated" in (ROOT / "VALIDATION.md").read_text(encoding="utf-8"):
        raise SystemExit("Complete VALIDATION.md before finalizing the release.")
    for filename in ("README.md", "VALIDATION.md", "LICENSE", "THIRD_PARTY.md", "tools.lock.json", "requirements.lock.txt"):
        shutil.copy2(ROOT / filename, release / filename)
    bundle_sources(release)
    destination = ROOT / "dist" / "ytdwnldr-portable.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(release.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(release.parent).as_posix())
            elif not any(path.iterdir()):
                archive.write(path, path.relative_to(release.parent).as_posix() + "/")
    with zipfile.ZipFile(destination) as archive:
        if bad := archive.testzip():
            raise RuntimeError(f"Archive CRC check failed: {bad}")
    with destination.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    destination.with_suffix(".zip.sha256").write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    metrics = {
        "folder_mib": round(sum(path.stat().st_size for path in release.rglob("*") if path.is_file()) / 1048576, 1),
        "zip_mib": round(destination.stat().st_size / 1048576, 1),
        "zip_sha256": digest,
        "archive_crc_check": "passed",
        "file_count": sum(path.is_file() for path in release.rglob("*")),
    }
    (ROOT / "artifacts" / "package-metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
