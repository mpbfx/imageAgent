"""Renderer 契约 + ``RenderedCanvas`` 数据结构。

Renderer 把校验过的 :class:`~genclaw.schemas.CanvasPlan` 编译成可执行
画布源码(SVG / HTML / Three.js 宿主页),再光栅化成 PNG 草图。本模块
只定义*契约*和结果类型;具体 renderer(task 6-8)与 Playwright 光栅化
辅助(task 5)都在同级模块里,浏览器懒加载,所以即使没装 Playwright
本模块也能 import。
"""
# 本模块:定义所有 renderer 的统一接口(抽象基类 Renderer)和渲染结果数据结构
# (RenderedCanvas)。renderer 的职责是把校验过的 CanvasPlan 编译成可执行画布
# 源码(SVG/HTML/Three.js),再光栅化成 PNG 草图(sketch)。
# 关键设计:本文件只定义"契约",不依赖 Playwright;具体后端实现和浏览器渲染
# 都在同级模块里、且懒加载浏览器,所以即使没装 Playwright 也能 import 本模块。

from __future__ import annotations

import abc
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from genclaw.schemas import CanvasBackend, CanvasPlan


class RenderedCanvas(BaseModel):
    """一步渲染的输出。

    ``png_path`` 可选,因为源码编译(确定性、无浏览器)和 PNG 光栅化
    (Playwright)是可分离的:phase-1 CI 没有浏览器也能产出并检查
    canvas 源码。
    """

    backend: CanvasBackend
    source_path: Path
    png_path: Optional[Path] = None
    width: int
    height: int


class Renderer(abc.ABC):
    """把 :class:`CanvasPlan` 编译成画布源码与 PNG 草图。"""

    backend: CanvasBackend

    @abc.abstractmethod
    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        """把 ``plan`` 编译到 ``output_dir`` 并返回结果。"""
        raise NotImplementedError
