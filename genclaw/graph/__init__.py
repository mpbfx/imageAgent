"""GenClaw LangGraph 编排。

LangGraph *只*管编排;领域逻辑(schema、renderers、generators、review)
各自独立成模块。本包定义的 state 是纯 Pydantic 模型,不依赖
langgraph,这样即使没装编排栈也能 import 与单测。
"""
