"""Mock 图像生成器（plan task 9）。

把 code sketch 原封不动复制成 ``final.png`` 并记录 metadata。fixture 路径
**显式声明**不提供写实——它只验证生成步骤的契约与 artifact 链,完全不依赖
任何 provider 凭据（ADR 0004）。外部 provider（默认 Gemini-Flash-Image per
ADR 0004）放在 :mod:`genclaw.generators.external`,core 永远不 import 它。
"""

# 中文补充说明：
# mock 生成器存在的意义不在于「看起来真」,而在于:
#   1. 端到端打通 pipeline（agent -> render -> generate -> review）
#   2. 不需要任何凭据 -> CI、离线开发、教学示例都能跑
#   3. 给 real provider 当「对照」：当 mock 跑过但 real 失败时,问题一定
#      出在 network/SDK/凭据/输入 sketch 上,不在编排本身。

from __future__ import annotations

import shutil
from pathlib import Path

from genclaw.generators.base import GenerationResult, ImageGenerator


class MockImageGenerator(ImageGenerator):
    """把 sketch 原样当 final 返回(不写实)。"""

    name = "mock"

    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if sketch_path.exists():
            shutil.copyfile(sketch_path, output_path)
        else:
            # 某些 phase-1 场景没有 PNG（如无浏览器时 HTML/SVG renderer 不
            # 做光栅化）：写一个空文件占位,让 artifact 路径「存在」,
            # 失败模式显式可见,而不是 review 时默默以为图存在。
            output_path.write_bytes(b"")

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "prompt": prompt,
                "constraints": constraints or {},
                "note": (
                    "fixture/mock mode: final image is a copy of the code sketch; "
                    "no photorealistic generation is performed"
                ),
                "sketch_existed": sketch_path.exists(),
            },
        )
