"""Tests for the rule-based reviewer (plan task 10)."""

import pytest

from genclaw.agent.fixture import FixtureAgent
from genclaw.renderers.html import HTMLRenderer
from genclaw.renderers.svg import SVGRenderer
from genclaw.review.rules import RuleReviewer
from genclaw.schemas import ReviewCheck


@pytest.fixture
def reviewer():
    return RuleReviewer()


def test_three_circle_fixture_passes_object_count(reviewer, tmp_path):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    result = SVGRenderer().render(plan, tmp_path)
    review = reviewer.review(plan, canvas_source_path=result.source_path)
    assert review.passed
    assert review.score == 1.0
    assert not review.failures


def test_object_count_mismatch_fails_with_reason(reviewer):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    plan.checks = [ReviewCheck(kind="object_count", target="circle", expected=5)]
    review = reviewer.review(plan)
    assert not review.passed
    assert any("expected 5 but found 3" in f for f in review.failures)


def test_missing_required_text_fails_clearly(reviewer, tmp_path):
    plan = FixtureAgent().conceptualize("a poster for GenClaw")
    result = HTMLRenderer().render(plan, tmp_path)
    plan.checks = [ReviewCheck(kind="contains_text", expected="Nonexistent Heading")]
    review = reviewer.review(plan, canvas_source_path=result.source_path)
    assert not review.passed
    assert any("missing required text" in f for f in review.failures)


def test_contains_text_passes_for_present_text(reviewer, tmp_path):
    plan = FixtureAgent().conceptualize("a poster for GenClaw")
    result = HTMLRenderer().render(plan, tmp_path)
    review = reviewer.review(plan, canvas_source_path=result.source_path)
    assert review.passed


def test_wrong_backend_fails(reviewer):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    plan.checks = [ReviewCheck(kind="backend", expected="html")]
    review = reviewer.review(plan)
    assert not review.passed
    assert any("backend expected" in f for f in review.failures)


def test_unevaluable_check_warns_not_passes(reviewer):
    # contains_text without source text cannot be evaluated -> warning, not pass.
    plan = FixtureAgent().conceptualize("a poster for GenClaw")
    plan.checks = [ReviewCheck(kind="contains_text", expected="Code as Brush")]
    review = reviewer.review(plan, canvas_source_path=None)
    assert not review.passed
    assert review.warnings
    assert not review.failures


def test_artifact_exists_check(reviewer, tmp_path):
    f = tmp_path / "final.png"
    f.write_bytes(b"data")
    plan = FixtureAgent().conceptualize("three red circles on the left")
    plan.checks = [ReviewCheck(kind="artifact_exists", target=str(f))]
    review = reviewer.review(plan)
    assert review.passed
