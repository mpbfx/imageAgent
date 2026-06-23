"""外部 LLM agent:prompt -> 经过校验的 CanvasPlan（plan task 14）。

这是真正的「认知结构化层」（paper §3.1）——对自由格式 prompt 做意图识别,
与基于关键词匹配的 :class:`~genclaw.agent.fixture.FixtureAgent` 相对。
默认后端为 Claude-Opus（ADR 0004）。

整个架构的关键支点是「prompt -> CanvasPlan」这个契约,所以本模块的
核心目标是「可靠性」:

* 强约束让模型按 CanvasPlan schema 输出 JSON（通过 provider 的
  structured-output / tool mode）。
* 一旦 Pydantic 校验失败,把错误信息回喂给模型,要求它修复,最多重试
  ``max_parse_retries`` 轮。
* 仍然失败则抛 :class:`PlanParseError`,把所有尝试历史都带出来,让
  调用方能写一份结构化的错误 artifact——绝不静默吞掉,绝不返回半成品。

模型调用本身被隔离在 :meth:`_complete` 中,所以 parse/repair 循环可以
在没有 SDK、没有凭据的情况下做单测（见测试中注入一条坏 JSON 响应、验证
重试+终态行为的用例）。
"""

# 中文补充说明：
# 本文件是「真实可用的认知结构化层」。它与 fixture agent 的区别在于：
#   - 真正调用大模型（默认 Anthropic Claude,也可走 OpenAI 兼容协议）
#   - 容错：模型可能吐非 JSON、可能字段不齐、可能语义不合法。本模块用
#     「重试 + 错误回喂」的方式逼模型自我修正,而不是放宽校验。
# 替换 / 扩展建议：若要换模型或加新 provider,只要继承 ExternalLLMAgent
# 并重写 _complete 即可；contractualize 入口（处理 system/user 提示组装、
# 重试循环、JSON 抽取、Pydantic 校验）已经通用化,不必再改。

from __future__ import annotations

import json
from typing import Optional

from pydantic import ValidationError

from genclaw.agent.base import AgentProvider
from genclaw.agent.prompts import (
    CODE_DEVELOPER_PROMPT,
    CODE_SYSTEM_PROMPT,
    DEVELOPER_PROMPT,
    REPAIR_PROMPT,
    SYSTEM_PROMPT,
)
from genclaw.config import ProviderConfig
from genclaw.schemas import CanvasPlan, TaskType

GLM_AGENT_MAX_TOKENS = 8192


def _should_knowledge_ground(prompt: str) -> bool:
    """启发式判断 prompt 是否涉及知识密集型任务（需要搜索补齐）。

    检测特征：
    - 时间敏感（年份、"最新"、"最近"、"今年"等）
    - 具体实体（地名、人名、品牌、电影等）
    - 文化符号（节日、传统、习俗）
    - 新闻/事件性（发生、举办、比赛等）

    这个启发式会在 Phase 2 被替换为更复杂的意图识别。
    """
    keywords = [
        # 时间敏感
        "2026", "2025", "2024", "最新", "最近", "今年", "去年", "明年",
        "当前", "最新", "实时", "新闻",
        # 地理/地点
        "城市", "街景", "地点", "国家", "地区", "场景", "街道",
        # 文化/事件
        "节日", "传统", "风俗", "习俗", "文化", "活动", "比赛", "竞赛",
        "世界杯", "奥运", "展览", "庆典",
        # 具体实体（需要外部知识）
        "品牌", "餐厅", "电影", "人物", "名人", "历史人物",
        # 专业领域
        "科学", "数学", "物理", "化学", "医学", "法律",
        # 食物/菜品（需要准确信息）
        "菜单", "菜品", "食谱", "料理",
    ]

    prompt_lower = prompt.lower()
    # 只要匹配到任何关键词，就认为需要知识补齐
    for kw in keywords:
        if kw in prompt_lower:
            return True
    return False


class PlanParseError(RuntimeError):
    """在 ``max_parse_retries`` 预算内仍无法产出合法 CanvasPlan 时抛出。

    携带全部尝试历史 + 最后一次错误,便于调用方写结构化错误 artifact
    或把现场（attempts / last_error）回灌给运维/调试。
    """

    def __init__(self, attempts: list[str], last_error: str):
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"agent failed to produce a valid CanvasPlan after {len(attempts)} "
            f"attempt(s); last error: {last_error}"
        )


