"""GenClaw LangGraph orchestration.

LangGraph owns *only* orchestration; domain logic (schema, renderers,
generators, review) stays in independent modules. The state defined here is a
plain Pydantic model with no langgraph dependency, so it imports and tests
without the orchestration stack installed.
"""
