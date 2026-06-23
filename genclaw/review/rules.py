"""Rule-based reviewer (plan task 10).

Deterministic, browser-free checks over the plan and its rendered artifacts.
Each :class:`~genclaw.schemas.ReviewCheck` ``kind`` maps to a rule:

* ``object_count``   -- count objects of ``target`` kind; compare to ``expected``.
* ``contains_text``  -- the canvas source must contain ``expected`` text.
* ``backend``        -- the plan's backend must equal ``expected``.
* ``artifact_exists``-- the named artifact path must exist and be non-empty.
* ``image_size``     -- the rendered PNG dimensions must match (needs Pillow).

Every failure carries an explicit, human-readable reason. A check that cannot
be evaluated (e.g. image_size with no PNG) records a warning rather than a
silent pass, so missing evidence is never mistaken for success.

基于规则的 reviewer(任务 10)。

执行 plan 与渲染产物的确定性、无浏览器检查。每一个
:class:`~genclaw.schemas.ReviewCheck` ``kind`` 映射到一条具体规则:

  * ``object_count``   -- 数 plan 中 ``target`` 类型的对象,与 ``expected`` 比较。
  * ``contains_text``  -- 编译出的 canvas 源码必须包含 ``expected`` 文本。
  * ``backend``        -- plan 的 backend 必须等于 ``expected``。
  * ``artifact_exists``-- 命名 artifact 路径必须存在且非空。
  * ``image_size``     -- 渲染 PNG 的尺寸必须匹配(需 Pillow)。

设计要点:
  1. **失败必须带原因**——所有失败项都带可读说明,方便后续定位。
  2. **缺证据 ≠ 通过**——一条不能评估的 check(比如没有 PNG 时的
     ``image_size``)记为 warning,绝不悄悄通过。
  3. **可幂等复跑**——纯规则判断,不依赖任何外部服务,可放进 CI。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.review.base import Reviewer
from genclaw.schemas import CanvasPlan, ReviewCheck, ReviewResult


# 对 LLM agent 可能输出的「近似命名」做容错映射。prompt 里列的是规范名,
# 这里作为兜底——这样把 ``size`` 写错成 ``canvas_size`` 的 plan 仍能评,
# 不会因"未知 check kind"而直接挂掉。
_CHECK_ALIASES = {
    "size": "image_size",
    "canvas_size": "image_size",
    "required_text": "contains_text",
    "text": "contains_text",
    "element_count": "object_count",
    "count": "object_count",
}


class RuleReviewer(Reviewer):
    """Runs the plan's declarative checks and aggregates the result.

    把 plan 中的每条 :class:`~genclaw.schemas.ReviewCheck` 都跑一遍,汇
    总成一份 :class:`~genclaw.schemas.ReviewResult`。

    关键不变量:
      * 跑在浏览器外、无外部依赖,适合 CI / 离线回归。
      * 不读最终光栅化 PNG(那条路是 :class:`~genclaw.review.vlm.VLMReviewer`),
        只看 plan 和编译出的 canvas 源码。
    """

    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        # 一次性把 canvas 源码读进内存,所有 ``contains_text`` check 共用,
        # 避免对每条 check 重复读盘。
        source_text = None
        if canvas_source_path is not None and Path(canvas_source_path).exists():
            source_text = Path(canvas_source_path).read_text(encoding="utf-8")

        failures: list[str] = []
        warnings: list[str] = []
        passed_count = 0
        evaluated = 0

        for check in plan.checks:
            ok, reason, evaluable = _run_check(check, plan, source_text, image_path)
            if not evaluable:
                # 不可评估 = 缺证据,记 warning 而不是失败也不算通过
                warnings.append(reason)
                continue
            evaluated += 1
            if ok:
                passed_count += 1
            else:
                failures.append(reason)

        # score = 通过数 / 可评估数;全部不可评估时,score=0,passed=False
        # (否则会变成"啥也没检查所以通过",那是错误信号)
        score = passed_count / evaluated if evaluated else 0.0
        return ReviewResult(
            passed=not failures and evaluated > 0,
            score=score,
            failures=failures,
            warnings=warnings,
        )


def _run_check(
    check: ReviewCheck,
    plan: CanvasPlan,
    source_text: Optional[str],
    image_path: Optional[Path],
) -> tuple[bool, str, bool]:
    """Return (passed, reason, evaluable) for a single check.

    对单条 :class:`~genclaw.schemas.ReviewCheck` 做评估。
    返回三元组:
      * ``passed``  -- 检查是否通过;
      * ``reason``  -- 人可读说明,会进入 failures / warnings;
      * ``evaluable`` -- 这条 check 是否具备评估条件(否则记 warning)。

    kind 命名先用 :data:`_CHECK_ALIASES` 做一次宽容归一化,再分发到具体
    规则;未知 kind 一律失败,绝不悄悄通过。
    """
    kind = _CHECK_ALIASES.get(check.kind, check.kind)

    if kind == "object_count":
        # 数 plan.objects 里 kind == check.target 的对象,与 expected 对比
        actual = sum(1 for o in plan.objects if o.kind == check.target)
        expected = int(check.expected)
        if actual == expected:
            return True, f"object_count[{check.target}]={actual}", True
        return (
            False,
            f"object_count[{check.target}] expected {expected} but found {actual}",
            True,
        )

    if kind == "contains_text":
        # 必须能读到 canvas 源码;读不到 = 缺证据 = warning
        if source_text is None:
            return False, "contains_text: canvas source unavailable", False
        needle = str(check.expected)
        if needle in source_text:
            return True, f"contains_text: found {needle!r}", True
        return False, f"contains_text: missing required text {needle!r}", True

    if kind == "backend":
        # 验 plan.backend 字符串相等。注意这里比对的是 plan 的 backend,
        # 而不是最终光栅图——后者是 PNG,问它"是不是 SVG"没意义
        # (见 composite.py 中的注释)。
        actual = plan.backend.value
        if actual == str(check.expected):
            return True, f"backend={actual}", True
        return False, f"backend expected {check.expected!r} but plan uses {actual!r}", True

    if kind == "artifact_exists":
        # artifact 路径必须存在且非空文件;target 为空 = 配置错误,记失败
        target = Path(check.target) if check.target else None
        if target is None:
            return False, "artifact_exists: no target path given", True
        if target.exists() and target.stat().st_size > 0:
            return True, f"artifact_exists: {target}", True
        return False, f"artifact_exists: missing or empty {target}", True

    if kind == "image_size":
        return _check_image_size(check, plan, image_path)

    # 未知 kind:保守失败,避免静默通过
    return False, f"unknown check kind {kind!r}", True


def _check_image_size(
    check: ReviewCheck, plan: CanvasPlan, image_path: Optional[Path]
) -> tuple[bool, str, bool]:
    """对 ``image_size`` check 做具体评估。

    三种"缺证据"路径都返回 ``evaluable=False``:
      1. 没有提供 image_path(参数缺失);
      2. 图像文件存在但大小为 0(比如 fixture 模式占位 PNG);
      3. Pillow 没安装或图像解码失败(环境问题)。
    """
    if image_path is None or not Path(image_path).exists():
        return False, "image_size: rendered image unavailable", False
    if Path(image_path).stat().st_size == 0:
        # 占位 PNG(浏览器未跑、留空文件):不能评估,记 warning。
        return False, "image_size: rendered image is empty (no rasterization)", False
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return False, "image_size: Pillow not installed", False

    try:
        with Image.open(image_path) as img:
            actual = f"{img.width}x{img.height}"
            aw, ah = img.width, img.height
    except UnidentifiedImageError:
        return False, "image_size: rendered image is not a valid image", False
    # 默认期望值是 plan 里声明的逻辑画布尺寸;check.expected 优先。
    expected = str(check.expected or f"{plan.size.width}x{plan.size.height}")
    if actual == expected:
        return True, f"image_size={actual}", True
    # sketch 可能以整数倍的 device pixel ratio(典型 2x,让喂给图像模型的
    # 草图更清晰)被光栅化,所以 PNG 实际像素是逻辑尺寸的 N 倍。
    # 只要宽高都被整除、且缩放比一致,就当"等比放大"通过——
    # 这样不误报因 dpr>1 引起的尺寸差异,只拦真正的比例/数值异常。
    try:
        ew, eh = (int(v) for v in expected.lower().split("x"))
        if ew and eh and aw % ew == 0 and ah % eh == 0 and (aw // ew) == (ah // eh):
            return True, f"image_size={actual} ({aw // ew}x of {expected})", True
    except (ValueError, ZeroDivisionError):
        pass
    return False, f"image_size expected {expected} but got {actual}", True
