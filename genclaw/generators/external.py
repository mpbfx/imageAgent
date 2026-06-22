"""External image generators (plan task 14).

The visual generation layer completes a code sketch into a final image. The
default provider is Gemini-Flash-Image (ADR 0004); open alternatives
(FLUX.1-Kontext, Qwen-Image, SDXL+ControlNet) are optional and not wired here.

The SDK is imported lazily and credentials are required up front, so this module
imports without the vendor SDK and raises
:class:`~genclaw.config.ProviderNotConfiguredError` when unconfigured rather
than failing deep inside an API call.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.config import ProviderConfig
from genclaw.generators.base import GenerationResult, ImageGenerator


class GeminiImageGenerator(ImageGenerator):
    """Gemini-Flash-Image generator (default paper-aligned generator).

    Takes the code sketch as a visual condition plus the prompt and constraints,
    and writes the completed image to ``output_path``.
    """

    name = "gemini-flash-image"

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig.from_env()

    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        api_key = self.config.require_google(self.name)
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:  # pragma: no cover - exercised only without SDK
            raise RuntimeError(
                "the 'google-genai' package is required for the Gemini generator; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Route through a Gemini-compatible proxy when GOOGLE_BASE_URL is set.
        http_options = (
            genai_types.HttpOptions(base_url=self.config.google_base_url)
            if self.config.google_base_url
            else None
        )
        client = genai.Client(api_key=api_key, http_options=http_options)
        sketch_bytes = sketch_path.read_bytes()
        response = client.models.generate_content(
            model=self.config.generator_model,
            contents=[
                _instruction(prompt, constraints),
                {"inline_data": {"mime_type": "image/png", "data": sketch_bytes}},
            ],
        )
        image_bytes = _first_image_bytes(response)
        if image_bytes is None:
            raise RuntimeError("generator returned no image data")
        output_path.write_bytes(image_bytes)

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "model": self.config.generator_model,
                "prompt": prompt,
                "constraints": constraints or {},
            },
        )


def _instruction(prompt: str, constraints: dict | None) -> str:
    base = (
        "Use the provided sketch as a strict structural condition: keep object "
        "counts, positions, and layout exactly as drawn. Complete materials, "
        "texture, and lighting to render a photorealistic image of: " + prompt
    )
    if constraints:
        base += f"\nConstraints: {constraints}"
    return base


def _first_image_bytes(response) -> Optional[bytes]:
    """Pull the first inline image payload out of a genai response."""
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    return None


class OpenAICompatImageGenerator(ImageGenerator):
    """Sketch-conditioned generator for an OpenAI-style image proxy.

    Many gateways (incl. the packyapi proxy) expose image models through the
    OpenAI ``/v1/images/edits`` endpoint rather than the native Gemini
    ``generate_content`` API -- they reject "gemini chat" requests. This adapter
    posts the code sketch + prompt as multipart to ``images/edits`` and stores
    the returned image. Uses ``GOOGLE_API_KEY`` / ``GOOGLE_BASE_URL`` and the
    configured generator model. Stdlib only -- no vendor SDK.
    """

    name = "openai-compat-image"

    def __init__(self, config: Optional[ProviderConfig] = None):
        self.config = config or ProviderConfig.from_env()

    def generate(
        self,
        prompt: str,
        sketch_path: Path,
        output_path: Path,
        constraints: dict | None = None,
    ) -> GenerationResult:
        import json
        import urllib.request

        api_key = self.config.require_google(self.name)
        base = (self.config.google_base_url or "https://api.openai.com").rstrip("/")
        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        body, content_type = _multipart(
            {"model": self.config.generator_model, "prompt": _instruction(prompt, constraints)},
            {"image": ("sketch.png", sketch_path.read_bytes(), "image/png")},
        )
        req = urllib.request.Request(
            f"{base}/v1/images/edits",
            data=body,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read())

        image_bytes = _decode_image_payload(payload)
        if image_bytes is None:
            raise RuntimeError(f"image endpoint returned no usable image: {payload}")
        output_path.write_bytes(image_bytes)

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "model": self.config.generator_model,
                "endpoint": f"{base}/v1/images/edits",
                "prompt": prompt,
                "constraints": constraints or {},
            },
        )


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body. ``files``: name -> (filename, bytes, mime)."""
    boundary = "----genclawformboundary7MA4YWxkTrZu0gW"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    for name, (filename, data, mime) in files.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; '
            f'filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _decode_image_payload(payload: dict) -> Optional[bytes]:
    """Extract image bytes from an OpenAI-style images response (url or b64)."""
    import base64
    import urllib.request

    data = payload.get("data") or []
    if not data:
        return None
    item = data[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    url = item.get("url")
    if url:
        with urllib.request.urlopen(url, timeout=180) as resp:
            return resp.read()
    return None
