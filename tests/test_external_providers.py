"""Tests for external provider stubs (plan task 14).

The reliability mechanism (structured-output validation + bounded repair) is
tested by subclassing the agent and injecting scripted ``_complete`` responses,
so no SDK or credentials are needed. Credential-gating is tested via
ProviderConfig.
"""

import io
import json
import sys
import types
import urllib.error
import urllib.request

import pytest

from genclaw.agent.external import ExternalLLMAgent, PlanParseError, _extract_json
from genclaw.config import ProviderConfig, ProviderNotConfiguredError
from genclaw.generators.external import (
    OpenAICompatImageGenerator,
    _instruction,
    _openai_compat_api_base,
)
from genclaw.review.vlm import VLMReviewer, _parse_result
from genclaw.schemas import CanvasBackend, TaskType


# A minimal valid CanvasPlan as JSON the model might return.
_GOOD_PLAN = json.dumps(
    {
        "request_id": "req-1",
        "prompt": "two blue squares",
        "task_type": "composition",
        "backend": "svg",
        "size": {"width": 256, "height": 256},
        "objects": [
            {"id": "s1", "kind": "rectangle", "x": 10, "y": 10, "width": 40, "height": 40},
            {"id": "s2", "kind": "rectangle", "x": 80, "y": 10, "width": 40, "height": 40},
        ],
        "checks": [{"kind": "object_count", "target": "rectangle", "expected": 2}],
    }
)


class ScriptedAgent(ExternalLLMAgent):
    """Agent whose _complete returns scripted responses in order."""

    def __init__(self, responses, **kw):
        super().__init__(**kw)
        self._responses = list(responses)
        self.calls = 0

    def _complete(self, system, user, history=None):
        resp = self._responses[self.calls]
        self.calls += 1
        return resp


class RecordingScriptedAgent(ScriptedAgent):
    def __init__(self, responses, **kw):
        super().__init__(responses, **kw)
        self.complete_calls = []

    def _complete(self, system, user, history=None):
        self.complete_calls.append((system, user, history))
        return super()._complete(system, user, history=history)


@pytest.fixture
def config():
    # No credentials needed: ScriptedAgent overrides _complete.
    return ProviderConfig(max_parse_retries=2)


def test_valid_first_response_parses(config):
    agent = ScriptedAgent([_GOOD_PLAN], config=config)
    plan = agent.conceptualize("two blue squares", request_id="req-1")
    assert plan.backend is CanvasBackend.svg
    assert len(plan.objects) == 2
    assert agent.calls == 1


def test_markdown_fenced_response_is_extracted(config):
    fenced = f"```json\n{_GOOD_PLAN}\n```"
    agent = ScriptedAgent([fenced], config=config)
    plan = agent.conceptualize("two blue squares", request_id="req-1")
    assert len(plan.objects) == 2


def test_one_bad_then_good_triggers_repair_and_succeeds(config):
    # First response is invalid JSON; the repair attempt returns a valid plan.
    agent = RecordingScriptedAgent(["not json at all", _GOOD_PLAN], config=config)
    plan = agent.conceptualize("two blue squares", request_id="req-1")
    assert len(plan.objects) == 2
    assert agent.calls == 2  # initial + one repair
    history = agent.complete_calls[1][2]
    assert history == [
        {"role": "user", "content": agent.complete_calls[0][1]},
        {"role": "assistant", "content": "not json at all"},
        {"role": "user", "content": history[2]["content"]},
    ]
    assert "response was not valid JSON" in history[2]["content"]


def test_invalid_schema_then_good_repairs(config):
    # Valid JSON but schema-invalid (duplicate ids), then a good plan.
    bad = json.dumps(
        {
            "request_id": "r",
            "prompt": "p",
            "task_type": "composition",
            "backend": "svg",
            "size": {"width": 10, "height": 10},
            "objects": [
                {"id": "dup", "kind": "circle"},
                {"id": "dup", "kind": "circle"},
            ],
        }
    )
    agent = ScriptedAgent([bad, _GOOD_PLAN], config=config)
    plan = agent.conceptualize("two blue squares", request_id="req-1")
    assert len(plan.objects) == 2
    assert agent.calls == 2


