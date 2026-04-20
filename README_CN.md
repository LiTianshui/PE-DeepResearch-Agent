[English](README.md) | **中文**

# 项目名称

基于提示工程优化的自动化深度研究智能体

Prompt Engineering-Optimized Automated Deep Research Agent (PE-DeepResearch-Agent)

## 📝 项目简介

传统的自动化研究工具在面对复杂开放式问题时，往往存在任务拆解不够深入、搜索结果噪声较多、信息整合不够稳定，以及总结内容容易出现幻觉等问题。  
**PE-DeepResearch-Agent** 旨在解决这些问题。该项目以 [hello-agents](https://github.com/datawhalechina/hello-agents) 第 14 章中的 **Automated Deep Research Agent** 为基础，并结合 [Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) 中的关键提示工程方法，对智能体在**规划、检索、反思和报告生成**等阶段进行系统性优化。

本项目的目标不是简单地"优化几句提示词"，而是将 **Prompt Engineering** 作为一个可设计、可迭代、可评估的系统层，提升自动化深度研究智能体的可靠性、可追踪性和研究完整性。


## 🎯 项目要解决的问题

本项目主要面向以下几个痛点：

- 自动化研究任务中，子任务拆解过于浅层，难以覆盖复杂问题的关键维度。
- 搜索过程往往是一次性的，缺少基于中间结果的动态调整能力。
- 信息总结容易出现事实遗漏、来源混杂或缺乏证据支撑。
- 最终报告虽然语言流畅，但不一定具备足够的可验证性和可信度。
- 缺少对研究结果的自我审查与补充检索机制，导致研究链路不完整。
- 关键节点单次生成偏差较大，缺乏稳定性保障。


## ✨ 核心功能

- **结构化任务规划**：将用户输入的研究主题拆解为多个清晰、可执行、可检索的子任务，并携带检索意图、时效性要求和满意标准等阶段契约字段。
- **迭代式搜索与查询改写**：基于 ReAct 循环根据阶段性结果动态调整检索策略，支持同义词扩展、子维度聚焦、时间限定等多种改写策略。
- **基于证据的信息总结**：从搜索结果中抽取关键 claims、evidence 和 sources，强制绑定来源引用，区分推断性结论与证据支持的结论。
- **反思驱动的研究闭环**：Reflexion 机制在总结后自动评估证据充分性、来源多样性、时效性和矛盾点，不达标则触发补充搜索与重新总结。
- **关键节点一致性增强**：在 Planner 和 Summarizer 两个高价值节点引入 Self-Consistency，通过多次采样 + Judge 选优，降低单次生成偏差。
- **可追踪的最终报告生成**：整合各子任务的结构化契约数据，区分"证据支持的结论"与"综合推断"，并保留来源引用和时效性警告。


## 🔗 系统流水线

```
用户输入
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Planner（+ Self-Consistency）                                    │
│  将研究主题拆解为子任务列表，每个任务携带：                             │
│  search_intent / freshness / success_criteria                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │ 子任务列表
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  ReAct Search Loop（每个子任务独立执行）                             │
│  Reason → Act(search) → Observe → 改写 Query → 循环               │
│  Observer LLM 判断 DONE / CONTINUE，动态决定下一轮检索策略            │
└──────────────────────┬───────────────────────────────────────────┘
                       │ merged_context（含轮次标签）
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Summarizer（+ Self-Consistency）                                    │
│  输出 <chain_output> 结构化块：                                        │
│  claims / evidence / sources / inferred_claims / freshness_warnings │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ 摘要 + 契约数据
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Reflexion Reviewer                                              │
│  四维评估：证据充分性 / 来源多样性 / 时效性 / 矛盾检测                  │
│  pass → 继续 │ fail → execute_targeted() 补充检索 → 重新总结        │
└──────────────────────┬───────────────────────────────────────────┘
                       │ 全部子任务完成
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Reporter                                                        │
│  消费 claims/evidence/source_citations/inferred_claims           │
│  输出结构化报告：证据支持的结论 vs 【综合推断】；含引用和时效性警告         │
└──────────────────────────────────────────────────────────────────┘
```


## 🚀 与原项目相比的主要改进点

### 1. Prompt Chaining — 阶段契约，强化链路结构化传递

将复杂研究任务拆分为多个清晰阶段，并将前一阶段的**结构化输出**作为下一阶段的输入，而非自由文本传递。

**核心实现：**
- `models.py`：`TodoItem` 新增 7 个阶段契约字段
  - Planner 契约：`search_intent` / `freshness`（latest \| historical \| both）/ `success_criteria`
  - Summarizer 契约：`claims` / `evidence` / `missing_info` / `confidence`
- `prompts.py`：三阶段 prompt 升级为严格契约——Planner 输出 JSON 从 3 字段扩展至 6 字段；Summarizer 强制输出 `<chain_output>` 结构化块；Reporter 新增 `CHAIN_INPUT_RULES`，只能基于上游契约数据得出结论
- `services/text_processing.py`：新增 `extract_chain_output()`，解析并剥离 `<chain_output>` 块
- `services/planner.py` / `summarizer.py` / `reporter.py`：全链路解析与消费契约字段，无结构化数据时优雅降级为纯文本

---

### 2. ReAct — 动态搜索循环，替换单次线性检索

将原来"每个任务只搜索一次"的线性流程，升级为 **Reason → Act(search) → Observe → Repeat** 的 ReAct 循环。

**核心实现：**
- `services/react_search.py`（新建）：`ReActSearchService` 核心引擎
  - `execute()`：在 `max_web_research_loops` 上限内循环执行搜索
  - 每轮 ACT 后调用 `_reason_next_action()` 触发 Observer LLM 推断
  - Observer 返回 `DONE` 或 `CONTINUE + 新 query`，实现动态 query 改写
  - 每轮结果加轮次标签后合并为 `merged_context`，传给 Summarizer
- `prompts.py`：新增 `react_observer_system_prompt`，包含 `DECISION_RULES` 与 `QUERY_REWRITE_STRATEGIES`（同义词扩展、子维度聚焦、时间限定、争议追加等）
- `agent.py`：`_execute_task()` 替换单次 `dispatch_search` 为 `react_search.execute()`，推送 `react_search_step` / `react_thought` 事件至前端
- `models.py`：`TodoItem` 新增 `react_queries`（各轮 query 列表）与 `react_loop_count`（实际执行轮数）

---

### 3. Reflexion — 自我评估闭环，驱动缺口补充检索

在每轮 Summarize 之后插入 **Reviewer LLM 调用**，从四个维度评估摘要质量，若不达标则自动触发补充搜索。

**核心实现：**
- `services/reflexion.py`（新建）：`ReflexionService` 审查引擎
  - `review()`：调用 Reviewer LLM，返回 `quality` / `gaps` / `supplemental_queries` 等字段
  - `_build_prompt()`：注入 Planner 契约 + Summarizer 契约 + ReAct 搜索轨迹 + 历史反思记录（memory），避免重复相同方向
  - `is_pass()`：静态方法判断 `quality` 值
- `services/react_search.py`：新增 `execute_targeted()`，直接执行 Reflexion 指定的补充 queries，不经 Observer 推断，每条结果加 `[Reflexion 补充检索 N]` 标签
- `prompts.py`：新增 `reflexion_reviewer_system_prompt`，包含 `EVALUATION_DIMENSIONS`（证据充分性 / 来源多样性 / 时效性验证 / 矛盾检测）、`QUALITY_THRESHOLD` 和 `SUPPLEMENTAL_QUERY_RULES`
- `agent.py`：`_execute_task()` 在 `task.summary` 设置后加 Reflexion 闭环；反思结果追加 `task.reflections` 作为 memory 供后续轮次参考
- `config.py`：新增 `max_reflexion_rounds`（默认 1，0 = 关闭）

---

### 4. Self-Consistency — 关键节点局部增强

对成本敏感的两个高价值节点（Planner + Summarizer）应用 SC，而非全链路开启，在控制开销的同时显著降低单次生成偏差。

**核心实现：**
- `services/self_consistency.py`（新建）：`SelfConsistencyService`
  - 采样阶段使用 `sc_llm`（高温度）生成多样候选，Judge 阶段使用主 `llm`（temperature=0）确定性判断
  - `sample_and_select_plan()`：调用 N 次采样 + Plan Judge，返回最优方案
  - `sample_and_select_summary()`：调用 N 次采样 + Summary Judge，返回最优总结
  - `_parse_judge_output()`：解析 `best_index`，失败时默认返回 0
- `prompts.py`：新增 `sc_plan_judge_system_prompt`（5 维评选：覆盖广度 / 互补性 / 可执行性等）和 `sc_summary_judge_system_prompt`（5 维评选：证据覆盖 / 准确性 / chain_output 质量等）
- `agent.py`：`_init_llm()` 重构，支持创建多温度 LLM 实例；新增 `self.sc_llm`（高温度）和 `self.sc_service`（仅在 SC 启用时初始化）
- `config.py`：新增三个 SC 配置项（见配置说明）

---

### 5. RAG / Truthfulness Constraints — 强化证据绑定与可验证性

在 Summarizer 输出和 Reporter 生成两个环节引入严格的 **真实性约束**，区分"证据支持的结论"与"综合推断"，并强制附上来源引用和时效性警告。

**核心实现：**
- `prompts.py`：
  - Summarizer 新增 `<RAG_TRUTHFULNESS_CONSTRAINTS>`，要求每条 claim 绑定来源（title / url / date）；无单一来源的推断性结论须在 `inferred_claims` 中记录索引并加「【综合推断】」标注；`freshness=latest` 时超过 18 个月的来源须在 `freshness_warnings` 中告警
  - Reporter 新增 `<TRUTHFULNESS_RULES>`，将报告拆分为"证据支持的结论"与"推断性总结"两个部分
- `services/summarizer.py`：扩展 `_apply_chain_data()`，解析 `<chain_output>` 中三个新 RAG 字段：`sources → source_citations`、`inferred_claims`、`freshness_warnings`
- `services/reporter.py`：将所有 RAG 契约字段注入 Reporter prompt；用「【综合推断】」标记推断性声明；每个任务附上 `source_citations`、`freshness_warnings` 和 `inferred_claims` 索引


## 🚀 快速开始

### 环境要求

```bash
python --version  # Python 3.10 或更高
node --version    # Node.js 16 或更高
npm --version     # npm 8 或更高
```

### 后端

**1. 创建并激活 conda 环境**

```bash
conda create -n deepresearch python=3.11 -y
conda activate deepresearch
```

**2. 安装依赖**

```bash
cd PE-DeepResearch-Agent/backend
python -m pip install "hello-agents==0.2.9" huggingface_hub \
    fastapi "tavily-python>=0.5.0" "python-dotenv==1.0.1" "requests>=2.31.0" \
    "openai>=1.12.0" "uvicorn[standard]>=0.32.0" "ddgs>=9.6.1" "loguru>=0.7.3" \
    -i https://mirrors.aliyun.com/pypi/simple
```

**3. 配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env`，至少填写以下四项：

```env
LLM_PROVIDER=custom
LLM_MODEL_ID=你的模型名称        # 如 gemini-2.0-flash
LLM_API_KEY=你的API密钥
LLM_BASE_URL=模型接口地址        # 如 https://generativelanguage.googleapis.com/v1beta/openai/
```

> 搜索引擎默认使用 `duckduckgo`，无需额外 API Key。如需使用 Tavily，在 `.env` 中设置 `SEARCH_API=tavily` 并填入 `TAVILY_API_KEY`。

**4. 启动后端**

```bash
python src/main.py
```

看到以下输出说明启动成功：

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 前端

新开一个终端窗口：

```bash
cd PE-DeepResearch-Agent/frontend
npm install
npm run dev
```
看到以下输出说明启动成功：

```
  VITE v5.0.0  ready in 500 ms

  ➜  Local:   http://localhost:5174/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

打开浏览器访问 `http://localhost:5173` 即可开始使用。


## ⚙️ 配置说明

所有配置项可通过环境变量或 `Configuration` 对象覆盖：

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| `max_web_research_loops` | `MAX_WEB_RESEARCH_LOOPS` | `3` | 每个子任务的 ReAct 最大搜索轮数 |
| `max_reflexion_rounds` | `MAX_REFLEXION_ROUNDS` | `1` | Reflexion 最大审查轮数，`0` = 关闭 |
| `sc_plan_samples` | `SC_PLAN_SAMPLES` | `3` | Planner SC 采样数，`1` = 关闭 |
| `sc_summary_samples` | `SC_SUMMARY_SAMPLES` | `3` | Summarizer SC 采样数，`1` = 关闭 |
| `sc_temperature` | `SC_TEMPERATURE` | `0.7` | SC 采样温度，建议范围 0.5–1.0 |


## 🛠️ 技术栈

- **基础框架**：hello-agents
- **提示工程方法**：Prompt Chaining、ReAct、Reflexion、Self-Consistency、RAG + Truthfulness Constraints
- **核心服务模块**：
  - `services/react_search.py`：ReAct 动态搜索循环引擎
  - `services/reflexion.py`：Reflexion 自我评估审查引擎
  - `services/self_consistency.py`：Self-Consistency 采样与 Judge 服务
  - `services/planner.py`：结构化任务规划服务
  - `services/summarizer.py`：基于契约的信息总结服务
  - `services/reporter.py`：RAG 感知的报告生成服务
- **工具与 API**：Web Search API（Tavily / Perplexity / DuckDuckGo / SearXNG）、LLM API、结构化输出解析
- **后端**：Python、FastAPI
- **前端**：Vue3、TypeScript


## 📁 项目结构

```
PE-DeepResearch-Agent/
├── backend/
│   └── src/
│       ├── agent.py               # 智能体主协调器
│       ├── config.py              # 配置项（含 ReAct / Reflexion / SC 参数）
│       ├── models.py              # 数据模型（TodoItem 含阶段契约字段）
│       ├── prompts.py             # 所有阶段的系统提示词
│       ├── main.py                # FastAPI 入口
│       └── services/
│           ├── planner.py         # 任务规划（接入 SC）
│           ├── react_search.py    # ReAct 搜索循环 + Reflexion 定向检索
│           ├── reflexion.py       # Reflexion 审查引擎
│           ├── self_consistency.py# SC 采样与 Judge 服务
│           ├── summarizer.py      # 摘要生成（接入 SC + RAG 契约）
│           ├── reporter.py        # 报告生成（消费 RAG 契约字段）
│           ├── text_processing.py # chain_output 解析工具
│           └── notes.py           # 笔记工具
├── frontend/                      # Vue3 + TypeScript 前端
├── LICENSE
└── README.md
```


## 📄 许可证

MIT License

## 🙏 致谢

感谢 [Datawhale 社区](https://github.com/datawhalechina) 与 [hello-agents](https://github.com/datawhalechina/hello-agents) 项目提供自动化深度研究智能体的基础思路，  
也感谢 [DAIR.AI](https://github.com/dair-ai) 与 [Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) 项目提供系统化的提示工程方法参考。
