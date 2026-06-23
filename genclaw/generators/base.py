"""图像生成器接口 + ``GenerationResult`` 数据载体。

「视觉生成层」(paper §3.3) 把 code sketch 当作视觉条件,调用图像生成/编辑
provider 去补足材质、纹理、光照。本模块只定义契约和结果类型;mock 生成器
(task 9) 和外部 provider (task 14) 在同级模块。外部 provider 的配置不进
core（ADR 0004 强调）。
"""

# 中文补充说明：
# 本文件是「视觉生成层」的最薄契约层。它刻意只做两件事：
#   1. 定义 ``ImageGenerator`` 抽象基类（固定 generate 签名）
#   2. 定义 ``GenerationResult``（产物路径 + provider + sketch 路径 + metadata）
# 这样所有具体 provider（mock / Gemini / OpenAI 兼容 / TeleImage SSH）都能
# 以同一接口接入,pipeline 编排层不用关心底层差异。

from __future__ import annotations

import abc
from pathlib import Path

from pydantic import BaseModel, Field


class GenerationResult(BaseModel):
    """生成步骤的输出。

    ``final_path`` 是最终的成图; ``metadata`` 记录 provider 和输入,reviewer
    能看到成图是怎么产生的; mock provider 会显式标注「fixture 模式不提供
    写实」,避免有人误以为它是真图。
    """

    final_path: Path
    provider: str
    sketch_path: Path
    metadata: dict = Field(default_factory=dict)


class ImageGenerator(abc.ABC):
    """把 code sketch「补」成最终图像的 provider。"""

    name: str

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        """从 ``sketch_path`` 出发,产出 ``output_path``,返回结果。"""
        raise NotImplementedError
