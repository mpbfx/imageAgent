"""外部图像生成器（plan task 14）。

「视觉生成层」负责把 code sketch 补成成图。默认 provider 是 Gemini-Flash-Image
（ADR 0004）；其他开放替代（FLUX.1-Kontext / Qwen-Image / SDXL+ControlNet）
作为可选,本文件不接。

SDK 用懒加载导入,凭据在前置阶段就要求提供,所以本模块 import 时不依赖
vendor SDK；未配置时抛 :class:`~genclaw.config.ProviderNotConfiguredError`,
而不是深埋在 API 调用里才失败。
"""

# 中文补充说明：
# 本文件实现两个具体生成器：
#   1) GeminiImageGenerator：走 google-genai 原生 SDK,支持 GOOGLE_BASE_URL
#      代理（国内或自建网关很常见）。
#   2) OpenAICompatImageGenerator：走 /v1/images/edits 端点的 OpenAI 兼容
#      代理（packyapi 等）,纯标准库（urllib + base64）,无 vendor 依赖。
# 两者的核心调用约定一致：把 sketch PNG 当视觉条件,叠加 prompt 和
# constraints,产出成图；产出路径、provider 名称、metadata 都按
# GenerationResult 契约填好。

from __future__ import annotations

from pathlib import Path
from typing import Optional

from genclaw.config import ProviderConfig
from genclaw.generators.base import GenerationResult, ImageGenerator


def _openai_compat_api_base(base_url: str) -> str:
    """Normalize OpenAI-compatible base URLs so '/v1' is not duplicated later."""
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base[:-3]
    return base


