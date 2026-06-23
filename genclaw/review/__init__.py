"""GenClaw 的 review 层:对照 plan 中声明的 checks,验证一次完整渲染产出的结果。

本层对外只暴露 :class:`~genclaw.review.base.Reviewer` 抽象接口,具体实现
包括基于规则的结构化检查(:mod:`genclaw.review.rules`)和基于 VLM 的感知
检查(:mod:`genclaw.review.vlm`),生产环境默认二者组合运行
(:class:`~genclaw.review.composite.CompositeReviewer`)。
"""
