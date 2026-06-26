from pathlib import Path

from genclaw.artifacts import RunArtifacts
from genclaw.generators.base import GenerationResult
from genclaw.graph.nodes import GraphNodes
from genclaw.graph.state import GenClawState
from genclaw.renderers.base import RenderedCanvas
from genclaw.schemas import CanvasBackend, CanvasPlan, CanvasSize, CanvasSource, TaskType


class RecordingGenerator:
    name = "recording"

    def __init__(self):
        self.constraints = None

    def generate(self, prompt, sketch_path, output_path, constraints=None):
        self.constraints = dict(constraints or {})
        Path(output_path).write_bytes(b"fake")
        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
        )


def test_generate_passes_backend_source_and_code_lang_constraints(tmp_path):
    sketch = tmp_path / "sketch.png"
    sketch.write_bytes(b"fake")
    canvas = tmp_path / "canvas.svg"
    canvas.write_text("<svg></svg>", encoding="utf-8")
    artifacts = RunArtifacts.create(tmp_path / "runs", "req", "20260625_160000")
    plan = CanvasPlan(
        request_id="req",
        prompt="一张卡通信息图",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        size=CanvasSize(width=100, height=100),
        source=CanvasSource.code,
        code_lang="svg",
        code_source="<svg></svg>",
    )
    state = GenClawState(
        request_id="req",
        prompt=plan.prompt,
        plan=plan,
        artifacts=artifacts,
        rendered_canvas=RenderedCanvas(
            backend=CanvasBackend.svg,
            source_path=canvas,
            png_path=sketch,
            width=100,
            height=100,
        ),
    )
    generator = RecordingGenerator()
    nodes = GraphNodes(agent=None, generator=generator, reviewer=None)

    nodes.generate(state)

    assert generator.constraints == {
        "task_type": "composition",
        "backend": "svg",
        "source": "code",
        "code_lang": "svg",
    }
