# GenClaw 复现 · 工作规划（极简）

> single source of truth 是 `docs/specs` 与 `docs/plans`；本文件只做**一页纸进度总览**，便于快速对齐"做到哪了、还差什么"。状态：✅ 完成 / ◑ 部分（结构在、机制未落地）/ ✗ 未做。
> 最后更新：2026-06-22。

## 一句话定位

论文 GenClaw（arXiv 2605.30248）的独立复现。三层范式 **Think（认知：意图+搜索+推理）→ Sketch（代码画布）→ Color（图像模型上色+审查）**，code-as-brush 为核心主张。本复现已搭好三层外壳并接通真实 provider，但论文两个最硬的差异化机制（分层编辑、free-form code-as-brush）仍是 phase 2。

## 已完成 ✅

| 模块 | 状态 | 说明 |
| --- | --- | --- |
| 核心 schema `CanvasPlan` | ✅ | 中心契约，对齐 4 任务族，structured/code 双来源判别 |
| Artifact-first 产物 + JSONL trace | ✅ | 每 run 完整目录，可追溯 |
| LangGraph 编排 | ✅ | `conceptualize→search→render→generate→review→route`，实跑（langgraph 1.2.5）。注：意图识别 + 选后端都在 `conceptualize` 内完成（agent 出的 plan 含 `task_type`/`backend`）；`render` 只按 `plan.backend` 查表选 renderer，不做判断 |
| Fixture agent（确定性冒烟） | ✅ | 关键字匹配，无凭据 CI 路径 |
| 渲染后端 ×5 | ✅ | SVG / HTML / Three.js(WebGL) / Python(matplotlib) / Canvas，源码编译 + PNG |
| 规则审查 | ✅ | object_count/contains_text/backend/artifact/image_size |
| Mock generator | ✅ | fixture 模式复制 sketch，无 photorealism |
| CLI | ✅ | `run / render / review / bench` |
| Mini benchmark | ✅ | 本地回归冒烟（非官方 metric，带免责声明） |
| 外部 provider（意图识别） | ✅ | Claude-Opus agent，structured-output + 有界重试 |
| 真实 provider 实跑闭环 | ✅ | 经 packyapi 代理：Claude agent + Gemini 图像(`images/edits`) + Claude VLM 审查 |
| base_url 代理支持 + .env | ✅ | Anthropic/Gemini 兼容端点，凭据 gitignore |
| Composite 审查（结构/感知分层） | ✅ | 结构检查只查草图、VLM 只判 final，修掉"backend=svg 判栅格图"误杀 |
| 文档（README / reproduction-notes / spec 覆盖度表） | ✅ | 含 PyPI 镜像、机制覆盖度诚实声明 |

**实跑验证产出**（`outputs/runs/`）：量子海报 0.88 / 中餐菜单 0.82（繁体生僻字保真）/ 气球组合 0.95 / 桌面静物 0.78 / 读书会卡 0.925 / 销售柱状图 0.975（数据精确）。
**对照实验结论**：常规生活场景（农贸市场、猫咪）frontier 文生图单挑已足够，GenClaw 边际价值小；优势集中在**精确计数 / 空间遮挡 / 数据保真 / 生僻字**这类硬约束任务——与论文 limitations 预言一致。

## 部分完成 ◑

| 项 | 缺口 |
| --- | --- |
| 搜索 / 知识接地 | 节点+Tavily adapter 在；默认 NullSearch 不检索，真实多轮检索未实跑验证 |
| 推理（先算后画） | schema 有 `ReasoningStep`，无自动推理 provider 填充 |
| 视觉生成保真 | 已实跑；存在上色漂移（计数/位置/遮挡偏离草图），revise 反馈循环仍是占位 |

## 未做 ✗（按价值排序）

1. **分层编辑 + SAM3 + inpainting**（ImgEdit，论文最硬定量主张 PSNR/SSIM）— 最大缺口，仅 `EditOp` 占位
2. **执行沙箱** — 解锁 HTML/Three.js/Python 的 free-form code-as-brush（SVG 已落地）；也是补 code-as-brush 安全债的地方
3. **官方 benchmark + official metric**（GenEval++/LongText/ImgEdit/Mind-Bench）— 暂缓
4. **object_count check 程序化生成** — 当前靠 LLM 自报，大量对象时计数不准（农贸市场实跑暴露）
5. **生成保真增强** — 多通道条件 / 约束分级（硬锁语义、放开美学）/ 确定性校验+局部 inpainting 自纠

## 已落地的核心机制 ✅（原 phase-2）

- **code-as-brush（SVG）**：`--mode external-code`，Claude 直接手写 SVG 源码（含渐变/引线/体积感），静态校验放行后渲染。实跑验证（气球 prompt，88KB sketch vs 模板 6KB）。安全沙箱有意后置（ADR 0005，本地复现风险可控）。

## 下一步建议

- **最小确定性修复**：#4 object_count 改为代码统计实际对象数填充（消除认知层自洽 bug，是确定性校验地基）。
- **真正推进复现**：#1 分层编辑 + SAM3，论文数据最硬、缺口最大。
- 创新方向（架构级组合，非新算法）：多通道结构条件治漂移、约束分级治塑料感、复用 ImgEdit 的"SAM+inpainting"做生成自纠闭环。详见与对话记录。
