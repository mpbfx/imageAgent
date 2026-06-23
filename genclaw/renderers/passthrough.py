"""Passthrough renderer:不画代码草图,直接交给图像生成层。

对于纯写实 / 审美类 prompt(如"电影感的霓虹灯管照片""风景中的某款车"),
代码画布(SVG/HTML/Three.js)提供的结构控制收益很低——这类任务的价值在
材质、光照、氛围,而非对象计数或精确布局。强行生成 Three.js 草图反而会给
下游图像模型一个粗糙的 3D 渲染当条件,可能拖累成图质量。

Passthrough 后端因此*不*编译任何代码,只产出一张中性空白画布作为 sketch:
- 若 generate 阶段下载到了真实参考图(plan.knowledge 里的 image_url),
  会用参考图替换这张空白画布,走 img2img;
- 若没有参考图,空白画布 + 强 rerender ≈ 纯文生图。

这样既复用了现有 generate 节点的 sketch 接口,又不引入"代码草图噪音"。
"""

from __future__ import annotations

from pathlib import Path

from genclaw.renderers.base import RenderedCanvas, Renderer
from genclaw.schemas import CanvasBackend, CanvasPlan


class PassthroughRenderer(Renderer):
    """产出中性空白画布,把视觉生成完全交给图像 provider。"""

    backend = CanvasBackend.passthrough

    def render(self, plan: CanvasPlan, output_dir: Path) -> RenderedCanvas:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        w, h = plan.size.width, plan.size.height

        # source 落一份占位说明,便于审查者理解为何没有 canvas 代码。
        source_path = output_dir / "canvas.txt"
        source_path.write_text(
            "passthrough backend: no canvas code generated; "
            "image generation works from prompt (+ optional reference image).\n",
            encoding="utf-8",
        )

        # passthrough 不需要 sketch 图：参考图由 generate 节点从 knowledge 下载，
        # 若无参考图则生成器做纯文生图。不产出灰色占位图，避免混淆。
        return RenderedCanvas(
            backend=CanvasBackend.passthrough,
            source_path=source_path,
            png_path=None,
            width=w,
            height=h,
        )