def _format_knowledge(knowledge: Optional[list], max_refs: int = 3) -> str:
    """把 pre-search 检索到的 KnowledgeRef 格式化成可注入 prompt 的文本块。

    只取前 ``max_refs`` 条、每条 claim 截到 150 字——够 LLM 抓住关键外观
    特征即可,无需全文注入(会增大 prompt 负担)。
    """
    if not knowledge:
        return ""
    lines = [
        "",
        "REFERENCE FACTS (top search results for the named entity; use these",
        "to depict its REAL appearance instead of guessing):",
    ]
    for ref in list(knowledge)[:max_refs]:
        claim = (getattr(ref, "claim", None) or "").strip().replace("\n", " ")
        claim = claim[:150] + ("..." if len(claim) > 150 else "")
        if not claim:
            continue
        source = getattr(ref, "source", None)
        lines.append(f"- {claim}" + (f" [{source}]" if source else ""))
    lines.append("")
    return "\n".join(lines)


def _extract_json(text: str) -> str:
    """尽力从模型返回里抽出最外层 JSON 对象。

    处理三种常见「污染」:
      1. 包裹在 ```json ... ``` 三个反引号代码块里——剥掉首尾 fence。
      2. JSON 前后有多余解释文字——用首个 { 与末个 } 切出对象。
    对极端的混合输出（多个对象、嵌套错误）只取最外层一对花括号,够用即可。
    """
    s = text.strip()
    if s.startswith("```"):
        # 剥掉开头的 fence（``` 或 ```json）和结尾的 ```。
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    s = s.strip()
    start, end = s.find("{"), s.rfind("}")
    if start != -1 and end != -1 and end > start:
        return s[start : end + 1]
    return s


