"""Composite reviewer: deterministic structural checks + VLM perceptual review.

The two review concerns are different and must run against different artifacts
(this separation fixes a real bug where structural checks like ``backend=svg``
were applied to the final *raster* image and always failed):

* **Structural** (backend, image_size, object_count, contains_text, ...) are
  deterministic facts about the *plan* and the *compiled canvas source*. They
  run via :class:`~genclaw.review.rules.RuleReviewer` against the canvas source,
  never the rasterized final image.
* **Perceptual** (does the final image actually show the right objects, counts,
  relations, legible text?) is a judgment about the *final image*, made by a
  VLM via :class:`~genclaw.review.vlm.VLMReviewer`.

The composite passes only if both pass; failures/warnings are merged with a
prefix so a reviewer can see which layer raised each item. The score is the
mean of the two layer scores.

组合 reviewer:确定性结构检查 + VLM 感知检查。

两类 review 关注点不同,必须跑在不同的 artifact 上(这个分离修复了一个
真实 bug:之前把 ``backend=svg`` 这类结构 check 套到最终光栅图上,会无
一例外失败):

  * **结构性**(backend / image_size / object_count / contains_text 等)是
    *plan* 和 *编译出的 canvas 源码* 上的确定性事实,由
    :class:`~genclaw.review.rules.RuleReviewer` 对源码执行,绝不用最
    终光栅图。
  * **感知性**(最终图像里对象是否对、数量对、关系对、文本可读)是 *最
    终图像* 上的判断,由 :class:`~genclaw.review.vlm.VLMReviewer` 做。

只有两层都通过 composite 才算通过;failures / warnings 合并时加层名前
缀,方便人定位是哪个层报的。score 取两层分数的平均。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.review.base import Reviewer
from genclaw.review.rules import RuleReviewer
from genclaw.schemas import CanvasPlan, ReviewResult


class CompositeReviewer(Reviewer):
    """Runs structural rules on the canvas source and VLM on the final image.

    在 canvas 源码上跑结构规则,在最终图像上跑 VLM。

    关键设计:这两个 reviewer 永远跑在不同 artifact 上,这一步把
    "把结构性 check 错配到光栅图"的 bug 直接消灭。
    """

    def __init__(self, structural: Optional[Reviewer] = None, perceptual: Optional[Reviewer] = None):
        # 结构层默认用 RuleReviewer(确定性、无外部依赖)。
        self.structural = structural or RuleReviewer()
        # 感知层是可选的——没凭据或没装 VLM SDK 时,composite 自动降级为
        # 仅结构层而不是整体失败。
        self.perceptual = perceptual

    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        # 结构性 check 跑在 plan + canvas 源码上(不是光栅图)。
        # 故意不传 image_path,这样 image_size 退化为对照 canvas 推
        # 出的尺寸,backend 一直检查的是 plan,而不是去问"这张 PNG
        # 是不是 SVG"——那个问题在语义上是无意义的。
        structural = self.structural.review(plan, canvas_source_path=canvas_source_path)

        # 给每条来自结构层的 failure / warning 加 "[structural]" 前缀,
        # 方便下游日志一眼区分是哪一层报的。
        failures = [f"[structural] {f}" for f in structural.failures]
        warnings = [f"[structural] {w}" for w in structural.warnings]
        scores = [structural.score]
        passed = structural.passed

        if self.perceptual is not None and image_path is not None:
            # 感知层同时拿到 canvas 源码(辅助上下文)和最终图像(主体)
            perceptual = self.perceptual.review(
                plan, canvas_source_path=canvas_source_path, image_path=image_path
            )
            failures += [f"[perceptual] {f}" for f in perceptual.failures]
            warnings += [f"[perceptual] {w}" for w in perceptual.warnings]
            scores.append(perceptual.score)
            # 两层都过才算过;任何一层挂掉都挂
            passed = passed and perceptual.passed
        elif self.perceptual is not None:
            # 配了 VLM 但没拿到最终图:记 warning,不让 composite 直接挂,
            # 保持向后兼容
            warnings.append("[perceptual] skipped: no final image to review")

        # score = 两层平均;只有结构层时退化为结构层自身分数
        return ReviewResult(
            passed=passed,
            score=sum(scores) / len(scores) if scores else 0.0,
            failures=failures,
            warnings=warnings,
        )
