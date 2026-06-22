"""Tests for external provider stubs (plan task 14).

The reliability mechanism (structured-output validation + bounded repair) is
tested by subclassing the agent and injecting scripted ``_complete`` responses,
so no SDK or credentials are needed. Credential-gating is tested via
ProviderConfig.
"""

import json

import pytest

from genclaw.agent.external import ExternalLLMAgent, PlanParseError, _extract_json
from genclaw.config import ProviderConfig, ProviderNotConfiguredError
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

    def _complete(self, system, user):
        resp = self._responses[self.calls]
        self.calls += 1
        return resp


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
    agent = ScriptedAgent(["not json at all", _GOOD_PLAN], config=config)
    plan = agent.conceptualize("two blue squares", request_id="req-1")
    assert len(plan.objects) == 2
    assert agent.calls == 2  # initial + one repair


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


def test_config_from_env_reads_keys():
    cfg = ProviderConfig.from_env({"ANTHROPIC_API_KEY": "sk-x", "GOOGLE_API_KEY": "g-y"})
    assert cfg.anthropic_api_key == "sk-x"
    assert cfg.google_api_key == "g-y"
    assert cfg.agent_model  # default present


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
