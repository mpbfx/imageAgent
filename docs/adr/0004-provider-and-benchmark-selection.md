# ADR 0004：Provider 与 Benchmark 选型——默认对齐论文栈

**日期:** 2026-06-18

**状态:** 已接受。本 ADR 修订 ADR 0001 中"vendor-neutral 优先"的默认取向。

## 背景

ADR 0001 把 provider-pluggable、vendor-neutral 作为首要原则,fixture/mock 为一等公民。用户进一步明确意图:**能与论文一致的就一致**,替代方案只在论文同款拿不到时才用。

论文(`tmp/pdfs/method.txt`、`experiments.txt` §4.1)的实际技术栈大部分可获取:

- 画布后端 SVG / HTML/CSS / Three.js / Python / Canvas 是开源标准,不存在替代问题。
- 评测用 GenEval++、LongText-Bench、ImgEdit、Mind-Bench,均为公开 benchmark,论文报告其 official metrics。
- Agent backbone = Claude-Opus-4.6,默认 generator = Gemini-3.1-Flash-Image(Nano-Banana),分割 = SAM3——均可获取(SAM3 见 `facebookresearch/sam3`,API 模型需凭据)。

因此"无法对齐论文"在多数环节并不成立,vendor-neutral 不应反过来让默认实现偏离论文。

## 决策

**接口仍可插拔,但默认实现指向论文同款栈。** 调和如下:

- **画布层:直接一致。** SVG/HTML/Three.js/Canvas 即论文所用,无替代。
- **Benchmark:对齐官方实现为目标。** 接 GenEval++/LongText-Bench/ImgEdit/Mind-Bench 官方 repo 与 metric;mini fixture 降级为开发期冒烟,不再充当复现主体。编辑一致性 PSNR/SSIM follow CoCoEdit 的非编辑区 mask 方案。
- **模型栈:默认 = 论文同款。** backbone/review VLM = Claude-Opus-4.6;默认 generator = Gemini-3.1-Flash-Image;分割 = SAM3。
- **退路而非默认:** 开源替代(FLUX.1-Kontext、Qwen-Image、SDXL+ControlNet、SAM2、SearXNG 等)保留为可选 provider,仅在凭据/权重不可得时启用。
- **fixture/mock:** 降级为无凭据 CI 冒烟,不再是 spec 主交付。

## 影响

### 正向影响

- 默认路径与论文一致,数值可比、机制可对照,真正服务"复现"目标。
- 接口仍可插拔,凭据缺失时可退到开源替代,不阻塞开发。
- 评测接官方 benchmark,避免 mini fixture 的"自说自话"。

### 负向影响

- 默认路径需要 API 凭据(Opus、Gemini)与 SAM3 权重,CI 完整跑需配置;fixture 仅覆盖冒烟。
- 接官方 benchmark 工作量大于 mini fixture,但这是一致性的必要代价。
- SAM3 / 闭源 API 的可用性与版本仍可能变化,故保留可插拔接口与退路。

## 默认 vs 退路一览

| 环节 | 默认(对齐论文) | 退路(不可得时) |
|---|---|---|
| backbone / review VLM | Claude-Opus-4.6 | 其它多模态 LLM API |
| 默认 generator | Gemini-3.1-Flash-Image | FLUX.1-Kontext / Qwen-Image / SDXL+ControlNet |
| 分割 | SAM3 | SAM2 + Grounding DINO |
| 搜索 | search tool(多轮) | Tavily / SearXNG(自托管) |
| benchmark | 官方 GenEval++/LongText/ImgEdit/Mind-Bench | 本地 mini fixture(仅冒烟) |
| 画布 | SVG/HTML/Three.js/Canvas | 无替代(本即开源标准) |

## 待核实

- ~~SAM3 权重/代码/许可的发布状态~~ **已确认(2026-06-18):`facebookresearch/sam3` 已发布可用,分割默认直接用 SAM3。** SAM2 + Grounding DINO 仅保留为纯可选退路。落地时仍需在代码注释中记录所用 SAM3 版本与许可条款。

## 参考

- ADR 0001: `D:\genclaw\docs\adr\0001-genclaw-reproduction-architecture.md`
- 论文实验设置: `D:\genclaw\tmp\pdfs\experiments.txt` §4.1
- SAM3: https://github.com/facebookresearch/sam3