def test_persistent_failure_raises_with_history(config):
    agent = ScriptedAgent(["bad", "still bad", "nope"], config=config)
    with pytest.raises(PlanParseError) as exc:
        agent.conceptualize("two blue squares", request_id="req-1")
    # initial + 2 retries = 3 attempts, all recorded.
    assert len(exc.value.attempts) == 3
    assert exc.value.last_error


def test_task_type_override_is_forced(config):
    # Even if the model picks a different task_type, the caller's wins.
    agent = ScriptedAgent([_GOOD_PLAN], config=config)
    plan = agent.conceptualize(
        "two blue squares", task_type=TaskType.long_text, request_id="req-1"
    )
    assert plan.task_type is TaskType.long_text


def test_extract_json_isolates_object():
    assert _extract_json('prefix {"a": 1} suffix') == '{"a": 1}'


# --- credential gating ---------------------------------------------------------


def test_agent_without_key_raises_provider_not_configured():
    from genclaw.agent.external import ExternalLLMAgent

    agent = ExternalLLMAgent(config=ProviderConfig(anthropic_api_key=None))
    with pytest.raises(ProviderNotConfiguredError, match="ANTHROPIC_API_KEY"):
        # Real _complete path requires a key.
        agent._complete("sys", "user")


def test_generator_without_key_raises():
    from genclaw.generators.external import GeminiImageGenerator

    gen = GeminiImageGenerator(config=ProviderConfig(google_api_key=None))
    with pytest.raises(ProviderNotConfiguredError, match="GOOGLE_API_KEY"):
        gen.generate("p", "sketch.png", "out.png")


def test_image_instruction_preserves_svg_structure_without_forcing_photorealism():
    prompt = "一张充满趣味的卡通信息图展示销售漏斗"
    text = _instruction(prompt, {"task_type": "composition", "backend": "svg"})

    assert "Use the provided sketch as a structural guide" in text
    assert "Preserve only the semantic structure" in text
    assert "Preserve the number of main objects" in text
    assert "relative positions" in text
    assert "all readable text and labels" in text
    assert "Completely redraw the image in the requested style" in text
    assert "Do not preserve exact colors, outlines, flat shapes" in text
    assert "Do not copy the sketch's flat vector rendering literally" in text
    assert "playful cartoon infographic" in text
    assert "photorealistic" not in text


def test_image_instruction_uses_low_redraw_for_long_text():
    text = _instruction("一张包含多行中文菜单的海报", {"task_type": "long_text", "backend": "html"})

    assert "Use a conservative redraw" in text
    assert "Completely redraw the image" not in text


def test_image_instruction_uses_photorealism_only_for_photo_style_prompts():
    text = _instruction(
        "cinematic photorealistic product photo of a red apple",
        {"task_type": "composition"},
    )

    assert "photorealistic" in text
    assert "cinematic" in text


def test_config_from_env_reads_keys():
    cfg = ProviderConfig.from_env({"ANTHROPIC_API_KEY": "sk-x", "GOOGLE_API_KEY": "g-y"})
    assert cfg.anthropic_api_key == "sk-x"
    assert cfg.google_api_key == "g-y"
    assert cfg.agent_model  # default present


def test_config_can_force_native_gemini():
    cfg = ProviderConfig.from_env(
        {
            "GOOGLE_API_KEY": "g-y",
            "GOOGLE_BASE_URL": "https://api.qlhazycoder.top",
            "GENCLAW_FORCE_NATIVE_GEMINI": "true",
        }
    )
    assert cfg.force_native_gemini is True


def test_openai_compat_api_base_trims_trailing_v1():
    assert _openai_compat_api_base("https://api.qlhazycoder.top") == "https://api.qlhazycoder.top"
    assert _openai_compat_api_base("https://api.qlhazycoder.top/") == "https://api.qlhazycoder.top"
    assert _openai_compat_api_base("https://api.qlhazycoder.top/v1") == "https://api.qlhazycoder.top"


