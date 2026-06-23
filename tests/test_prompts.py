"""Tests for provider prompt contracts."""

from genclaw.agent.prompts import (
    CODE_SYSTEM_PROMPT,
    CODE_DEVELOPER_PROMPT,
    SYSTEM_PROMPT,
    DEVELOPER_PROMPT,
)


def test_code_prompt_requires_cjk_font_stack_for_text():
    assert "Noto Serif CJK SC" in CODE_SYSTEM_PROMPT
    assert "Source Han Serif SC" in CODE_SYSTEM_PROMPT
    assert "SimSun" in CODE_SYSTEM_PROMPT


def test_code_developer_prompt_allows_html_code_source():
    assert "complete, valid SVG document" not in CODE_DEVELOPER_PROMPT
    assert "code_lang" in CODE_DEVELOPER_PROMPT
    assert "complete, self-contained document" in CODE_DEVELOPER_PROMPT


def test_code_system_prompt_covers_all_backends():
    """Verify CODE_SYSTEM_PROMPT has quality guidance for all backends."""
    assert "MeshStandardMaterial" in CODE_SYSTEM_PROMPT
    assert "metalness" in CODE_SYSTEM_PROMPT
    assert "envMap" in CODE_SYSTEM_PROMPT
    assert "shadow" in CODE_SYSTEM_PROMPT
    assert "flexbox" in CODE_SYSTEM_PROMPT
    assert "viewBox" in CODE_SYSTEM_PROMPT
    assert "matplotlib" in CODE_SYSTEM_PROMPT
    assert "colorblind-friendly" in CODE_SYSTEM_PROMPT


def test_code_developer_prompt_has_backend_specific_requirements():
    """Verify CODE_DEVELOPER_PROMPT specifies requirements per backend."""
    assert "BACKEND-SPECIFIC REQUIREMENTS" in CODE_DEVELOPER_PROMPT
    assert "SVG:" in CODE_DEVELOPER_PROMPT
    assert "HTML:" in CODE_DEVELOPER_PROMPT
    assert "Three.js:" in CODE_DEVELOPER_PROMPT
    assert "Python" in CODE_DEVELOPER_PROMPT


def test_three_js_quality_checklist():
    """Verify Three.js quality requirements are explicit."""
    assert "MeshStandardMaterial" in CODE_SYSTEM_PROMPT
    assert "DirectionalLight" in CODE_SYSTEM_PROMPT
    assert "shadow.mapSize" in CODE_SYSTEM_PROMPT
    assert "shadowMap" in CODE_DEVELOPER_PROMPT
    assert "castShadow" in CODE_DEVELOPER_PROMPT


def test_structured_prompt_has_backend_guidance():
    """Verify SYSTEM_PROMPT (structured mode) has backend-specific guidance."""
    assert "BACKEND-SPECIFIC GUIDANCE" in SYSTEM_PROMPT
    assert "SVG (structural composition" in SYSTEM_PROMPT
    assert "HTML (text-driven layout" in SYSTEM_PROMPT
    assert "Three.js (3D geometry" in SYSTEM_PROMPT
    assert "Python (numeric sketches" in SYSTEM_PROMPT


def test_developer_prompt_has_examples_per_backend():
    """Verify DEVELOPER_PROMPT (structured mode) has examples for all backends."""
    assert "BACKEND-SPECIFIC EXAMPLES" in DEVELOPER_PROMPT
    assert "SVG (composition, spatial relations)" in DEVELOPER_PROMPT
    assert "HTML (long text, documents, menus)" in DEVELOPER_PROMPT
    assert "Three.js (3D geometry, physics, reflections)" in DEVELOPER_PROMPT
    assert "metalness" in DEVELOPER_PROMPT
    assert "roughness" in DEVELOPER_PROMPT

