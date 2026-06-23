"""Provider 配置:环境变量名、默认模型、错误类型。

外部 provider 是可插拔的 adapter(ADR 0004)。*默认*栈与论文对齐——以
Claude-Opus 作为 agent / VLM 骨干,Gemini-Flash-Image 作为生成器,
SAM3 做分割——同时提供开源替代作为兜底。本模块不 import 任何厂商 SDK;
adapter 自己懒加载 SDK,这样即使一个都没装,核心包也能正常 import。

凭据来自环境变量。当必需的环境变量缺失时,adapter 抛
:class:`ProviderNotConfiguredError`,错误里带变量名和简短的设置提示,
而不是深陷到 SDK 调用里失败。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# --- environment variable names ------------------------------------------------
# 这一段集中定义所有"环境变量名字符串"。adapter 从环境变量读取凭据/配置,
# 改这里的字符串会改变用户需要设置的环境变量名,改名后文档与 .env 也要同步。

ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"  # Anthropic(Claude)API key 的环境变量名
ENV_GOOGLE_KEY = "GOOGLE_API_KEY"  # Google(Gemini)API key 的环境变量名

# 可选:Anthropic / Gemini 兼容代理网关的 base_url(自建或第三方中转)。
# 不设则用各 SDK 默认官方端点。可同时配这两个指向同一个代理(同时支持
# 两种协议)。国内被墙或走中转时在这里指向代理。
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"  # Claude 自定义 base_url 的环境变量名
ENV_GOOGLE_BASE_URL = "GOOGLE_BASE_URL"  # Gemini 自定义 base_url 的环境变量名

# 可选:OpenAI 兼容的 API 端点(如 UniAPI、LM Studio、vLLM 等)
ENV_OPENAI_KEY = "OPENAI_API_KEY"  # OpenAI 兼容 provider 的 API key
ENV_OPENAI_BASE_URL = "OPENAI_BASE_URL"  # OpenAI 兼容 provider 的自定义端点(如 https://api.uniapi.io/v1)
ENV_UNIAPI_KEY = "UNIAPI_API_KEY"  # UniAPI 专用 key
ENV_UNIAPI_BASE_URL = "UNIAPI_BASE_URL"  # UniAPI 专用 endpoint

# 可选:用环境变量覆盖下面的默认模型名(不设则用默认)。
ENV_AGENT_MODEL = "GENCLAW_AGENT_MODEL"  # 覆盖 agent/认知层模型
ENV_REVIEWER_MODEL = "GENCLAW_REVIEWER_MODEL"  # 覆盖审查者模型
ENV_GENERATOR_MODEL = "GENCLAW_GENERATOR_MODEL"  # 覆盖图像生成器模型

# --- default models (paper-aligned stack, ADR 0004) ----------------------------
# 严格匹配论文实验设置(§4.1):agent 骨干 Claude-Opus-4.6,默认生成器
# Gemini-3.1-Flash-Image。可用上面环境变量覆盖。记录下精确 id,让复现栈可审计。
# 默认模型 = 论文实验栈(ADR 0004)。下面三个字符串是"可调参数"。
# 注意:换模型不仅改名字,对应 adapter 必须支持该模型/该 provider,否则调用会失败。
DEFAULT_AGENT_MODEL = "claude-opus-4-6"  # ← 可改:认知层(prompt→CanvasPlan)用的 backbone 模型
DEFAULT_REVIEWER_MODEL = "claude-opus-4-6"  # ← 可改:审查层 VLM 模型(默认与 agent 同款)
DEFAULT_GENERATOR_MODEL = "gemini-3.1-flash-image"  # ← 可改:给草图上色/补全的图像生成模型

# 结构化输出(LLM 产出的 JSON)解析失败时的有界修复重试(plan task 14):
# 1 次初始尝试 + 本值次修复重试,超过则抛结构化 error 而非裸异常。
# ← 可改:调大更能容忍模型输出畸形 JSON,但每次重试都多花一次 LLM 调用(更慢更贵);
#   总尝试 = 1 次初始 + 本值次修复;超过后写出结构化 error 而非抛裸异常。
DEFAULT_MAX_PARSE_RETRIES = 2


class ProviderNotConfiguredError(RuntimeError):
    """某个外部 provider 缺少必需凭据/配置时抛出。"""

    # 当某个 provider 缺少必需凭据时抛出。携带 provider 名、缺失的环境变量名和提示,
    # 这样错误能在调用早期清晰报出,而不是深陷在 SDK 内部报一个看不懂的异常。
    def __init__(self, provider: str, env_var: str, hint: str = ""):
        self.provider = provider
        self.env_var = env_var
        msg = (
            f"provider {provider!r} is not configured: set the {env_var} "
            f"environment variable"
        )
        if hint:
            msg += f". {hint}"
        super().__init__(msg)


@dataclass(frozen=True)
class ProviderConfig:
    """Resolved configuration for the external stack."""

    # 解析后的 provider 配置(不可变)。一次 run 通常构造一份贯穿始终。
    # 各字段:None 表示未配置该凭据;model 字段已带默认值。
    anthropic_api_key: str | None = None  # Claude key(缺则调用 Claude 时报错)
    anthropic_base_url: str | None = None  # Claude 自定义端点(走代理时用)
    google_api_key: str | None = None  # Gemini key(缺则调用图像生成时报错)
    google_base_url: str | None = None  # Gemini 自定义端点(走代理时用)
    uniapi_api_key: str | None = None  # UniAPI key(用于 OpenAI 兼容调用)
    uniapi_base_url: str | None = None  # UniAPI 自定义端点
    agent_model: str = DEFAULT_AGENT_MODEL  # 认知层模型名(默认见上方常量)
    reviewer_model: str = DEFAULT_REVIEWER_MODEL  # 审查层模型名
    generator_model: str = DEFAULT_GENERATOR_MODEL  # 图像生成器模型名
    max_parse_retries: int = DEFAULT_MAX_PARSE_RETRIES  # 结构化解析修复重试次数

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ProviderConfig":
        """从环境变量解析配置(默认读 ``os.environ``)。"""
        # 从环境变量装配配置。env 参数主要给测试注入假环境用;生产传 None 即读 os.environ。
        # 注意:这里没读 max_parse_retries 的环境变量,改这个值需直接构造 ProviderConfig。
        e = os.environ if env is None else env
        return cls(
            anthropic_api_key=e.get(ENV_ANTHROPIC_KEY),
            anthropic_base_url=e.get(ENV_ANTHROPIC_BASE_URL),
            google_api_key=e.get(ENV_GOOGLE_KEY),
            google_base_url=e.get(ENV_GOOGLE_BASE_URL),
            uniapi_api_key=e.get(ENV_UNIAPI_KEY),
            uniapi_base_url=e.get(ENV_UNIAPI_BASE_URL),
            agent_model=e.get(ENV_AGENT_MODEL, DEFAULT_AGENT_MODEL),
            reviewer_model=e.get(ENV_REVIEWER_MODEL, DEFAULT_REVIEWER_MODEL),
            generator_model=e.get(ENV_GENERATOR_MODEL, DEFAULT_GENERATOR_MODEL),
        )

    def anthropic_kwargs(self, provider: str) -> dict:
        """Client kwargs for the Anthropic SDK (api_key + optional base_url)."""
        # 拼装传给 Anthropic SDK 构造函数的关键字参数:必带 api_key,有 base_url 才加。
        kwargs = {"api_key": self.require_anthropic(provider)}
        if self.anthropic_base_url:
            kwargs["base_url"] = self.anthropic_base_url
        return kwargs

    def require_anthropic(self, provider: str) -> str:
        # 取 Claude key,缺失则抛 ProviderNotConfiguredError(带申请链接与安装提示)。
        if not self.anthropic_api_key:
            raise ProviderNotConfiguredError(
                provider,
                ENV_ANTHROPIC_KEY,
                "create a key at https://console.anthropic.com/ and "
                "install the 'providers' extra (pip install -e \".[providers]\").",
            )
        return self.anthropic_api_key

    def require_google(self, provider: str) -> str:
        # 取 Gemini key,缺失则抛 ProviderNotConfiguredError(带申请链接与安装提示)。
        if not self.google_api_key:
            raise ProviderNotConfiguredError(
                provider,
                ENV_GOOGLE_KEY,
                "create a key at https://aistudio.google.com/apikey and "
                "install the 'providers' extra (pip install -e \".[providers]\").",
            )
        return self.google_api_key

    def uniapi_kwargs(self, provider: str) -> dict:
        """以 UniAPI 端点构造 OpenAI SDK 客户端的关键字参数。"""
        # 拼装传给 OpenAI SDK 构造函数的关键字参数。UniAPI 兼容 OpenAI API。
        kwargs = {"api_key": self.require_uniapi(provider)}
        if self.uniapi_base_url:
            kwargs["base_url"] = self.uniapi_base_url
        return kwargs

    def require_uniapi(self, provider: str) -> str:
        # 取 UniAPI key,缺失则抛 ProviderNotConfiguredError。
        if not self.uniapi_api_key:
            raise ProviderNotConfiguredError(
                provider,
                ENV_UNIAPI_KEY,
                "set UNIAPI_API_KEY and UNIAPI_BASE_URL in .env and "
                "install the 'providers' extra (pip install -e \".[providers]\").",
            )
        return self.uniapi_api_key
