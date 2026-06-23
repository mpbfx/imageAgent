"""Provider configuration: env var names, default models, and errors.

External providers are pluggable adapters (ADR 0004). The *default* stack aligns
with the paper -- Claude-Opus as the agent/VLM backbone, Gemini-Flash-Image as
the generator, SAM3 for segmentation -- with open alternatives as fallbacks.
Nothing here imports a vendor SDK; adapters import their SDK lazily so the core
package works with none of them installed.

Credentials come from environment variables. When a required one is missing, an
adapter raises :class:`ProviderNotConfiguredError` with the variable name and a
short setup hint, rather than failing deep inside an SDK call.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# --- environment variable names ------------------------------------------------
# 这一段集中定义所有"环境变量名字符串"。adapter 从环境变量读取凭据/配置,
# 改这里的字符串会改变用户需要设置的环境变量名,改名后文档与 .env 也要同步。

ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"  # Anthropic(Claude)API key 的环境变量名
ENV_GOOGLE_KEY = "GOOGLE_API_KEY"  # Google(Gemini)API key 的环境变量名

# Optional custom endpoints for Anthropic-/Gemini-compatible proxies/gateways
# (e.g. a self-hosted or third-party relay). When unset, each SDK's default is
# used. A single proxy that speaks both protocols can be pointed at via both.
# 可选:自建/第三方代理网关地址。不设则用各 SDK 默认官方端点。
# 国内被墙或走中转时在这里指向代理(同一个兼容代理可同时填这两个变量)。
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"  # Claude 自定义 base_url 的环境变量名
ENV_GOOGLE_BASE_URL = "GOOGLE_BASE_URL"  # Gemini 自定义 base_url 的环境变量名

# Optional model overrides (else the defaults below are used).
# 可选:用环境变量覆盖下面的默认模型名(不设则用默认)。
ENV_AGENT_MODEL = "GENCLAW_AGENT_MODEL"  # 覆盖 agent/认知层模型
ENV_REVIEWER_MODEL = "GENCLAW_REVIEWER_MODEL"  # 覆盖审查者模型
ENV_GENERATOR_MODEL = "GENCLAW_GENERATOR_MODEL"  # 覆盖图像生成器模型

# --- default models (paper-aligned stack, ADR 0004) ----------------------------
# These match the paper's experimental setup exactly (§4.1): agent backbone
# Claude-Opus-4.6, default generator Gemini-3.1-Flash-Image. Override via the env
# vars above. The exact ids are recorded so the reproduction stack is auditable.
# 默认模型 = 论文实验栈(ADR 0004)。下面三个字符串是"可调参数"。
# 注意:换模型不仅改名字,对应 adapter 必须支持该模型/该 provider,否则调用会失败。
DEFAULT_AGENT_MODEL = "claude-opus-4-6"  # ← 可改:认知层(prompt→CanvasPlan)用的 backbone 模型
DEFAULT_REVIEWER_MODEL = "claude-opus-4-6"  # ← 可改:审查层 VLM 模型(默认与 agent 同款)
DEFAULT_GENERATOR_MODEL = "gemini-3.1-flash-image"  # ← 可改:给草图上色/补全的图像生成模型

# Bounded structured-output repair attempts (plan task 14). One initial attempt
# plus this many repair retries before giving up with a structured error.
# 结构化输出(LLM 产出的 JSON)解析失败时的额外修复重试次数。
# ← 可改:调大更能容忍模型输出畸形 JSON,但每次重试都多花一次 LLM 调用(更慢更贵);
#   总尝试 = 1 次初始 + 本值次修复;超过后写出结构化 error 而非抛裸异常。
DEFAULT_MAX_PARSE_RETRIES = 2


class ProviderNotConfiguredError(RuntimeError):
    """Raised when an external provider lacks required credentials/config."""

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
    agent_model: str = DEFAULT_AGENT_MODEL  # 认知层模型名(默认见上方常量)
    reviewer_model: str = DEFAULT_REVIEWER_MODEL  # 审查层模型名
    generator_model: str = DEFAULT_GENERATOR_MODEL  # 图像生成器模型名
    max_parse_retries: int = DEFAULT_MAX_PARSE_RETRIES  # 结构化解析修复重试次数

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ProviderConfig":
        """Resolve configuration from the environment (defaults to ``os.environ``)."""
        # 从环境变量装配配置。env 参数主要给测试注入假环境用;生产传 None 即读 os.environ。
        # 注意:这里没读 max_parse_retries 的环境变量,改这个值需直接构造 ProviderConfig。
        e = os.environ if env is None else env
        return cls(
            anthropic_api_key=e.get(ENV_ANTHROPIC_KEY),
            anthropic_base_url=e.get(ENV_ANTHROPIC_BASE_URL),
            google_api_key=e.get(ENV_GOOGLE_KEY),
            google_base_url=e.get(ENV_GOOGLE_BASE_URL),
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
