from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bundle_sources(release: Path):
    """Archive the current sources directly, avoiding stale staging files."""
    directories = ("app", "assets", "scripts", "tests", "licenses")
    filenames = ("main.py", "build.bat", "run.bat", "ytdwnldr.spec", "pytest.ini", ".gitignore", "requirements.txt", "requirements-dev.txt", "requirements.lock.txt", "tools.lock.json", "README.md", "VALIDATION.md", "LICENSE", "THIRD_PARTY.md")
    sources = [ROOT / name for name in filenames]
    sources.extend(path for name in directories for path in (ROOT / name).rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
    with zipfile.ZipFile(release / "source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for source in sorted(sources):
            archive.write(source, source.relative_to(ROOT).as_posix())


def main():
    if os.name != "nt" or sys.maxsize <= 2**32:
        raise SystemExit("A Windows x64 Python environment is required.")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_tools.py")], cwd=ROOT, check=True)
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QIcon, QPainter, QPixmap
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    icon = QIcon()
    renderer = QSvgRenderer(str(ROOT / "assets" / "icon.svg"))
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill()
        painter = QPainter(pixmap)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    # Qt's ICO writer stores all resolutions when supplied through an icon pixmap.
    icon.pixmap(256, 256).save(str(ROOT / "assets" / "icon.ico"), "ICO")
    import PySide6
    translations = ROOT / "assets" / "translations"
    translations.mkdir(exist_ok=True)
    qt_translation = Path(PySide6.__file__).parent / "translations" / "qtbase_ru.qm"
    if qt_translation.exists():
        shutil.copy2(qt_translation, translations)
    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, check=True)
    environment = os.environ.copy()
    # Keep unrelated host tools (e.g. Poppler's ICU) out of dependency discovery.
    environment["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), str(Path(sys.base_prefix)), str(Path(sys.base_prefix) / "DLLs"), str(Path(os.environ["SystemRoot"]) / "System32"), os.environ["SystemRoot"]])
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(ROOT / "ytdwnldr.spec")], cwd=ROOT, env=environment, check=True)
    release = ROOT / "dist" / "ytdwnldr-portable"
    shutil.copytree(ROOT / "bin", release / "bin", dirs_exist_ok=True)
    shutil.copytree(ROOT / "licenses", release / "licenses", dirs_exist_ok=True)
    for package in importlib.metadata.distributions():
        destination = release / "licenses" / package.metadata["Name"]
        for entry in package.files or []:
            if any(word in str(entry).lower() for word in ("license", "copying")) and not str(entry).endswith(".py"):
                source = package.locate_file(entry)
                if source.is_file():
                    destination.mkdir(exist_ok=True)
                    shutil.copy2(source, destination / source.name)
    for filename in ("README.md", "VALIDATION.md", "LICENSE", "THIRD_PARTY.md", "tools.lock.json", "requirements.lock.txt"):
        shutil.copy2(ROOT / filename, release / filename)
    (release / "data").mkdir(exist_ok=True)
    # Bundle our corresponding source and exact build recipe for redistribution.
    bundle_sources(release)
    total = sum(p.stat().st_size for p in release.rglob("*") if p.is_file())
    print(f"Portable release: {release}\nSize: {total / 1048576:.1f} MiB", flush=True)


if __name__ == "__main__":
    main()
