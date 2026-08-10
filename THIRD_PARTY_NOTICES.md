# Third-Party Notices

The optional macOS application bundle contains these third-party components:

- **gallery-dl 1.32.9** — GPL-2.0. The separately bundled executable handles
  supported public image posts and is invoked as a subprocess. Source and
  license: <https://codeberg.org/mikf/gallery-dl/releases/tag/v1.32.9>.
- **yt-dlp 2026.07.04** — GPL-3.0-or-later. The bundled official macOS
  executable is GPL-licensed because it includes compiled third-party
  components; the source-only yt-dlp project is Unlicense. Source, licenses,
  and release artifacts:
  <https://github.com/yt-dlp/yt-dlp/releases/tag/2026.07.04>.
  The pinned executable SHA-256 is
  `498bd0dae17855c599d371d68ec5bafc439a9d8640e838be25c765a9792f261b`.
- **FFmpeg 7.1 arm64/x86_64** — GPL-2.0-or-later architecture-specific builds
  supplied by imageio-ffmpeg 0.6.0. Each is a separate executable invoked as a
  subprocess.
  Source, build distribution, and licenses:
  <https://github.com/FFmpeg/FFmpeg/tree/n7.1> and
  <https://github.com/imageio/imageio-ffmpeg/tree/v0.6.0>. The pinned
  executable SHA-256 values are
  `6d175a4743ca50256e89a8cdd731100f9cee33bd79aeea46894d209410dc6617`
  for arm64 and
  `4a4a968b98859588e98500ae25973d80a5ca5eed0724222b9f76360dcb72a001`
  for x86_64.
- **PyInstaller 6.21.0 bootloader** — GPL-2.0-or-later with the PyInstaller
  exception permitting distribution of bundled applications. Source and
  license: <https://github.com/pyinstaller/pyinstaller/tree/v6.21.0>.
- **CPython** — Python Software Foundation License. Source and license:
  <https://www.python.org/downloads/source/>.

The complete project source and these build instructions are published with the
application so recipients can inspect and replace the bundled executables.
