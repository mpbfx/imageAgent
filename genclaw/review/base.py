"""Reviewer 契约。

Review 层(论文 §3.3)对照 plan 中声明的 ``checks`` 检查一次渲染产出
的产物,产出 :class:`~genclaw.schemas.ReviewResult`。

设计上分两条互补路径:
  * 规则型(reviewer = 任务 10):对 plan 和编译产物做确定性检查,无浏览器。
  * VLM 型(reviewer = 任务 14,默认 Claude-Opus,见 ADR 0004):做感知层面
    的判断(数量、空间关系、文本可读性等)。

二者实现同一份 :class:`Reviewer` 契约,消费同一份 ``CanvasPlan``,因此可以
在 :class:`~genclaw.review.composite.CompositeReviewer` 中无缝组合。
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Optional

from genclaw.schemas import CanvasPlan, ReviewResult


class Reviewer(abc.ABC):
    """Reviews a rendered run against the plan's checks.

    对一次渲染结果执行 review 的抽象接口。所有 reviewer 必须实现
    :meth:`review`,输入是 plan + 编译产物(可选)+ 最终图像(可选),输
    出是统一的 :class:`~genclaw.schemas.ReviewResult`。
    """

    @abc.abstractmethod
    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        """Evaluate the plan's ``checks`` and return a result.

        遍历 ``plan.checks`` 并产出 :class:`~genclaw.schemas.ReviewResult`。

        :param plan: 本次渲染对应的 plan(reviewer 共用同一份契约)。
        :param canvas_source_path: 渲染阶段写出的 canvas 源码文件
            (SVG/HTML/Python 等),结构性检查要读它。
        :param image_path: 最终光栅化得到的 PNG,只有感知层(VLM)需要
            它,规则层不应使用。
        """
        raise NotImplementedError
