# ADR 0005：Code-as-Brush（free-form 代码生成）落地 —— SVG 先行，沙箱后置

**日期:** 2026-06-22

**状态:** 已接受。本 ADR 落实 ADR 0003 中 phase-2 的核心机制 code-as-brush，并明确其安全边界与排期。

## 背景

ADR 0003 把 GenClaw 的核心贡献 code-as-brush（让 LLM **直接编写** SVG/HTML/Three.js 源码作画）定为 phase-2，并预留了两条铁轨：schema 的 `source="code"` + `code_source`/`code_lang` 字段，以及"renderer 接口同时接受 plan 和代码字符串"的约束。

phase-1 已用真实 external provider（Claude agent + Gemini）跑通模板路线，验证了编排/产物/审查/渲染管道可用。现在落地 code-as-brush，才真正触及论文机制——此前都是脚手架（ADR 0003 明确：phase-1 不得称为"复现了机制"）。

## 决策

落地 free-form 代码渲染，但**分两步走，并刻意推迟安全沙箱**：

- **第一步（本 ADR 范围）：SVG code-as-brush。** LLM 直接产出 `<svg>` 源码，经**轻量静态校验**（标签/属性白名单、禁 `<script>`、禁外链、禁 `foreignObject`）后，复用现有 Playwright 渲染出 PNG。选 SVG 先行因为它是**纯标记、渲染时不执行 JS**，安全面最小，静态校验即可覆盖主要风险。
- **第二步（后续 ADR）：HTML/Three.js/Python free-form。** 这些含真正可执行 JS/Python，需要完整执行沙箱（禁网、超时、CSP、资源限制），单独排期。

### 安全立场（明确记录的已知债）

**本阶段刻意不实现完整执行沙箱。** 依据：本项目是**本地单机复现、非公开服务**，输入来自受信任的 LLM provider 而非匿名公网，当前优先级是**验证 code-as-brush 机制是否成立**，而非加固生产安全。

风险因此被有意接受：
- SVG 走静态校验（白名单 + 禁脚本/外链），风险较低但**非零**（SVG 仍可能有 XML 实体、引用类攻击面）。
- HTML/Three.js/Python free-form 在沙箱就绪前**不开放执行任意模型代码**。

此立场必须在代码注释与 README/reproduction-notes 中显式标注为"已知的、被推迟的安全债"，**不得**被误认为已安全。公开部署前必须先补沙箱（后续 ADR）。

## 备选方案

### 方案 1：先建完整沙箱再做 code-as-brush
**不采用：** 沙箱（禁网/超时/CSP/资源限制）是独立非平凡工作，先建会拖慢"机制是否成立"这一最关键实验。本地复现场景下风险可控，可后置。

### 方案 2：HTML/Three.js 也一起做 free-form
**不采用：** 它们执行真实 JS，没有沙箱时风险显著高于纯标记 SVG。先用最安全的 SVG 验证机制，再投入沙箱解锁其余后端。

### 方案 3：继续只用模板
**不采用：** ADR 0003 已否决——模板画不出论文案例，且永远复现不出核心机制。

## 影响

### 正向
- 首次真正触及论文核心机制，可做"模板版 vs AI 写码版 vs 纯文生图"三方对比实验，实证 code-as-brush 价值。
- 复用现有 schema 字段与 Playwright 渲染，返工小。
- SVG 静态校验器可作为后续 HTML 沙箱的第一道防线复用。

### 负向 / 风险
- **安全债**：无执行沙箱，仅 SVG 静态校验。公开部署前必须补（见安全立场）。
- LLM 写的代码可能语法/渲染出错（论文 limitations 已述），需失败处理与重试。
- 多一条渲染输入路径（代码字符串 vs 结构化 plan）需维护。

## 后续 ADR
- HTML/Three.js/Python free-form 的执行沙箱方案（CSP、禁网、超时、内存/CPU 限制）。
- code 渲染失败 → 校验错误回灌 LLM 重试的可靠性机制。

## 参考
- ADR 0003: `docs/adr/0003-template-vs-freeform-code-generation.md`
- 论文方法 §3.2-3.3（code-as-brush、digital brush）
