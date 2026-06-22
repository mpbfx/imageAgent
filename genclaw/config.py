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

ENV_ANTHROPIC_KEY = "ANTHROPIC_API_KEY"
ENV_GOOGLE_KEY = "GOOGLE_API_KEY"

# Optional custom endpoints for Anthropic-/Gemini-compatible proxies/gateways
# (e.g. a self-hosted or third-party relay). When unset, each SDK's default is
# used. A single proxy that speaks both protocols can be pointed at via both.
ENV_ANTHROPIC_BASE_URL = "ANTHROPIC_BASE_URL"
ENV_GOOGLE_BASE_URL = "GOOGLE_BASE_URL"

# Optional model overrides (else the defaults below are used).
ENV_AGENT_MODEL = "GENCLAW_AGENT_MODEL"
ENV_REVIEWER_MODEL = "GENCLAW_REVIEWER_MODEL"
ENV_GENERATOR_MODEL = "GENCLAW_GENERATOR_MODEL"

# --- default models (paper-aligned stack, ADR 0004) ----------------------------
# These match the paper's experimental setup exactly (§4.1): agent backbone
# Claude-Opus-4.6, default generator Gemini-3.1-Flash-Image. Override via the env
# vars above. The exact ids are recorded so the reproduction stack is auditable.
DEFAULT_AGENT_MODEL = "claude-opus-4-6"
DEFAULT_REVIEWER_MODEL = "claude-opus-4-6"
DEFAULT_GENERATOR_MODEL = "gemini-3.1-flash-image"

# Bounded structured-output repair attempts (plan task 14). One initial attempt
# plus this many repair retries before giving up with a structured error.
DEFAULT_MAX_PARSE_RETRIES = 2


class ProviderNotConfiguredError(RuntimeError):
    """Raised when an external provider lacks required credentials/config."""

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

    anthropic_api_key: str | None = None
    anthropic_base_url: str | None = None
    google_api_key: str | None = None
    google_base_url: str | None = None
    agent_model: str = DEFAULT_AGENT_MODEL
    reviewer_model: str = DEFAULT_REVIEWER_MODEL
    generator_model: str = DEFAULT_GENERATOR_MODEL
    max_parse_retries: int = DEFAULT_MAX_PARSE_RETRIES

    @classmethod
    def from_env(cls, env: dict | None = None) -> "ProviderConfig":
        """Resolve configuration from the environment (defaults to ``os.environ``)."""
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
        kwargs = {"api_key": self.require_anthropic(provider)}
        if self.anthropic_base_url:
            kwargs["base_url"] = self.anthropic_base_url
        return kwargs

    def require_anthropic(self, provider: str) -> str:
        if not self.anthropic_api_key:
            raise ProviderNotConfiguredError(
                provider,
                ENV_ANTHROPIC_KEY,
                "create a key at https://console.anthropic.com/ and "
                "install the 'providers' extra (pip install -e \".[providers]\").",
            )
        return self.anthropic_api_key

    def require_google(self, provider: str) -> str:
        if not self.google_api_key:
            raise ProviderNotConfiguredError(
                provider,
                ENV_GOOGLE_KEY,
                "create a key at https://aistudio.google.com/apikey and "
                "install the 'providers' extra (pip install -e \".[providers]\").",
            )
        return self.google_api_key
