"""Playwright rasterization helper (plan task 5).

Renders an HTML string to a PNG via headless Chromium. This is the single point
that touches a browser; everything else (source compilation, review) is
browser-free. ``playwright`` is imported lazily inside the function so the
renderers' source-compilation paths import without it (phase-1 strategy: PNG
rasterization plugs in once the browser is installed).

Three.js / WebGL rendering (task 8) reuses ``BROWSER_ARGS`` and the
frame-ready wait validated by the task 7.5 spike: software WebGL via
swiftshader, and a screenshot only after frames have actually been painted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Chromium flags for stable headless rendering on Windows, including software
# WebGL (swiftshader) for Three.js scenes. Validated by the task 7.5 spike.
BROWSER_ARGS = [
    "--use-gl=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
]


class RenderTimeoutError(RuntimeError):
    """Raised when the page does not finish rendering within the timeout."""


def render_html_to_png(
    html: str,
    png_path: Path,
    *,
    width: int,
    height: int,
    timeout_ms: int = 15000,
    wait_for_frames: int = 0,
    scale: float = 2.0,
) -> Path:
    """Render ``html`` to ``png_path`` at a fixed viewport.

    ``scale`` is the device pixel ratio: the canvas is laid out at logical
    ``width``x``height`` but rasterized at ``scale``x that pixel density, so
    small text gets many more pixels. This matters when the sketch is later fed
    to an image model as a visual condition -- a low-res sketch makes the model
    lose/blur fine text. Default 2x.

    ``wait_for_frames`` > 0 waits for that many ``requestAnimationFrame`` ticks
    before the screenshot (needed for WebGL scenes that paint asynchronously).
    Captures console errors and surfaces a structured error on failure.

    The parent directory is created if missing. Raises
    :class:`RenderTimeoutError` on timeout.
    """
    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError as exc:  # pragma: no cover - exercised only without browser
        raise RuntimeError(
            "playwright is not installed; install the 'render' extra and run "
            "`python -m playwright install chromium`"
        ) from exc

    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=BROWSER_ARGS)
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=scale,
            )
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text)
                if msg.type == "error"
                else None,
            )
            try:
                page.set_content(html, wait_until="networkidle", timeout=timeout_ms)
                if wait_for_frames > 0:
                    _wait_for_frames(page, wait_for_frames, timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise RenderTimeoutError(
                    f"render timed out after {timeout_ms}ms"
                    + (f"; console errors: {console_errors}" if console_errors else "")
                ) from exc
            except PlaywrightError as exc:  # pragma: no cover
                raise RuntimeError(f"render failed: {exc}") from exc

            page.screenshot(path=str(png_path))
        finally:
            browser.close()

    return png_path


def _wait_for_frames(page, frames: int, timeout_ms: int) -> None:
    """Block until ``frames`` animation frames have been painted."""
    page.wait_for_function(
        """
        (target) => {
            if (window.__gcFrames === undefined) {
                window.__gcFrames = 0;
                const tick = () => { window.__gcFrames++; requestAnimationFrame(tick); };
                requestAnimationFrame(tick);
            }
            return window.__gcFrames >= target;
        }
        """,
        arg=frames,
        timeout=timeout_ms,
    )
