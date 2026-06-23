# GenClaw 搜索集成指南

## 概述

GenClaw 已集成 **Serper** 搜索提供商，与 GenEvolve 兼容。搜索功能在 pipeline 的 `conceptualize` 之后、`render` 之前执行，仅对 `task_type=knowledge_grounded` 的任务生效。

## 架构

### SearchProvider 接口

所有搜索提供商实现统一接口（`genclaw/search.py`）：

```python
class SearchProvider(abc.ABC):
    name: str
    
    def search(self, query: str, *, max_results: int = 5) -> list[KnowledgeRef]:
        """返回查询结果，带溯源信息。"""
        raise NotImplementedError
    
    def should_search(self, prompt: str, task_type: Optional[TaskType]) -> bool:
        """启发式开关：只有 knowledge_grounded 任务才搜索。"""
```

### 可用提供商

| 提供商 | 类 | 环境变量 | 说明 |
|------|-----|--------|------|
| Null | `NullSearchProvider` | 无 | 空 stub，不消耗凭据（默认 fixture 模式）|
| Tavily | `TavilySearchProvider` | `TAVILY_API_KEY` | 多轮搜索（论文默认） |
| Serper | `SerperSearchProvider` | `SERPER_API_KEY` | 快速搜索，Serper 兼容（GenEvolve 栈） |

### 流程

```
conceptualize (agent 生成 CanvasPlan)
    ↓
search_node (检查 should_search，调用 provider，合并知识)
    ↓
render / generate / review
```

搜索结果存入 `state.plan.knowledge`（`list[KnowledgeRef]`），每条记录带 `claim`、`source`、`confidence`。

## 使用方式

### 1. 用 Serper（推荐）

注册 https://serper.dev，获得 API key。

**配置环境变量：**
```powershell
$env:SERPER_API_KEY="your_api_key_here"
```

**运行：**
```powershell
genclaw run --prompt "your prompt" --mode external --search-provider serper
```

**支持自定义后端：**
```powershell
$env:SERPER_API_KEY="your_key"
$env:SERPER_BASE_URL="https://your-searxng:8888"
genclaw run --prompt "..." --search-provider serper
```

### 2. 用 Tavily（论文默认）

注册 https://tavily.com，获得 API key。

```powershell
$env:TAVILY_API_KEY="your_api_key_here"
genclaw run --prompt "..." --mode external
```

### 3. 开发/测试（无凭据）

用 fixture 模式，搜索被禁用：

```powershell
genclaw run --prompt "three red circles" --mode fixture
```

### 4. 测试搜索功能

Python API：

```python
from genclaw.search import SerperSearchProvider
from genclaw.schemas import TaskType
from genclaw.pipeline import Pipeline

# 直接测试 provider
provider = SerperSearchProvider()  # 需要 SERPER_API_KEY
results = provider.search("菜单", max_results=3)
for ref in results:
    print(f"- {ref.claim[:70]}... ({ref.source})")

# 完整 pipeline 测试
pipeline = Pipeline.for_mode("fixture", search_provider="serper")
state = pipeline.run("菜单", task_type=TaskType.knowledge_grounded)
print(f"Found {len(state.plan.knowledge)} knowledge refs")
```

## 实现细节

### SerperSearchProvider

- **API 端点**：`POST {base_url}/search`
- **请求头**：`X-API-KEY: {SERPER_API_KEY}`, `Content-Type: application/json`
- **请求体**：`{"q": query, "num": max_results}`
- **响应解析**：`response["organic"]` → `list[KnowledgeRef]`

### 错误处理

- 搜索失败 **不会** 打断 pipeline（`fatal=False`）
- 失败信息记入 `state.errors` 和 error artifact
- 无凭据时抛 `ProviderNotConfiguredError`

## Fixture 扩展

Fixture agent 支持以下关键词：

| 关键词 | 任务类型 | 用途 |
|------|--------|------|
| `three red circles` | `composition` | SVG 对象计数测试 |
| `poster` | `long_text` | HTML 文本检测测试 |
| `mirror` | `physical_reasoning` | Three.js 物理场景测试 |
| `menu` 或 `菜单` | `knowledge_grounded` | **搜索功能测试** |

## CLI 参数

```
genclaw run [OPTIONS]

Options:
  --prompt TEXT                 自然语言请求 [required]
  --mode TEXT                   fixture | external | external-template | external-code
                                [default: fixture]
  --search-provider TEXT        tavily (默认) | serper
  --out PATH                    run 输出根目录 [default: outputs/runs]
  --max-revisions INTEGER       审查重试预算 [default: 1]
  --langgraph                   改用 LangGraph 驱动
```

## 代码位置

- **提供商实现**：`genclaw/search.py`
- **Pipeline 集成**：`genclaw/pipeline.py::build_providers()`
- **节点调用**：`genclaw/graph/nodes.py::GraphNodes.search_node()`
- **CLI 选项**：`genclaw/cli.py::run()`
- **测试**：`tests/test_search.py`
- **Fixture**：`genclaw/agent/fixture.py::_menu()`

## 常见问题

### Q: 为什么搜索没有被调用？
A: 检查 `task_type` 是否为 `knowledge_grounded`。其他任务类型的搜索会被跳过（见 `should_search()` 启发式）。

### Q: 怎么用自建搜索后端？
A: 任何 Serper 兼容的后端都可以：
```powershell
$env:SERPER_BASE_URL="http://localhost:8888"
genclaw run --prompt "..." --search-provider serper
```

### Q: Serper 免费配额是多少？
A: 免费账户通常 100 次/月。付费从 $5/月 起。详见 https://serper.dev

### Q: 可以混用多个搜索提供商吗？
A: 目前 pipeline 一次只用一个 provider。若要 multi-provider 搜索，需要自定义 provider 或修改 `search_node()`。

## 下一步（Phase 2）

- [ ] 图像搜索（对应 Serper `/images` 端点）
- [ ] 多轮搜索与反馈循环
- [ ] 结构化搜索查询（从 plan 提取关键词）
- [ ] 缓存与速率限制