def test_glm_openai_compatible_uses_chat_with_thinking_disabled(monkeypatch):
    calls = []

    class FakeChatCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            message = types.SimpleNamespace(content='{"ok": true}')
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = types.SimpleNamespace(
                completions=FakeChatCompletions()
            )
            self.responses = types.SimpleNamespace(
                create=lambda **_kw: pytest.fail("GLM should not use responses.create")
            )

    fake_openai = types.SimpleNamespace(OpenAI=FakeClient)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    agent = ExternalLLMAgent(
        config=ProviderConfig(
            uniapi_api_key="sk-x",
            uniapi_base_url="https://api.uniapi.io/v1",
            agent_model="glm-5.2",
        )
    )

    assert agent._complete("system", "user") == '{"ok": true}'
    assert calls
    call = calls[0]
    assert call["model"] == "glm-5.2"
    assert call["max_tokens"] >= 8192
    assert call["extra_body"]["thinking"]["type"] == "disabled"
    assert call["extra_body"]["reasoning_effort"] == "none"


def test_openai_compatible_reuses_client_and_does_not_swallow_runtime_errors(monkeypatch):
    created = []

    class FakeChatCompletions:
        def create(self, **kwargs):
            raise RuntimeError("auth failed")

    class FakeClient:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.chat = types.SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeClient))
    agent = ExternalLLMAgent(
        config=ProviderConfig(
            uniapi_api_key="sk-x",
            uniapi_base_url="https://example.test/v1",
            agent_model="gpt-test",
        )
    )

    with pytest.raises(RuntimeError, match="auth failed"):
        agent._complete("system", "user")
    with pytest.raises(RuntimeError, match="auth failed"):
        agent._complete("system", "user")
    assert len(created) == 1


def test_uniapi_responses_attribute_error_warns_before_chat_fallback(monkeypatch, caplog):
    class BrokenResponses:
        def create(self, **kwargs):
            raise AttributeError("gone")

    class FakeChatCompletions:
        def create(self, **kwargs):
            message = types.SimpleNamespace(content='{"ok": true}')
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    class FakeClient:
        def __init__(self, **kwargs):
            self.responses = BrokenResponses()
            self.chat = types.SimpleNamespace(completions=FakeChatCompletions())

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeClient))
    agent = ExternalLLMAgent(
        config=ProviderConfig(
            uniapi_api_key="sk-x",
            uniapi_base_url="https://api.uniapi.io/v1",
            agent_model="claude-test",
        )
    )

    with caplog.at_level("WARNING", logger="genclaw.agent.external"):
        assert agent._complete("system", "user") == '{"ok": true}'
    assert "responses.create unavailable" in caplog.text


def test_openai_compat_generator_falls_back_to_async_video_api_for_1010_gate(
    monkeypatch, tmp_path
):
    sketch_path = tmp_path / "sketch.png"
    sketch_path.write_bytes(b"\x89PNG\r\n\x1a\nfakepng")
    output_path = tmp_path / "out.png"

    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeBinaryResponse:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(req, timeout=0):
        url = req.full_url if hasattr(req, "full_url") else req
        method = getattr(req, "method", "GET")
        body = req.data if hasattr(req, "data") else None
        requests.append((method, url, body))
        if url.endswith("/v1/images/edits"):
            raise urllib.error.HTTPError(
                url=url,
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=io.BytesIO(b'{"error":{"code":"1010","message":"wrong endpoint"}}'),
            )
        if url.endswith("/v1/videos") and method == "POST":
            return FakeResponse({"task_id": "task-123", "status": "queued"})
        if url.endswith("/v1/videos/task-123") and method == "GET":
            return FakeResponse(
                {
                    "task_id": "task-123",
                    "status": "completed",
                    "image_url": "https://example.com/final.png",
                }
            )
        if url == "https://example.com/final.png":
            return FakeBinaryResponse(b"final-image-bytes")
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda *_args, **_kwargs: None)

    gen = OpenAICompatImageGenerator(
        config=ProviderConfig(
            google_api_key="sk-test",
            google_base_url="https://api.qlhazycoder.top",
            generator_model="gemini-3.1-flash-image",
        )
    )

    result = gen.generate("render a red square", sketch_path, output_path)

    assert output_path.read_bytes() == b"final-image-bytes"
    assert result.metadata["endpoint"] == "https://api.qlhazycoder.top/v1/videos"
    assert [item[:2] for item in requests[:3]] == [
        ("POST", "https://api.qlhazycoder.top/v1/images/edits"),
        ("POST", "https://api.qlhazycoder.top/v1/videos"),
        ("GET", "https://api.qlhazycoder.top/v1/videos/task-123"),
    ]
    async_payload = json.loads(requests[1][2].decode("utf-8"))
    assert async_payload["model"] == "gemini-3.1-flash-image"
    assert async_payload["image_url"].startswith("data:image/png;base64,")