class GeminiImageGenerator(ImageGenerator):
    """Gemini-Flash-Image 生成器（论文对齐的默认生成器）。

    把 code sketch 当视觉条件 + prompt + constraints,产出成图到
    ``output_path``。支持 GOOGLE_BASE_URL 代理;必要时通过 HttpOptions
    把请求转给 Gemini 兼容代理。
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
        except ImportError as exc:  # pragma: no cover - 仅在无 SDK 时执行
            raise RuntimeError(
                "the 'google-genai' package is required for the Gemini generator; "
                'install the providers extra: pip install -e ".[providers]"'
            ) from exc

        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 若用户配了 GOOGLE_BASE_URL（如自建代理/网关），就走代理；
        # 否则用 google-genai 的默认 endpoint。
        http_options = None
        if self.config.google_base_url and not self.config.force_native_gemini:
            http_options = genai_types.HttpOptions(base_url=self.config.google_base_url)
        client = genai.Client(api_key=api_key, http_options=http_options)
        sketch_bytes = sketch_path.read_bytes()
        # Gemini 的多模态调用：把图像内联进 contents,跟文本指令一起送。
        # 这里指令强调「保留 sketch 的结构信息」,只补材质/光照/纹理。
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
    """构造给生成模型的「以 sketch 为结构条件」的指令文本。"""
    task_type = str((constraints or {}).get("task_type", "")).lower()
    backend = str((constraints or {}).get("backend", "")).lower()
    style = _style_directive(prompt, task_type)
    strength = _rerender_strength(prompt, constraints)

    base = (
        "Use the provided sketch as a structural guide: Preserve only the "
        "semantic structure. Preserve the number of main objects, their relative "
        "positions, the overall layout, and all readable text and labels. "
        "Do not copy the sketch's flat vector "
        "rendering literally; it is a layout guide, not the final visual style. "
        f"Render the final image in this style: {style}. "
    )
    if strength == "low":
        base += (
            "Use a conservative redraw: keep text glyphs and layout very stable, "
            "and improve only spacing, polish, contrast, and light visual styling. "
        )
    elif strength == "high":
        base += (
            "Completely redraw the image in the requested style. Do not preserve "
            "exact colors, outlines, flat shapes, character drawings, or SVG "
            "styling. "
        )
    else:
        base += (
            "Redraw the image noticeably. Avoid copying exact vector styling, "
            "but keep the semantic layout stable. "
        )
    if backend == "svg" or task_type in {"composition", "long_text"}:
        base += (
            "You may redesign colors, line quality, character details, shading, "
            "and visual polish as long as the structure and required text remain "
            "correct. "
        )
    else:
        base += (
            "Complete the visual details, materials, texture, and lighting while "
            "respecting the structure. "
        )
    base += "User request: " + prompt
    if constraints:
        base += f"\nConstraints: {constraints}"
    return base


def _style_directive(prompt: str, task_type: str) -> str:
    p = prompt.lower()
    if any(k in p for k in ("photorealistic", "photo", "photograph", "cinematic", "写实", "照片", "摄影")):
        return "photorealistic, polished, natural lighting"
    if any(k in p for k in ("infographic", "信息图", "diagram", "图解")):
        if any(k in p for k in ("cartoon", "卡通", "playful", "趣味")):
            return "playful cartoon infographic"
        return "clean polished infographic"
    if any(k in p for k in ("cartoon", "卡通", "cute", "可爱", "playful", "趣味")):
        return "playful cartoon illustration"
    if any(k in p for k in ("poster", "海报")):
        return "polished poster illustration"
    if task_type == "long_text":
        return "clean readable graphic design"
    return "polished illustration matching the user's requested style"


def _rerender_strength(prompt: str, constraints: dict | None) -> str:
    """Return low/medium/high redraw strength for sketch-conditioned generation."""
    c = constraints or {}
    task_type = str(c.get("task_type", "")).lower()
    backend = str(c.get("backend", "")).lower()
    p = prompt.lower()
    if task_type == "long_text" or backend == "html":
        return "low"
    if backend == "svg" and task_type in {"composition", "knowledge_grounded", ""}:
        return "high"
    if task_type in {"scene", "material", "editing"}:
        return "high"
    if any(k in p for k in ("infographic", "信息图", "cartoon", "卡通", "playful", "趣味")):
        return "high"
    if any(k in p for k in ("photorealistic", "photo", "photograph", "cinematic", "写实", "照片", "摄影")):
        return "high"
    return "medium"


def _first_image_bytes(response) -> Optional[bytes]:
    """从 genai 响应里抠出第一张内联图像的字节。

    Gemini 响应是嵌套结构:candidates[i].content.parts[j].inline_data.data,
    这里用 getattr 防御性穿透（不存在的字段返回 None,继续下一个 part）。
    """
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            inline = getattr(part, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                return inline.data
    return None


class OpenAICompatImageGenerator(ImageGenerator):
    """OpenAI 风格 image 代理的 sketch 条件生成器。

    很多网关（包括 packyapi 代理）通过 OpenAI 的 ``/v1/images/edits`` 端点
    暴露图像模型,而非 Gemini 原生的 ``generate_content`` API——后者在这种
    网关上会被直接拒绝。本适配器以 multipart 把 sketch + prompt POST 到
    ``/v1/images/edits``,把返回的图像落盘。

    同时支持:
    - Gemini 兼容代理（用 GOOGLE_API_KEY / GOOGLE_BASE_URL）
    - UniAPI 等 OpenAI 兼容端点（用 UNIAPI_API_KEY / UNIAPI_BASE_URL）

    纯标准库,无 vendor SDK。
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

        # 决定走哪一组凭据:Gemini 模型强制走 Google 凭据,其它模型才用 UniAPI。
        # 两者都遵循 OpenAI 兼容协议,multipart body 完全相同,只是 base_url
        # 和 token 来源不同。
        is_gemini = self.config.generator_model.lower().startswith("gemini")
        if self.config.uniapi_api_key and not is_gemini:
            api_key = self.config.require_uniapi(self.name)
            base = _openai_compat_api_base(self.config.uniapi_base_url or "https://api.openai.com")
        else:
            api_key = self.config.require_google(self.name)
            base = _openai_compat_api_base(self.config.google_base_url or "https://api.openai.com")

        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # /v1/images/edits 期望 multipart/form-data,不是 JSON。
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
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                payload = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if _should_fallback_to_async_video_api(
                status_code=exc.code,
                error_body=error_body,
                base_url=base,
                model=self.config.generator_model,
            ):
                payload = _generate_via_async_video_api(
                    base=base,
                    api_key=api_key,
                    model=self.config.generator_model,
                    prompt=_instruction(prompt, constraints),
                    sketch_bytes=sketch_path.read_bytes(),
                )
            else:
                raise RuntimeError(
                    f"image endpoint returned {exc.code}: {error_body}"
                ) from exc

        image_bytes = _decode_image_payload(payload)
        if image_bytes is None:
            raise RuntimeError(f"image endpoint returned no usable image: {payload}")
        output_path.write_bytes(image_bytes)

        endpoint = (
            f"{base}/v1/videos"
            if payload.get("_genclaw_endpoint") == "async-video"
            else f"{base}/v1/images/edits"
        )

        return GenerationResult(
            final_path=output_path,
            provider=self.name,
            sketch_path=sketch_path,
            metadata={
                "model": self.config.generator_model,
                "endpoint": endpoint,
                "prompt": prompt,
                "constraints": constraints or {},
            },
        )


