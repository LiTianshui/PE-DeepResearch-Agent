# 项目名称

基于提示工程优化的自动化深度研究智能体

Prompt Engineering-Optimized Automated Deep Research Agent (PE-DeepResearch-Agent)

## 📝 项目简介

传统的自动化研究工具在面对复杂开放式问题时，往往存在任务拆解不够深入、搜索结果噪声较多、信息整合不够稳定，以及总结内容容易出现幻觉等问题。  
**PE-DeepResearch-Agent** 旨在解决这些问题。该项目以 [hello-agents](https://github.com/datawhalechina/hello-agents) 第 14 章中的 **Automated Deep Research Agent** 为基础，并结合 [Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) 中的关键提示工程方法，对智能体在**规划、检索、反思和报告生成**等阶段进行系统性优化。

本项目的目标不是简单地“优化几句提示词”，而是将 **Prompt Engineering** 作为一个可设计、可迭代、可评估的系统层，提升自动化深度研究智能体的可靠性、可追踪性和研究完整性。


## 🎯 项目要解决的问题

本项目主要面向以下几个痛点：

- 自动化研究任务中，子任务拆解过于浅层，难以覆盖复杂问题的关键维度。
- 搜索过程往往是一次性的，缺少基于中间结果的动态调整能力。
- 信息总结容易出现事实遗漏、来源混杂或缺乏证据支撑。
- 最终报告虽然语言流畅，但不一定具备足够的可验证性和可信度。
- 缺少对研究结果的自我审查与补充检索机制，导致研究链路不完整。

## ✨ 核心功能

- **结构化任务规划**：将用户输入的研究主题拆解为多个清晰、可执行、可检索的子任务。
- **迭代式搜索与查询改写**：根据阶段性结果动态调整检索策略，而不是仅执行一次固定搜索。
- **基于证据的信息总结**：从搜索结果中抽取关键 claims、evidence 和 sources，降低幻觉风险。
- **反思驱动的研究闭环**：在总结后增加 reviewer 机制，自动检查证据是否充分、来源是否多样、是否存在信息缺口。
- **可追踪的最终报告生成**：将各子任务的结果整合为结构化研究报告，并尽可能保留来源与引用信息。

## 🚀 与原项目相比的主要改进点

- **Prompt Chaining**：强化阶段间的结构化协作。项目将复杂研究任务拆分为多个清晰阶段，并将前一阶段的结构化输出作为下一阶段的输入。相比宽泛的自由式 prompt，这种方式更有利于提升系统的稳定性、可控性和可调试性。

- **ReAct 风格检索**：让搜索过程具备动态决策能力。系统不再采用线性的一次性搜索流程，而是结合推理与行动，让智能体根据当前结果决定下一步是补充检索、改写 query、验证已有结论，还是查找冲突观点，从而更接近真实研究过程。

- **Reflexion 机制**：引入自我评估与自动补充检索。在每轮总结之后，系统会增加一个 reviewer 阶段，用于判断当前证据是否充分、来源是否单一、是否缺少时间敏感信息，以及是否存在尚未处理的矛盾结论。若结果不满足要求，系统将自动进入下一轮检索与修正。

- **Self-Consistency**：用于关键节点的局部增强。项目计划在部分高价值环节引入 Self-Consistency，例如对子任务规划结果进行多版本采样与筛选，或对同一组搜索结果生成多个摘要后进行一致性选择，以降低单次生成偏差带来的不稳定性。

- **RAG 与真实性约束**：强化证据绑定与可验证性。对于知识密集型和时效性较强的问题，系统将尽量通过外部检索结果来支撑关键结论，并在最终报告中区分“证据支持的结论”与“综合性推断”，以提升整体可信度。

## 🛠️ 技术栈

- **基础框架**：hello-agents
- **提示工程方法**：Prompt Chaining、ReAct、Reflexion、Self-Consistency、RAG
- **智能体能力**：任务规划、搜索编排、证据总结、反思审查、报告生成
- **工具与 API**：Web Search API、LLM API、结构化输出解析与校验工具
- **后端方向**：Python、FastAPI
- **前端方向**：Vue3、TypeScript


## 📄 许可证

MIT License

## 🙏 致谢

感谢 [Datawhale 社区](https://github.com/datawhalechina) 与 [hello-agents](https://github.com/datawhalechina/hello-agents) 项目提供自动化深度研究智能体的基础思路，  
也感谢 [DAIR.AI](https://github.com/dair-ai) 与 [Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) 项目提供系统化的提示工程方法参考。