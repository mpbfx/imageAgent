"""Renderer contract and the ``RenderedCanvas`` data carrier.

A renderer compiles a validated :class:`~genclaw.schemas.CanvasPlan` into
executable canvas source (SVG / HTML / Three.js host page) and rasterizes it to
a PNG sketch. This module defines only the *contract* and the result type; the
concrete renderers (tasks 6-8) and the Playwright rasterization helper (task 5)
live in sibling modules and import the browser lazily, so this module stays
importable without Playwright.
"""
# 本模块：定义所有 renderer 的统一接口（抽象基类 Renderer）和渲染结果数据结构
# （RenderedCanvas）。renderer 的职责是把校验过的 CanvasPlan 编译成可执行画布
# 源码（SVG/HTML/Three.js），再光栅化成 PNG 草图(sketch)。
# 关键设计：本文件只定义“契约”，不依赖 Playwright；具体后端实现和浏览器渲染
# 都在同级模块里、且懒加载浏览器，所以即使没装 Playwright 也能 import 本模块。

from __future__ import annotations

import abc
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from genclaw.schemas import CanvasBackend, CanvasPlan


class RenderedCanvas(BaseModel):
    """The output of a render step.

    ``png_path`` is optional because source compilation (deterministic, no
    browser) and PNG rasterization (Playwright) are separable: phase-1 CI
    without a browser can still produce and check the canvas source.
    """

    backend: CanvasBackend
    source_path: Path
    png_path: Optional[Path] = None
    width: int
    height: int


class Renderer(abc.ABC):
    """Compiles a :class:`CanvasPlan` to canvas source and a PNG sketch."""

    backend: CanvasBackend

    @abc.abstractmethod
    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        """Compile ``plan`` into ``output_dir`` and return the result."""
        raise NotImplementedError