class ExternalLLMAgent(AgentProvider):
    """LLM 驱动的 agent,带有限次 structured-output 自修复。

    子类/provider 通过重写 :meth:`_complete` 接入任意模型 SDK；
    默认实现调用 Anthropic Claude（与论文对齐），并采用懒加载
    导入,因此即使没装 SDK,这个类也可以在测试里被实例化。
    """

    def __init__(self, config: Optional[ProviderConfig] = None, *, code_mode: bool = False):
        self.config = config or ProviderConfig.from_env()
        # code_mode=True 时让 LLM 直接写 SVG 源码（ADR 0005, code-as-brush），
        # 而不是返回结构化字段再让模板编译——画笔本身就是代码。
        self.code_mode = code_mode

    # --- 公开契约 ---------------------------------------------------------------

    def conceptualize(
        self,
        prompt: str,
        task_type: Optional[TaskType] = None,
        request_id: Optional[str] = None,
        knowledge: Optional[list] = None,
    ) -> CanvasPlan:
        rid = request_id or "llm"
        tt = task_type.value if task_type else "infer the most appropriate one"
        # pre-search 检索到的事实,注入 prompt 让 LLM 写代码时能参考真实外观。
        knowledge_context = _format_knowledge(knowledge)
        # 根据 code_mode 选不同 prompt 模板：模板里有「返回 JSON」还是
        # 「返回 code_source 字段」的关键区别。
        if self.code_mode:
            system = CODE_SYSTEM_PROMPT
            user = CODE_DEVELOPER_PROMPT.format(
                task_type=tt, request_id=rid, prompt=prompt, knowledge_context=knowledge_context
            )
        else:
            system = SYSTEM_PROMPT
            user = DEVELOPER_PROMPT.format(
                task_type=tt, request_id=rid, prompt=prompt, knowledge_context=knowledge_context
            )

        attempts: list[str] = []
        last_error = ""
        # 1 次初次尝试 + 最多 max_parse_retries 次修复尝试。
        for attempt in range(self.config.max_parse_retries + 1):
            if attempt == 0:
                raw = self._complete(system, user)
            else:
                # 把上一次的原始输出 + 校验错误一起回喂给模型,让它在
                # 同一会话上下文里自我修正——大多数 Pydantic 错误（缺字段、
                # 类型不对、枚举值不合法）都能被模型一次修正。
                repair = REPAIR_PROMPT.format(errors=last_error, previous=attempts[-1])
                raw = self._complete(system, user + "\n\n" + repair)
            attempts.append(raw)

            try:
                data = json.loads(_extract_json(raw))
            except json.JSONDecodeError as exc:
                last_error = f"response was not valid JSON: {exc}"
                continue

            # 兜底: 必填的身份字段如果模型没填就补上。prompt 是事实来源,
            # 而不是模型「猜」——这是为了让 artifact 真实可追溯。
            data.setdefault("request_id", rid)
            data.setdefault("prompt", prompt)
            if task_type is not None:
                data["task_type"] = task_type.value
            else:
                # 如果没有显式指定 task_type，用启发式判断是否需要知识补齐。
                # 这是对论文「智能体主动判断是否搜索」的简化实现（Phase 1）。
                if _should_knowledge_ground(prompt):
                    data.setdefault("task_type", TaskType.knowledge_grounded.value)

            try:
                return CanvasPlan.model_validate(data)
            except ValidationError as exc:
                # 校验失败不立即抛——记下错误,等下一轮重试时回喂给模型。
                last_error = str(exc)
                continue

        raise PlanParseError(attempts, last_error)

    # --- provider boundary -----------------------------------------------------

    def _complete(self, system: str, user: str) -> str:
        """调用 LLM 后端并返回原始文本。

        同时支持 Anthropic（Claude）和 OpenAI 兼容 provider（UniAPI 等）。
        若设置了 UNIAPI_API_KEY 就走 OpenAI SDK,否则走 Anthropic SDK。
        懒加载导入：未安装 SDK 时,会在调到这里再抛错,而不是 import 时。
        """
        # 优先走 UniAPI (OpenAI 兼容),适合国内/自建代理场景。
        if self.config.uniapi_api_key:
            return self._complete_openai_compatible(system, user)

        # 退到 Anthropic Claude。
        return self._complete_anthropic(system, user)

    def _complete_openai_compatible(self, system: str, user: str) -> str:
        """调用 OpenAI 兼容 provider(UniAPI、LM Studio、vLLM 等)。"""
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "the 'openai' package is required for OpenAI-compatible agents; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        kwargs = self.config.uniapi_kwargs("openai-compatible-agent")
        client = OpenAI(**kwargs)

        # 检查是否是 UniAPI（通过 base_url 判断）
        is_uniapi = "uniapi" in str(self.config.uniapi_base_url).lower()
        is_glm = self.config.agent_model.lower().startswith("glm-")

        if is_uniapi and not is_glm:
            # UniAPI 使用独特的 responses.create() 接口
            try:
                combined_prompt = f"{system}\n\n{user}"
                response = client.responses.create(
                    model=self.config.agent_model,
                    input=combined_prompt,
                )
                return response.output_text or ""
            except AttributeError:
                # 回退到标准 chat.completions 接口
                pass

        # 标准 OpenAI 兼容接口
        max_tokens = GLM_AGENT_MAX_TOKENS if is_glm else 4096
        extra_body = (
            {"thinking": {"type": "disabled"}, "reasoning_effort": "none"}
            if is_glm
            else None
        )
        request_kwargs = {
            "model": self.config.agent_model,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if extra_body is not None:
            request_kwargs["extra_body"] = extra_body
        try:
            message = client.chat.completions.create(
                **request_kwargs,
                response_format={"type": "json_object"},
            )
        except (TypeError, Exception):
            # 如果 response_format 不支持，直接调用而不使用它
            message = client.chat.completions.create(**request_kwargs)

        return message.choices[0].message.content or ""

    def _complete_anthropic(self, system: str, user: str) -> str:
        """调用 Anthropic Claude 后端。"""
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "the 'anthropic' package is required for the Anthropic agent; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        client = anthropic.Anthropic(**self.config.anthropic_kwargs("anthropic-claude-agent"))
        message = client.messages.create(
            model=self.config.agent_model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        # Claude 返回的是 content 块列表(text / tool_use / image),这里只
        # 拼接 text 块,其它忽略——能跑通结构化 JSON 输出的对话。
        return "".join(
            block.text for block in message.content if getattr(block, "type", None) == "text"
        )