# --- VLM verdict parsing -------------------------------------------------------


def test_vlm_parse_valid_verdict():
    result = _parse_result('{"passed": true, "score": 0.9, "failures": []}')
    assert result.passed is True
    assert result.score == 0.9


def test_vlm_parse_malformed_fails_closed():
    result = _parse_result("the image looks great!")
    assert result.passed is False
    assert result.failures


def test_vlm_review_without_image_fails_closed():
    reviewer = VLMReviewer(config=ProviderConfig(anthropic_api_key="sk-x"))
    from genclaw.agent.fixture import FixtureAgent

    plan = FixtureAgent().conceptualize("three red circles on the left")
    result = reviewer.review(plan, image_path=None)
    assert result.passed is False
    assert "requires a rendered image" in result.failures[0]


# --- code-as-brush mode (ADR 0005) -------------------------------------------

_CODE_PLAN = json.dumps(
    {
        "request_id": "c1",
        "prompt": "a red circle",
        "task_type": "composition",
        "backend": "svg",
        "source": "code",
        "code_lang": "svg",
        "size": {"width": 100, "height": 100},
        "code_source": '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><circle cx="50" cy="50" r="40" fill="#d62828"/></svg>',
    }
)


def test_code_mode_produces_code_source_plan(config):
    agent = ScriptedAgent([_CODE_PLAN], config=config, code_mode=True)
    plan = agent.conceptualize("a red circle", request_id="c1")
    assert plan.source.value == "code"
    assert plan.code_source and "<circle" in plan.code_source
    assert agent.code_mode is True


def test_code_mode_flag_defaults_false(config):
    agent = ScriptedAgent([_GOOD_PLAN], config=config)
    assert agent.code_mode is False


# --- mode -> code_mode mapping (code-as-brush is the external default) --------

def test_external_mode_defaults_to_code_as_brush(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-y")
    from genclaw.pipeline import build_providers

    for mode in ("external", "external-code"):
        agent, _gen, _rev, _search = build_providers(mode)
        assert agent.code_mode is True, mode


def test_external_mode_can_force_native_gemini_even_with_google_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-y")
    monkeypatch.setenv("GOOGLE_BASE_URL", "https://api.qlhazycoder.top")
    monkeypatch.setenv("GENCLAW_FORCE_NATIVE_GEMINI", "true")
    monkeypatch.setenv("GENCLAW_GENERATOR_MODEL", "gemini-3.1-flash-image")
    monkeypatch.delenv("UNIAPI_API_KEY", raising=False)
    monkeypatch.delenv("UNIAPI_BASE_URL", raising=False)
    from genclaw.generators.external import GeminiImageGenerator
    from genclaw.pipeline import build_providers

    _agent, generator, _rev, _search = build_providers("external")
    assert isinstance(generator, GeminiImageGenerator)


def test_external_template_opts_out_of_code(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("GOOGLE_API_KEY", "g-y")
    from genclaw.pipeline import build_providers

    agent, _gen, _rev, _search = build_providers("external-template")
    assert agent.code_mode is False


def test_external_tele_uses_tele_generator(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("UNIAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_BASE_URL", raising=False)
    monkeypatch.delenv("UNIAPI_BASE_URL", raising=False)

    class FakeTeleGenerator:
        name = "fake-tele"

        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    import genclaw.generators.tele as tele_mod
    monkeypatch.setattr(tele_mod, "TeleImg2ImgGenerator", FakeTeleGenerator)

    from genclaw.pipeline import build_providers

    agent, generator, reviewer, search = build_providers("external-tele")
    assert agent.code_mode is True
    assert isinstance(generator, FakeTeleGenerator)
    assert reviewer is not None
    assert search is not None


def test_tele_generator_writes_prompt_file_and_uses_cuda_zero(monkeypatch, tmp_path):
    from genclaw.generators.tele import TeleImg2ImgGenerator
    from PIL import Image

    scp_calls = []
    ssh_calls = []

    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/teleedit_mask_v3/models/base_model/",
            "GENCLAW_TELE_PYTHON": "uv run python",
            "GENCLAW_TELE_GPU": "1",
        }
    )
    monkeypatch.setattr(gen, "_scp", lambda src, dst: scp_calls.append((src, dst)))
    monkeypatch.setattr(gen, "_ssh_run", lambda remote_cmd, timeout=300: ssh_calls.append(remote_cmd) or "")

    sketch = tmp_path / "sketch.png"
    Image.new("RGB", (32, 32), "white").save(sketch)
    out = tmp_path / "out.png"

    gen.generate(
        "一张充满趣味的卡通信息图展示销售漏斗",
        sketch,
        out,
        {"task_type": "composition", "backend": "svg", "source": "code"},
    )

    assert any("CUDA_VISIBLE_DEVICES=1" in call for call in ssh_calls)
    assert any("cd /teleedit_mask_v3/codes &&" in call for call in ssh_calls)
    assert any("payload.json" in src or "payload" in dst for src, dst in scp_calls)


def test_tele_generator_infers_remote_codes_workdir():
    from genclaw.generators.tele import TeleImg2ImgGenerator

    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": (
                "/gemini/platform/public/aigc/aigc_image/zangxh/"
                "teleedit_mask_v3/models/base_model/"
            ),
            "GENCLAW_TELE_PYTHON": "uv run python",
        }
    )

    assert (
        gen.workdir
        == "/gemini/platform/public/aigc/aigc_image/zangxh/teleedit_mask_v3/codes"
    )


