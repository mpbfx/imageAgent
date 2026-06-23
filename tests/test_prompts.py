"""Tests for provider prompt contracts."""

from genclaw.agent.prompts import CODE_SYSTEM_PROMPT
from genclaw.agent.prompts import CODE_DEVELOPER_PROMPT


def test_code_prompt_requires_cjk_font_stack_for_text():
    assert "Noto Serif CJK SC" in CODE_SYSTEM_PROMPT
    assert "Source Han Serif SC" in CODE_SYSTEM_PROMPT
    assert "SimSun" in CODE_SYSTEM_PROMPT


def test_code_developer_prompt_allows_html_code_source():
    assert "complete, valid SVG document" not in CODE_DEVELOPER_PROMPT
    assert "code_lang" in CODE_DEVELOPER_PROMPT
    assert "complete, self-contained document" in CODE_DEVELOPER_PROMPT
