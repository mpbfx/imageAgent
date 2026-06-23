"""Tests for browser rasterization helpers."""

from genclaw.renderers.playwright_render import _wait_for_fonts_ready


class FakePage:
    def __init__(self):
        self.calls = []

    def wait_for_function(self, script, timeout):
        self.calls.append((script, timeout))


def test_wait_for_fonts_ready_uses_browser_font_api():
    page = FakePage()
    _wait_for_fonts_ready(page, timeout_ms=1234)
    assert page.calls
    script, timeout = page.calls[0]
    assert "document.fonts.ready" in script
    assert timeout == 1234