def test_tele_generator_prefers_explicit_workdir_env():
    from genclaw.generators.tele import TeleImg2ImgGenerator

    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/unused/model",
            "GENCLAW_TELE_PYTHON": "uv run python",
            "GENCLAW_TELE_WORKDIR": "/srv/teleimage_edit_v4.2/codes",
        }
    )

    assert gen.workdir == "/srv/teleimage_edit_v4.2/codes"


def test_tele_generator_service_script_uses_main_entry_and_defaults():
    from genclaw.generators.tele import TeleImg2ImgGenerator

    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/models/base_model",
            "GENCLAW_TELE_PYTHON": "uv run python",
        }
    )

    script = gen._service_script()
    assert "from diffusers import QwenImageEditPlusPipeline" in script
    assert "from main import TeleEdit_Mask" not in script
    assert "pipe = QwenImageEditPlusPipeline.from_pretrained" in script
    assert "result = pipe(" in script
    assert "image," in script
    assert "prompt," in script
    assert "payload.get(" in script
    assert "true_cfg_scale" in script
    assert "num_inference_steps" in script
    assert "guidance_scale" in script


def test_tele_generator_client_command_posts_json_to_local_service():
    from genclaw.generators.tele import TeleImg2ImgGenerator

    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/models/base_model",
            "GENCLAW_TELE_PYTHON": "uv run python",
            "GENCLAW_TELE_SERVICE_PORT": "18765",
        }
    )

    cmd = gen._service_client_command("/tmp/in.json", "/tmp/out.json")
    assert "http://127.0.0.1:18765/generate" in cmd
    assert "/tmp/in.json" in cmd
    assert "/tmp/out.json" in cmd


