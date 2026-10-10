from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

root = Path(SPECPATH)
datas = [(str(root / 'assets'), 'assets')]
for package in ('yt_dlp', 'yt_dlp_ejs', 'certifi'):
    datas += collect_data_files(package)
for package in ('yt-dlp', 'yt-dlp-ejs', 'mutagen', 'requests', 'urllib3', 'websockets', 'brotli', 'certifi', 'pycryptodomex'):
    datas += copy_metadata(package)

a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=[], datas=datas,
             hiddenimports=collect_submodules('yt_dlp', filter=lambda name: '.__pyinstaller' not in name) + collect_submodules('yt_dlp_ejs') + ['mutagen.mp4', 'mutagen.id3'],
             hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtPrintSupport', 'tkinter', 'unittest', 'pytest', 'psutil'],
             noarchive=False, optimize=1)
# Raster widgets need no OpenGL fallback. Qt 6.12 uses Windows' ICU API;
# Poppler's similarly named DLL exports a different ABI and must not shadow it.
a.binaries = [entry for entry in a.binaries if Path(entry[0]).name.lower() not in {'opengl32sw.dll', 'icuuc.dll', 'icuin.dll', 'icudt78.dll'}]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ytdwnldr', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(root / 'assets' / 'icon.ico'), version=str(root / 'scripts' / 'version.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ytdwnldr-portable')