def _multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """手工拼一个 multipart/form-data 字节体,``files`` 形如 {name: (filename, bytes, mime)}。

    不引入 requests 是为了把 vendor SDK 依赖降到零;multipart 协议本身简单,
    自己拼反而便于看清每一段。
    """
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
    """从 OpenAI 风格 image 响应里抠出图像字节,支持 b64_json 与 url 两种格式。"""
    import base64
    import urllib.request

    data = payload.get("data") or []
    if not data:
        return None
    item = data[0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    # 部分代理只给 URL,需要再发一次 GET 拉回图像。
    url = item.get("url") or item.get("image_url") or item.get("result_url")
    if url:
        with urllib.request.urlopen(url, timeout=180) as resp:
            return resp.read()
    return None


def _should_fallback_to_async_video_api(
    *, status_code: int, error_body: str, base_url: str, model: str
) -> bool:
    """Return True when an image proxy rejects /images/edits and wants async /videos."""
    if status_code != 403:
        return False
    body = error_body.lower()
    if "1010" not in body:
        return False
    if not model.lower().startswith("gemini"):
        return False
    return "qlhazycoder.top" in base_url.lower() or "async image/video api" in body


def _generate_via_async_video_api(
    *,
    base: str,
    api_key: str,
    model: str,
    prompt: str,
    sketch_bytes: bytes,
    poll_interval_seconds: float = 2.0,
    max_polls: int = 90,
) -> dict:
    """Submit to async /v1/videos, then poll until a final image URL is ready."""
    import base64
    import json
    import time
    import urllib.request

    image_data_url = "data:image/png;base64," + base64.b64encode(sketch_bytes).decode("ascii")
    submit_req = urllib.request.Request(
        f"{base}/v1/videos",
        data=json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "image_url": image_data_url,
            }
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(submit_req, timeout=180) as resp:
        task = json.loads(resp.read())

    task_id = task.get("task_id") or task.get("id")
    if not task_id:
        raise RuntimeError(f"async video api returned no task id: {task}")

    for _ in range(max_polls):
        status_req = urllib.request.Request(
            f"{base}/v1/videos/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(status_req, timeout=180) as resp:
            payload = json.loads(resp.read())
        status = str(payload.get("status", "")).lower()
        if status == "completed":
            if payload.get("image_url") or payload.get("result_url") or payload.get("url"):
                payload.setdefault("data", [{"image_url": payload.get("image_url") or payload.get("result_url") or payload.get("url")}])
                payload["_genclaw_endpoint"] = "async-video"
                return payload
            raise RuntimeError(f"async video api completed without image url: {payload}")
        if status in {"failed", "error", "canceled", "cancelled"}:
            raise RuntimeError(f"async video api task failed: {payload}")
        time.sleep(poll_interval_seconds)

    raise RuntimeError(f"async video api timed out waiting for task {task_id}")


class UniAPIImageEditGenerator(ImageGenerator):
    """UniAPI Qwen 图像编辑生成器（qwen-image-edit / qwen-image-edit-plus）。

    通过原生 HTTP 调用 UniAPI 的图像编辑接口（不走 OpenAI SDK 以避免默认参数冲突）。
    把 sketch PNG 作为视觉条件，通过 prompt 指导编辑，产出成图。
    """

    name = "uniapi-qwen-image-edit"

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

        api_key = self.config.require_uniapi(self.name)
        base_url = (self.config.uniapi_base_url or "https://api.uniapi.io/v1").rstrip("/")

        sketch_path = Path(sketch_path)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 构造指令：强调保留 sketch 结构
        instruction = _instruction(prompt, constraints)

        # 读取 sketch 图像字节（避免在循环中重复打开文件）
        sketch_bytes = sketch_path.read_bytes()

        # 用 multipart 形式发送请求到 /images/edits
        # UniAPI Qwen 模型期望尺寸格式为 "width*height" 而非 "widthxheight"
        body, content_type = _multipart(
            {
                "model": self.config.generator_model,
                "prompt": instruction,
                "size": "1024*1024",  # UniAPI 格式：width*height
            },
            {"image": ("sketch.png", sketch_bytes, "image/png")},
        )

        # 端点路径（base_url 已经包含 /v1）
        endpoint = f"{base_url}/images/edits"

        try:
            req = urllib.request.Request(
                endpoint,
                data=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": content_type,
                },
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
                    "endpoint": endpoint,
                    "prompt": prompt,
                    "constraints": constraints or {},
                },
            )
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            raise RuntimeError(
                f"UniAPI image edit failed at {endpoint} ({e.code}): {error_body}"
            ) from e
