"""VLM-based reviewer (plan task 14).

Perceptual review of the final image against the plan, complementing the
deterministic rule reviewer (:mod:`genclaw.review.rules`). The default backbone
is Claude-Opus (ADR 0004), used as a vision-language judge that returns a
structured pass/fail with evidence.

Like the other external adapters, the SDK is imported lazily and credentials
are required up front; the structured-output contract is enforced and a parse
failure surfaces as a structured error rather than a silent pass.

VLM 版 reviewer(任务 14)。

对最终图像做感知层 review,与确定性规则 reviewer(:mod:`genclaw.review.rules`)
互为补充。默认骨干是 Claude-Opus(ADR 0004),用 VLM 当 judge,返回带
evidence 的结构化 pass/fail。

设计要点(与其他外部 adapter 一致):
  * SDK 懒加载,本地无凭据时不会因 import 失败而崩;
  * 凭据提前校验(在 :class:`~genclaw.config.ProviderConfig` 阶段);
  * 结构化输出契约强制执行——VLM 吐出非 JSON 时解析失败会显式落到
    ``ReviewResult.failures``,绝不悄悄通过。
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

from genclaw.config import ProviderConfig
from genclaw.review.base import Reviewer
from genclaw.schemas import CanvasPlan, ReviewResult

# VLM 的 system prompt:明确划定它"该管什么 / 不该管什么",
# 防止它去 judge 后端选型、文件大小这种语义上判不了的东西(那些是规则
# 层职责)。同时要求它只回 JSON,便于结构化解析。
_VLM_SYSTEM = """\
You are the perceptual review layer of GenClaw. You judge ONLY whether the
rendered image visually satisfies the user's intent described in the plan:
correct objects and counts, spatial relations, attributes/colors, and required
text being visibly present and legible.

Do NOT judge implementation details you cannot determine from a photo: do not
fault the image for being a raster photograph "instead of SVG/HTML" (the final
image is always a rasterized render -- that is expected and correct), and do not
try to verify exact pixel dimensions. Backend, file size, and exact dimensions
are checked separately by deterministic rules, not by you.

Reply with ONLY a JSON object: {"passed": bool, "score": 0..1,
"failures": [str], "warnings": [str]}. Put only genuine perceptual mismatches
(wrong count, wrong relation, missing/illegible text) in failures; cite concrete
visual evidence.
"""


class VLMReviewer(Reviewer):
    """Claude-Opus vision reviewer (default paper-aligned reviewer).

    默认与论文一致的 Claude-Opus VLM reviewer。
    """

    name = "claude-opus-vlm"

    def __init__(self, config: Optional[ProviderConfig] = None):
        # 没有传 config 时,从环境变量读——保持与其他 provider 一致。
        self.config = config or ProviderConfig.from_env()

    def review(
        self,
        plan: CanvasPlan,
        canvas_source_path: Optional[Path] = None,
        image_path: Optional[Path] = None,
    ) -> ReviewResult:
        # VLM 必须有最终图像才能 review;没有就直接结构化失败
        if image_path is None or not Path(image_path).exists():
            return ReviewResult(
                passed=False,
                score=0.0,
                failures=["VLM review requires a rendered image; none was provided"],
            )
        raw = self._complete(plan, Path(image_path))
        return _parse_result(raw)

    def _complete(self, plan: CanvasPlan, image_path: Path) -> str:
        """Call Claude with the image + plan; return raw text. Lazy SDK import.

        调 Claude,把 plan 摘要 + base64 图像一起塞进 user message。
        SDK 懒加载,本地没装 / 没凭据时只在这一步才报错。
        """
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - exercised only without SDK
            raise RuntimeError(
                "the 'anthropic' package is required for the VLM reviewer; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        client = anthropic.Anthropic(**self.config.anthropic_kwargs(self.name))
        # Anthropic 走 base64 内嵌图;png_path 完整读一遍再编码
        b64 = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
        # 只把 VLM 真正需要的字段塞进 plan 摘要,避免 token 浪费;
        # 具体地:prompt / task_type / backend / size / checks——它要靠
        # checks 知道"该判断图像满足哪些条件"
        plan_summary = plan.model_dump_json(
            include={"prompt", "task_type", "backend", "size", "checks"}
        )
        message = client.messages.create(
            model=self.config.reviewer_model,
            max_tokens=1024,
            system=_VLM_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": f"Plan: {plan_summary}"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64,
                            },
                        },
                    ],
                }
            ],
        )
        # message.content 是多模态块列表,只取文本块拼起来
        return "".join(
            b.text for b in message.content if getattr(b, "type", None) == "text"
        )


def _parse_result(raw: str) -> ReviewResult:
    """Parse the VLM's JSON verdict; a malformed verdict fails closed.

    解析 VLM 的 JSON 裁决,解析失败时 fail closed(返回 passed=False),
    避免模型偶尔吐出非 JSON 文字时被当成功——这是感知层安全网。
    """
    s = raw.strip()
    # 宽松地找最外层 { ... };防御 VLM 在 JSON 前后加废话的情况
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        return ReviewResult(
            passed=False, score=0.0, failures=[f"VLM returned no JSON verdict: {raw[:200]}"]
        )
    try:
        data = json.loads(s[start : end + 1])
    except json.JSONDecodeError as exc:
        return ReviewResult(
            passed=False, score=0.0, failures=[f"VLM verdict was not valid JSON: {exc}"]
        )
    # 显式把 None / 缺字段都收紧到默认值,不让模型漏字段就崩
    return ReviewResult(
        passed=bool(data.get("passed", False)),
        score=float(data.get("score", 0.0)),
        failures=list(data.get("failures", [])),
        warnings=list(data.get("warnings", [])),
    )