def test_tele_generator_payload_uses_stronger_request_overrides(monkeypatch, tmp_path):
    from genclaw.generators.tele import TeleImg2ImgGenerator
    from PIL import Image

    sent_payload = {}
    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/teleedit_mask_v3/models/base_model/",
            "GENCLAW_TELE_PYTHON": "uv run python",
            "GENCLAW_TELE_WORKDIR": "/srv/codes",
        }
    )

    def fake_scp(src, dst):
        if src.endswith("payload.json"):
            import json
            from pathlib import Path

            sent_payload.update(json.loads(Path(src).read_text(encoding="utf-8")))

    monkeypatch.setattr(gen, "_scp", fake_scp)
    monkeypatch.setattr(gen, "_ensure_service", lambda: None)
    monkeypatch.setattr(gen, "_ssh_run", lambda remote_cmd, timeout=300: "")

    sketch = tmp_path / "sketch.png"
    Image.new("RGB", (32, 32), "white").save(sketch)
    out = tmp_path / "out.png"

    gen.generate("一只红苹果", sketch, out, {"task_type": "scene"})

    assert sent_payload["prompt"].startswith(
        "Use the provided sketch as a structural guide:"
    )
    assert sent_payload["rerender_strength"] == "high"
    assert sent_payload["num_inference_steps"] == 52
    assert sent_payload["true_cfg_scale"] == 7.5
    assert sent_payload["guidance_scale"] == 1.8


def test_tele_generator_high_strength_softens_sketch_but_keeps_color_cues(monkeypatch, tmp_path):
    from genclaw.generators.tele import TeleImg2ImgGenerator
    from PIL import Image
    import io
    import base64
    import json
    from pathlib import Path

    sent_payload = {}
    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/teleedit_mask_v3/models/base_model/",
            "GENCLAW_TELE_PYTHON": "uv run python",
            "GENCLAW_TELE_WORKDIR": "/srv/codes",
        }
    )

    def fake_scp(src, dst):
        if src.endswith("payload.json"):
            sent_payload.update(json.loads(Path(src).read_text(encoding="utf-8")))

    monkeypatch.setattr(gen, "_scp", fake_scp)
    monkeypatch.setattr(gen, "_ensure_service", lambda: None)
    monkeypatch.setattr(gen, "_ssh_run", lambda remote_cmd, timeout=300: "")

    img = Image.new("RGB", (32, 16), "white")
    for x in range(8, 24):
        for y in range(4, 12):
            img.putpixel((x, y), (20, 120, 220))
    sketch = tmp_path / "sketch.png"
    img.save(sketch)
    out = tmp_path / "out.png"

    gen.generate("In the photo, there are four blue apples and one green apple.", sketch, out, {"task_type": "composition", "backend": "svg"})

    payload_img = Image.open(io.BytesIO(base64.b64decode(sent_payload["image"]))).convert("RGB")
    # High strength should soften the finished sketch but keep color semantics.
    assert payload_img.getpixel((16, 8)) != (20, 120, 220)
    r, g, b = payload_img.getpixel((16, 8))
    assert b > g > r


def test_tele_generator_ensure_service_waits_for_port(monkeypatch):
    from genclaw.generators.tele import TeleImg2ImgGenerator

    calls = []
    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/teleedit_mask_v3/models/base_model/",
            "GENCLAW_TELE_PYTHON": "uv run python",
            "GENCLAW_TELE_WORKDIR": "/srv/codes",
            "GENCLAW_TELE_SERVICE_PORT": "18765",
        }
    )
    monkeypatch.setattr(gen, "_ssh_run", lambda remote_cmd, timeout=300: calls.append(remote_cmd) or "")

    gen._ensure_service()

    assert calls
    assert "connect_ex(('127.0.0.1', 18765))" in calls[0]
    assert "for i in $(seq 1 300)" in calls[0]
    assert "if ! python - <<'PY'" in calls[0]
    assert "then" in calls[0]
    assert "fi;" in calls[0] or "\nfi\n" in calls[0]


def test_tele_generator_remote_error_includes_stdout_stderr(monkeypatch):
    from genclaw.generators.tele import TeleImg2ImgGenerator

    gen = TeleImg2ImgGenerator(
        env={
            "GENCLAW_TELE_SSH_HOST": "host",
            "GENCLAW_TELE_SSH_USER": "user",
            "GENCLAW_TELE_SSH_KEY": "key",
            "GENCLAW_TELE_MODEL_PATH": "/model",
            "GENCLAW_TELE_PYTHON": "uv run python",
        }
    )

    class Proc:
        returncode = 1
        stdout = "hello stdout"
        stderr = "hello stderr"

    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: Proc())

    with pytest.raises(RuntimeError) as exc:
        gen._ssh_run("echo hi")
    msg = str(exc.value)
    assert "hello stdout" in msg
    assert "hello stderr" in msg
