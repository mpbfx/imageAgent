"""artifact 优先的 run 目录管理。

按项目"artifact 优先"原则(ADR 0001),每次 run 都写一个完整、自包含
的目录,这样审查者可以检查整条 pipeline 而不用重跑。run 目录位于::

    outputs/runs/<timestamp>_<request_id>_v<version>/
        request.json    # 原始请求(prompt、任务类型、选项)
        plan.json       # 校验过的 CanvasPlan
        canvas.svg      # 编译出来的可执行画布(后端不同扩展名也不同)
        canvas.html
        sketch.png      # code sketch 光栅化成的 PNG
        final.png       # 生成器基于 sketch 补全的最终图
        review.json     # ReviewResult
        trace.jsonl     # 每个 pipeline 阶段一条 JSON 对象(见 tracing.py)

目录名规范: <timestamp>_<request_id>_v<version>
  * timestamp: YYYYMMDD_HHmmss 格式,便于时间排序
  * request_id: 由 prompt slug + counter 组成
  * version: v001 起始,预留给未来的重试 / 重建机制

``RunArtifacts`` 只管*路径和 IO*;它不认 schema、renderer、provider。
路径属性在 run 生命周期内稳定,所以每个节点都写到同一个地方。

本模块无第三方依赖,无需浏览器或 provider 凭据即可 import。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

# 文件名是固定的,审查者随时知道去哪儿看(ADR 0001)。
REQUEST_JSON = "request.json"
PLAN_JSON = "plan.json"
SKETCH_PNG = "sketch.png"
FINAL_PNG = "final.png"
REVIEW_JSON = "review.json"
TRACE_JSONL = "trace.jsonl"

# 每个 backend 对应的画布文件扩展名。``canvas.<ext>`` 是可执行源码。
_CANVAS_EXT = {"svg": "svg", "html": "html", "three": "html"}


def _sanitize(component: str) -> str:
    """把字符串处理成可放进目录名的安全形态。

    request id 和 timestamp 都要落到 Windows 路径上,所以把所有不是字母
    数字、dash、点、下划线的字符都剔掉。
    """
    safe = "".join(c if (c.isalnum() or c in "-._") else "-" for c in component)
    return safe.strip("-") or "run"


@dataclass(frozen=True)
class RunArtifacts:
    """负责一次 pipeline run 的磁盘布局。

    用 :meth:`create` 构造(它会建目录)。路径属性都是纯函数、稳定的;
    构造后不会再重新派生或移动路径。
    """

    run_dir: Path
    request_id: str

    @classmethod
    def create(
        cls,
        base_dir: Union[str, Path],
        request_id: str,
        timestamp: str,
    ) -> "RunArtifacts":
        """建目录 ``<base_dir>/<timestamp>_<request_id>_v001/`` 并返回句柄。

        ``timestamp`` 由调用方注入(不读时钟),保证 run 可复现。格式为 YYYYMMDD_HHmmss。
        目录名规范: <timestamp>_<request_id>_v<version>，便于排序与版本管理。
        """
        name = f"{_sanitize(timestamp)}_{_sanitize(request_id)}_v001"
        run_dir = Path(base_dir) / name
        run_dir.mkdir(parents=True, exist_ok=True)
        return cls(run_dir=run_dir, request_id=request_id)

    # --- 稳定的路径访问器 -----------------------------------------------------

    @property
    def request_path(self) -> Path:
        return self.run_dir / REQUEST_JSON

    @property
    def plan_path(self) -> Path:
        return self.run_dir / PLAN_JSON

    @property
    def sketch_path(self) -> Path:
        return self.run_dir / SKETCH_PNG

    @property
    def final_path(self) -> Path:
        return self.run_dir / FINAL_PNG

    @property
    def review_path(self) -> Path:
        return self.run_dir / REVIEW_JSON

    @property
    def trace_path(self) -> Path:
        return self.run_dir / TRACE_JSONL

    def canvas_path(self, backend: str) -> Path:
        """``backend`` 对应可执行画布源码的路径。"""
        ext = _CANVAS_EXT.get(backend, backend)
        return self.run_dir / f"canvas.{ext}"

    def error_path(self, stage: str) -> Path:
        """某 ``stage`` 失败时,结构化 error artifact 的路径。

        provider / backend 失败时必须在这里留一条结构化 error,不能
        吞上下文(ADR 0001)。
        """
        return self.run_dir / f"error.{_sanitize(stage)}.json"

    # --- IO 助手 --------------------------------------------------------------

    def write_json(self, path: Path, data: Any) -> Path:
        """把 ``data`` 写成 UTF-8 JSON(保留非 ASCII,不转义)。"""
        text = json.dumps(data, ensure_ascii=False, indent=2, default=str)
        path.write_text(text, encoding="utf-8")
        return path

    def write_text(self, path: Path, text: str) -> Path:
        path.write_text(text, encoding="utf-8")
        return path

    def write_error(self, stage: str, message: str, detail: Optional[Any] = None) -> Path:
        """为 ``stage`` 落一条结构化 error artifact。"""
        return self.write_json(
            self.error_path(stage),
            {"stage": stage, "error": message, "detail": detail},
        )
