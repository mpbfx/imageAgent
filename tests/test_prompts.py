"""Tests for prompt builder contracts."""

from genclaw.agent.prompts import (
    build_code_prompt_bundle,
    build_repair_prompt,
    build_structured_prompt_bundle,
)


def _structured_bundle():
    return build_structured_prompt_bundle(
        task_type="composition",
        request_id="req-1",
        prompt="three circles",
        knowledge_context="",
    )


def _code_bundle():
    return build_code_prompt_bundle(
        task_type="composition",
        request_id="req-1",
        prompt="a red circle",
        knowledge_context="",
    )


def test_code_prompt_requires_cjk_font_stack_for_text():
    bundle = _code_bundle()
    assert "Noto Serif CJK SC" in bundle.system
    assert "Source Han Serif SC" in bundle.system
    assert "SimSun" in bundle.system


def test_code_developer_prompt_allows_html_code_source():
    bundle = _code_bundle()
    assert "complete, valid SVG document" not in bundle.developer
    assert "code_lang" in bundle.developer
    assert "complete, self-contained document" in bundle.developer


def test_code_system_prompt_covers_all_backends():
    """Verify code system prompt has quality guidance for all backends."""
    system = _code_bundle().system
    assert "MeshStandardMaterial" in system
    assert "metalness" in system
    assert "envMap" in system
    assert "shadow" in system
    assert "flexbox" in system
    assert "viewBox" in system
    assert "matplotlib" in system
    assert "colorblind-friendly" in system


def test_svg_code_prompt_enforces_sparse_structural_sketches():
    """SVG code-as-brush should stay sparse so image edit can rerender freely."""
    system = _code_bundle().system
    assert "sparse structural sketch" in system
    assert "low-fidelity structural guide" in system
    assert "placeholder silhouettes" in system
    assert "not a finished illustration" in system
    assert "Only draw the minimum geometry needed" in system
    assert "Do NOT simulate texture, gradients, shadows, highlights" in system
    assert "Do NOT break one semantic object into many tiny paths" in system
    assert "Keep total shape count low" in system
    assert "Start flat and simple by default" in system
    assert "Do NOT add explanatory labels" in system
    assert "Treat infographics, playful cartoons, posters, and diagrammatic scenes as" in system
    assert "Never emit <linearGradient>, <radialGradient>, <filter>, <pattern>, or <mask>" in system


def test_code_developer_prompt_has_backend_specific_requirements():
    """Verify code developer prompt specifies requirements per backend."""
    developer = _code_bundle().developer
    assert "BACKEND-SPECIFIC REQUIREMENTS" in developer
    assert "SVG:" in developer
    assert "HTML:" in developer
    assert "Three.js:" in developer
    assert "Python" in developer


def test_three_js_quality_checklist():
    """Verify Three.js quality requirements are explicit."""
    bundle = _code_bundle()
    assert "MeshStandardMaterial" in bundle.system
    assert "DirectionalLight" in bundle.system
    assert "shadow.mapSize" in bundle.system
    assert "shadowMap" in bundle.developer
    assert "castShadow" in bundle.developer


def test_planar_mirror_uses_reflector_not_envmap():
    """Planar mirrors must use THREE.Reflector, not MeshStandardMaterial+envMap."""
    bundle = _code_bundle()
    for prompt in (bundle.system, bundle.developer):
        assert "Reflector" in prompt
        assert "envMap" in prompt
    assert "objects/Reflector.js" in bundle.system


def test_structured_prompt_has_backend_guidance():
    """Verify structured system prompt has backend-specific guidance."""
    system = _structured_bundle().system
    assert "BACKEND-SPECIFIC GUIDANCE" in system
    assert "SVG (structural composition" in system
    assert "HTML (text-driven layout" in system
    assert "Three.js (3D geometry" in system
    assert "Python (numeric sketches" in system


def test_developer_prompt_has_examples_per_backend():
    """Verify structured developer prompt has examples for all backends."""
    developer = _structured_bundle().developer
    assert "BACKEND-SPECIFIC EXAMPLES" in developer
    assert "SVG (composition, spatial relations)" in developer
    assert "HTML (long text, documents, menus)" in developer
    assert "Three.js (3D geometry, physics, reflections)" in developer
    assert "metalness" in developer
    assert "roughness" in developer


def test_repair_prompt_stays_independent():
    repair = build_repair_prompt(errors="bad json", previous="oops")
    assert "Validation errors:" in repair
    assert "bad json" in repair
    assert "oops" in repair
