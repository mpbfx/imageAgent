# ADR 0003：模板控制画布 vs Free-Form 代码生成的分阶段路线

**日期:** 2026-06-18

**状态:** 已接受。本 ADR 修订并细化 ADR 0001 中"模板控制画布"的决策边界。

## 背景

ADR 0001 决定第一阶段用 **schema-owned templates** 生成可执行画布:模型只填入校验过的字段,代码不由模型自由编写。理由是测试稳定与安全。

但论文复审(`tmp/pdfs/method.txt` §3.3、`experiments.txt` §4.2)表明,GenClaw 的核心贡献正是 **code-as-brush**:让 agent 像数字画笔一样**直接编写** SVG/HTML/Three.js/Python 代码,显式构造对象、坐标、图层、文本与物理约束。论文展示的真实案例——2026 世界杯海报、滕王阁序、弹簧形变、水柱射程、镜面反射、街景合成——其表达自由度**无法由一个固定字段的 schema 表达**。

因此存在结构性张力:模板路线能跑通管道,却画不出论文案例;固定 `CanvasPlan` 又被 ADR 0001 定为 renderer 和 reviewer 共享的"中心契约",一旦围绕少数 fixture 定型,转向 free-form 时返工成本最高。

## 决策

把"模板 vs free-form"明确为**分阶段路线**,而非二选一:

- **Phase 1(脚手架):** 保留模板控制画布,但**显式承认其定位是脚手架**,用于验证 LangGraph 编排、artifact/trace、review 规则、Playwright 渲染管道,而非验证 code-as-brush 假设。文档不得把 phase-1 描述为"复现了 GenClaw 机制"。
- **Phase 2(核心机制):** 引入**受约束的 free-form 代码生成**作为一等 backend——LLM 直接产出 SVG/HTML/Three.js 源码,经静态校验后在**沙箱化的本地 renderer**(固定 viewport、超时、禁网、无 shell)中渲染。这才是论文机制的真正落地。

为降低 phase 1→2 的返工,本 ADR 追加两条约束:

- **`CanvasPlan` 须对齐四个 benchmark 任务族(GenEval++ / LongText-Bench / ImgEdit / Mind-Bench)做需求推导,而不是围绕 3 个 fixture 设计。** schema 应区分两类后端:`structured`(模板编译,phase 1)与 `code`(free-form 源码 + 校验,phase 2),让同一契约能容纳两种路线,避免 phase 2 推翻中心契约。
- **renderer 接口须从一开始就同时接受"结构化 plan"和"代码字符串"两种输入**,使 phase 2 的 free-form backend 复用 phase 1 的沙箱渲染与 artifact 写出,而非另起一套。

## 备选方案

### 方案 1:phase 1 直接做 free-form 代码生成

**不采用原因:** 无凭据无法确定性测试,且沙箱、静态校验、prompt→code 可靠性都未就绪时,测试会极度脆弱。先用模板把编排/产物/审查管道稳定下来更稳妥。

### 方案 2:永远只用模板,不断扩字段

**不采用原因:** 论文案例的表达自由度无法由固定字段穷举,会陷入"模板地狱",且始终复现不出核心机制。模板只能是过渡。

### 方案 3:phase 1 就冻结 `CanvasPlan` 为最终契约

**不采用原因:** 围绕 3 个 fixture 冻结的契约几乎必然在 phase 2 推翻。把契约对齐四任务族、并预留 `code` 后端,是更低返工的折中。

## 影响

### 正向影响

- 文档与代码不再把脚手架误称为机制复现,定位诚实。
- 中心契约预留 free-form 通道,phase 2 不必推翻 schema 与 renderer 接口。
- 沙箱渲染从 phase 1 接口层就被考虑,安全约束前置。

### 负向影响

- `CanvasPlan` 设计期变长(要对齐四任务族),plan 任务顺序需相应前置 schema 设计。
- 需要额外维护"结构化 plan"与"代码字符串"两条渲染输入路径。
- free-form 沙箱(静态校验、禁网、超时、资源限制)是独立且非平凡的工作,需单独排期与后续 ADR。

## 后续 ADR

- free-form 代码的静态校验与浏览器沙箱具体方案(CSP、禁网、超时、内存限制)。
- prompt→`CanvasPlan` 的可靠性机制(structured output / function calling / 校验失败重试)。
- search node 与 SAM/分割在图中的接入位置(对应 Mind-Bench 与 ImgEdit 机制)。

## 参考

- ADR 0001: `D:\genclaw\docs\adr\0001-genclaw-reproduction-architecture.md`
- 论文方法: `D:\genclaw\tmp\pdfs\method.txt` §3.3
- 论文实验: `D:\genclaw\tmp\pdfs\experiments.txt` §4.2
- 本地 Spec: `D:\genclaw\docs\specs\2026-06-18-genclaw-reproduction-spec.md`
