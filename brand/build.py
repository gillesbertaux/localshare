#!/usr/bin/env python3
"""Rasterize the SVG sources in this folder into png/.

The SVGs are the source of truth; everything in png/ is generated. Run this
after editing a mark, and commit the result so consumers who cannot render SVG
still get correct pixels.

Chrome headless is the renderer because it is the only one reliably available on
macOS that honours stroke-linecap and keeps the background transparent.
ImageMagick's internal SVG renderer squares off the arc caps; QuickLook flattens
onto white.

Usage: python3 brand/build.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PNG_EOF = b"IEND\xae\x42\x60\x82"
RENDER_TIMEOUT_S = 90

BRAND = Path(__file__).resolve().parent
OUT = BRAND / "png"

CHROME = Path(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)

# (source svg, width, height, output name)
TARGETS: list[tuple[str, int, int, str]] = [
    ("logo.svg", 64, 64, "logo-64.png"),
    ("logo.svg", 128, 128, "logo-128.png"),
    ("logo.svg", 256, 256, "logo-256.png"),
    ("logo.svg", 512, 512, "logo-512.png"),
    ("logo.svg", 1024, 1024, "logo-1024.png"),
    ("logo-mono.svg", 512, 512, "logo-mono-512.png"),
    ("logo-dark.svg", 512, 512, "logo-dark-512.png"),
    ("favicon.svg", 16, 16, "favicon-16.png"),
    ("favicon.svg", 32, 32, "favicon-32.png"),
    ("favicon.svg", 48, 48, "favicon-48.png"),
    ("logo-badge.svg", 180, 180, "apple-touch-icon-180.png"),
    ("logo-badge.svg", 512, 512, "icon-512.png"),
    ("logo-badge.svg", 1024, 1024, "icon-1024.png"),
    ("logo-lockup.svg", 480, 128, "logo-lockup-480.png"),
    ("logo-lockup.svg", 960, 256, "logo-lockup-960.png"),
    ("logo-lockup-dark.svg", 480, 128, "logo-lockup-dark-480.png"),
    ("logo-lockup-dark.svg", 960, 256, "logo-lockup-dark-960.png"),
    ("states/reach-lan.svg", 128, 128, "reach-lan-128.png"),
    ("states/reach-tailnet.svg", 128, 128, "reach-tailnet-128.png"),
    ("states/reach-public.svg", 128, 128, "reach-public-128.png"),
    ("states/reach-off.svg", 128, 128, "reach-off-128.png"),
]

ICO_SOURCES = ["favicon-16.png", "favicon-32.png", "favicon-48.png"]

PAGE = """<!doctype html>
<meta charset="utf-8">
<style>
  html, body {{ margin: 0; padding: 0; background: transparent; color: #10162F; }}
  svg {{ display: block; width: {w}px; height: {h}px; }}
</style>
{svg}
"""

_ROOT_SIZE = re.compile(r'\s(?:width|height)="[^"]*"')


def _page(svg_path: Path, width: int, height: int) -> str:
    """Inline the SVG at an exact CSS size so the screenshot needs no cropping."""
    svg = svg_path.read_text(encoding="utf-8")
    head, sep, tail = svg.partition(">")
    if not sep:
        raise SystemExit(f"{svg_path.name}: no SVG root tag")
    return PAGE.format(w=width, h=height, svg=_ROOT_SIZE.sub("", head) + sep + tail)


def _wait_for_png(path: Path, proc: subprocess.Popen[bytes]) -> bool:
    """Chrome writes the screenshot long before it exits, so watch the file.

    Its bundled updater keeps the process alive for ~30s per launch; waiting on
    exit would turn a two-second build into a ten-minute one.
    """
    deadline = time.monotonic() + RENDER_TIMEOUT_S
    while time.monotonic() < deadline:
        if path.is_file() and path.read_bytes().endswith(PNG_EOF):
            return True
        if proc.poll() is not None and not path.is_file():
            return False
        time.sleep(0.1)
    return False


def render(source: str, width: int, height: int, name: str, workdir: Path) -> None:
    page = workdir / f"{name}.html"
    page.write_text(_page(BRAND / source, width, height), encoding="utf-8")
    out = OUT / name
    out.unlink(missing_ok=True)

    proc = subprocess.Popen(
        [
            str(CHROME),
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            f"--user-data-dir={workdir / 'chrome'}",
            f"--window-size={width},{height}",
            f"--screenshot={out}",
            page.as_uri(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        if not _wait_for_png(out, proc):
            raise SystemExit(f"error: Chrome did not render {name}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    print(f"  {name}  ({width}x{height})")


def main() -> int:
    if not CHROME.is_file():
        print(f"error: need Chrome at {CHROME}", file=sys.stderr)
        return 1

    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        for source, width, height, name in TARGETS:
            render(source, width, height, name, workdir)

    ico = shutil.which("magick") or shutil.which("convert")
    if ico:
        subprocess.run(
            [ico, *[str(OUT / n) for n in ICO_SOURCES], str(BRAND / "favicon.ico")],
            check=True,
        )
        print("  favicon.ico (16, 32, 48)")
    else:
        print("  skipped favicon.ico (no ImageMagick)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
