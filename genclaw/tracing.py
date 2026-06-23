"""append-only JSONL trace 写入器。

每个 LangGraph 节点执行完后必须追加一条 trace 事件(plan task 3),
至少记录:节点名、输入摘要、输出产物路径、错误摘要。trace 用 JSON
Lines 格式写入,这样可以增量检查、且对中途崩溃健壮——已经写下的
部分都还在磁盘上。

写入器刻意保持极小、零依赖。除了 JSON 序列化之外它不解释 ``data``,
所以事件的具体形状由调用方自己定。timestamp 由调用方注入(不读
时钟),保证 run 的确定性和可复现性。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union


@dataclass
class TraceWriter:
    """向 trace 文件追加 JSON Lines。

    第一次写入时如果父目录不存在会自动创建,所以 run 目录还没建好
    时就构造这个 writer 也是安全的。
    """

    path: Path
    # 单次 run 内单调递增的序号;即使 timestamp 撞了或没传,事件也有
    # 一个全序。
    _seq: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def append(
        self,
        stage: str,
        data: Optional[dict] = None,
        *,
        timestamp: Optional[str] = None,
    ) -> dict:
        """追加一条 ``stage`` 事件,返回写入的记录。

        ``data`` 会合并进记录;保留键(``seq`` / ``stage`` / ``ts``)
        永远以写入器为准,事件信封保持一致。
        """
        record: dict[str, Any] = dict(data or {})
        record["seq"] = self._seq
        record["stage"] = stage
        if timestamp is not None:
            record["ts"] = timestamp
        self._seq += 1

        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return record

    def append_node(
        self,
        node: str,
        *,
        input_summary: Any = None,
        artifacts: Optional[Union[list, dict]] = None,
        error: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> dict:
        """标准节点 trace 形状的便捷包装(plan task 3)。

        记录节点名、输入摘要、输出产物路径、错误摘要。``artifacts``
        里的路径会被字符串化,便于跨平台读。
        """
        if isinstance(artifacts, dict):
            arts: Any = {k: str(v) for k, v in artifacts.items()}
        elif artifacts is not None:
            arts = [str(p) for p in artifacts]
        else:
            arts = None
        return self.append(
            node,
            {
                "node": node,
                "input_summary": input_summary,
                "artifacts": arts,
                "error": error,
            },
            timestamp=timestamp,
        )

    def read_events(self) -> list[dict]:
        """把 trace 文件解析回事件列表(供检查用)。"""
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                events.append(json.loads(line))
        return events
