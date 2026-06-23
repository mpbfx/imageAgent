"""Playwright 光栅化辅助函数(plan task 5)。

把一段 HTML 字符串丢进 headless Chromium 截成 PNG。整个项目里只有本模块
碰浏览器,其它(源码编译、review)都不依赖浏览器。``playwright`` 在函数
内部懒加载——这样 renderer 的「只编译源码不截屏」路径在没装 playwright
时也能 import(phase-1 策略:等浏览器装上再把 PNG 截屏接通)。

Three.js / WebGL 渲染(task 8)复用 ``BROWSER_ARGS`` 和「等帧就绪」的
wait(task 7.5 spike 验证过):swiftshader 软渲 WebGL + 真正画完再截屏。
"""

# 中文补充说明:
# BROWSER_ARGS 是为 Windows headless 环境调出来的 Chromium flags:
#   - --use-gl=swiftshader:在没硬件 GPU 的 headless 环境用 swiftshader 软渲
#   - --enable-unsafe-swiftshader:显式放行 swiftshader(新 Chromium 默认禁)
#   - --ignore-gpu-blocklist:即使在黑名单 GPU 上也试
#   - --disable-dev-shm-usage:避免 /dev/shm 太小导致 Chromium 挂
#   - --hide-scrollbars:防截图里多出来滚动条
# scale=2.0(device pixel ratio)很关键:把 layout 1024x1024 的 sketch 实际
# 截成 2048x2048,小字才不会糊——下游 image model 收低清 sketch 会丢
# 细节(尤其是文字)。
# console_errors 在出错时一起打到异常信息里:常常是 CDN 拉不到/JS 报错导致
# 白屏,异常信息能直接指出原因。

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Chromium flags:为 Windows headless 调出来的稳定组合,含 swiftshader 软渲
# WebGL(task 7.5 spike 验证)。
BROWSER_ARGS = [
    "--use-gl=swiftshader",
    "--enable-unsafe-swiftshader",
    "--ignore-gpu-blocklist",
    "--disable-dev-shm-usage",
    "--hide-scrollbars",
]


class RenderTimeoutError(RuntimeError):
    """页面在 timeout 之内没渲染完。"""


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
    """把 ``html`` 渲染到 ``png_path``,用固定视口。

    ``scale`` 是 device pixel ratio:布局按逻辑 ``width``x``height``,但实
    际截成 ``scale``x 那个像素密度,让小字拿到更多像素。这事很关键——
    sketch 是给下游 image model 当「视觉条件」的,低清 sketch 会让模型
    糊掉细字。默认 2x。

    ``wait_for_frames`` > 0 时,等够那个数量个 ``requestAnimationFrame``
    帧再截图(WebGL 场景是异步画完的,必须等)。失败时把 console error
    收集到结构化异常里。

    父目录不存在会自动建。timeout 抛 :class:`RenderTimeoutError`。
    """
    try:
        from playwright.sync_api import (
            Error as PlaywrightError,
            TimeoutError as PlaywrightTimeoutError,
            sync_playwright,
        )
    except ImportError as exc:  # pragma: no cover - 仅在没装浏览器时执行
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
                # networkidle:等所有 CDN/资源加载完(Three.js 场景要等模块)
                page.set_content(html, wait_until="networkidle", timeout=timeout_ms)
                _wait_for_fonts_ready(page, timeout_ms)
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


def _wait_for_fonts_ready(page, timeout_ms: int) -> None:
    """等浏览器字体系统完成匹配/加载,避免截图早于 font fallback 稳定。"""
    page.wait_for_function(
        """
        () => !document.fonts || document.fonts.ready.then(() => true)
        """,
        timeout=timeout_ms,
    )


def _wait_for_frames(page, frames: int, timeout_ms: int) -> None:
    """等够 ``frames`` 个动画帧再放行。

    通过 page.wait_for_function 注入一个全局 frame 计数器:每次 rAF
    自增,达到目标值就 resolve。
    """
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
