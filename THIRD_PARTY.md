# Included software

The application is GPL-3.0-or-later. Original SVG art is supplied under the same license. Font names and third-party trademarks remain with their owners.

| Component | License | Corresponding source / project |
|---|---|---|
| Python 3.12 | PSF | https://www.python.org/downloads/source/ |
| PySide6 / Qt 6.12 | LGPL-3.0 / GPL-3.0 | https://download.qt.io/official_releases/QtForPython/ and https://download.qt.io/official_releases/qt/ |
| yt-dlp 2026.8.19 | Unlicense (individual vendored components have separate notices) | https://github.com/yt-dlp/yt-dlp/tree/2026.08.19 |
| yt-dlp-ejs | MIT | https://github.com/yt-dlp/ejs |
| FFmpeg 9.0.2 essentials by Gyan | GPL-3.0 | https://www.gyan.dev/ffmpeg/builds/ and https://github.com/FFmpeg/FFmpeg/commit/946fcce07b |
| Deno 2.9.7 | MIT (with dependency notices) | https://github.com/denoland/deno/tree/v2.9.7 |
| Oswald, Golos Text | SIL Open Font License 1.1 | https://github.com/google/fonts/tree/main/ofl/oswald and https://github.com/google/fonts/tree/main/ofl/golostext |
| Mutagen | GPL-2.0-or-later | https://github.com/quodlibet/mutagen |
| PyInstaller bootloader | GPL with distribution exception | https://github.com/pyinstaller/pyinstaller |

Python package license files, the FFmpeg build notice, font licenses, and Deno's license are copied into `licenses/`. Full pinned package versions are in `requirements.lock.txt`; binary and font hashes are in `tools.lock.json`. The application source and build recipe are included as `source.zip` in the portable folder.

The FFmpeg essentials build includes third-party GPL libraries (including x264/x265). Its upstream build README describes enabled libraries. When redistributing publicly, supply the complete corresponding source for the exact FFmpeg build and its linked libraries, plus the Qt/PySide corresponding source, as required by their licenses; upstream links alone do not replace that obligation. This local release includes the application source but does not mirror all upstream source trees.
