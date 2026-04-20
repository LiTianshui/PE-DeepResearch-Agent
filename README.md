**English** | [中文](README_CN.md)

# PE-DeepResearch-Agent

Prompt Engineering-Optimized Automated Deep Research Agent


## 📝 Overview

Conventional automated research tools often struggle with complex, open-ended questions — sub-tasks are decomposed too shallowly, search results are noisy, summaries lack stable grounding, and final reports are prone to hallucination.

**PE-DeepResearch-Agent** addresses these issues. Built on top of the **Automated Deep Research Agent** from [hello-agents](https://github.com/datawhalechina/hello-agents) Chapter 14, it applies five prompt engineering techniques from the [Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) to systematically improve the agent's **planning, retrieval, reflection, and report generation** stages.

The goal is not to tweak a few prompt strings, but to treat **Prompt Engineering** as a designable, iterable, and evaluable system layer — improving the reliability, traceability, and research integrity of the automated pipeline.


## 🎯 Problems Addressed

- Sub-task decomposition is too shallow to cover the key dimensions of complex questions.
- Search is a single-pass process with no dynamic adjustment based on intermediate results.
- Summaries suffer from factual omissions, mixed sources, and weak evidence grounding.
- Final reports are fluent but not necessarily verifiable or trustworthy.
- No self-evaluation or gap-filling mechanism exists, leaving the research chain incomplete.
- Single-pass generation at critical nodes produces unstable, high-variance outputs.


## ✨ Key Features

- **Structured Task Planning**: Decomposes a research topic into clear, executable sub-tasks, each carrying stage-contract fields for search intent, freshness requirements, and success criteria.
- **Iterative Search with Query Rewriting**: A ReAct loop dynamically adjusts retrieval strategy based on intermediate results, with strategies including synonym expansion, sub-dimension focus, and recency filtering.
- **Evidence-Grounded Summarization**: Extracts claims, evidence, and sources from search results; enforces source binding; and distinguishes inferred conclusions from evidence-backed ones.
- **Reflexion-Driven Research Loop**: After each summarization, a Reviewer LLM scores four dimensions — evidence sufficiency, source diversity, recency, and contradiction — and triggers targeted gap-filling re-searches on failure.
- **Self-Consistency at Critical Nodes**: Applies multi-sample voting at the two highest-variance nodes (Planner + Summarizer) to reduce single-pass bias without multiplying cost across the full pipeline.
- **Traceable Report Generation**: Integrates structured contract data from all sub-tasks; distinguishes evidence-backed conclusions from inferential summaries; preserves source citations and freshness warnings.


## 🔗 System Pipeline

```
User Input
   │
   ▼
┌──────────────────────────────────────────────────────────────────┐
│  Planner (+ Self-Consistency)                                    │
│  Decomposes topic into sub-tasks, each carrying:                 │
│  search_intent / freshness / success_criteria                    │
└──────────────────────┬───────────────────────────────────────────┘
                       │ sub-task list
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  ReAct Search Loop (per sub-task)                                │
│  Reason → Act(search) → Observe → Rewrite Query → Repeat        │
│  Observer LLM decides DONE / CONTINUE with new query            │
└──────────────────────┬───────────────────────────────────────────┘
                       │ merged_context (with round labels)
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Summarizer (+ Self-Consistency)                                    │
│  Outputs structured <chain_output> block:                           │
│  claims / evidence / sources / inferred_claims / freshness_warnings │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ summary + contract data
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Reflexion Reviewer                                              │
│  4-dimension scoring: evidence / diversity / recency / conflict  │
│  pass → continue │ fail → execute_targeted() → re-summarize     │
└──────────────────────┬───────────────────────────────────────────┘
                       │ all sub-tasks complete
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Reporter                                                        │
│  Consumes claims / evidence / source_citations / inferred_claims │
│  Outputs structured report: evidence-backed vs. [Inferred];     │
│  includes source citations and freshness warnings                │
└──────────────────────────────────────────────────────────────────┘
```


## 🚀 Improvements Over the Baseline

### 1. Prompt Chaining — Typed Stage Contracts

Replaces free-text handoffs between agents with **structured stage contracts**, ensuring every downstream stage only consumes validated upstream data.

**Implementation:**
- `models.py`: `TodoItem` gains 7 contract fields
  - Planner contract: `search_intent` / `freshness` (latest \| historical \| both) / `success_criteria`
  - Summarizer contract: `claims` / `evidence` / `missing_info` / `confidence`
- `prompts.py`: All three stage prompts upgraded to strict contracts — Planner JSON expanded from 3 to 6 fields; Summarizer enforces `<chain_output>` XML block; Reporter adds `CHAIN_INPUT_RULES` requiring conclusions to trace back to upstream data
- `services/text_processing.py`: New `extract_chain_output()` parses and strips the `<chain_output>` block
- `services/planner.py` / `summarizer.py` / `reporter.py`: Full pipeline parses and consumes contract fields; graceful fallback to plain text when structured data is absent

---

### 2. ReAct — Dynamic Search Loop

Replaces the single-pass search with a **Reason → Act(search) → Observe → Repeat** loop, up to a configurable maximum number of iterations per sub-task.

**Implementation:**
- `services/react_search.py` (new): `ReActSearchService` core engine
  - `execute()`: loops within `max_web_research_loops` budget
  - After each ACT, calls `_reason_next_action()` to invoke an Observer LLM
  - Observer returns `DONE` or `CONTINUE + new query` with rewrite strategies (synonym expansion, sub-dimension focus, recency filter, controversy append, etc.)
  - Results from each round are tagged and merged into `merged_context` for the Summarizer
- `prompts.py`: New `react_observer_system_prompt` with `DECISION_RULES` and `QUERY_REWRITE_STRATEGIES`
- `agent.py`: `_execute_task()` replaces single `dispatch_search` call with `react_search.execute()`; pushes `react_search_step` / `react_thought` events to the frontend
- `models.py`: `TodoItem` gains `react_queries` (per-round query list) and `react_loop_count`

---

### 3. Reflexion — Self-Evaluation Closed Loop

Inserts a **Reviewer LLM call** after each summarization step to assess quality across four dimensions; automatically triggers gap-filling re-searches on failure.

**Implementation:**
- `services/reflexion.py` (new): `ReflexionService` review engine
  - `review()`: calls Reviewer LLM, returns `quality` / `gaps` / `supplemental_queries`
  - `_build_prompt()`: injects Planner contract + Summarizer contract + ReAct search trace + accumulated reflection history (memory) to prevent repeated search directions
  - `is_pass()`: static helper to evaluate `quality` field
- `services/react_search.py`: New `execute_targeted()` runs Reflexion-specified queries directly without Observer inference; tags results with `[Reflexion Supplement N]`
- `prompts.py`: New `reflexion_reviewer_system_prompt` with `EVALUATION_DIMENSIONS`, `QUALITY_THRESHOLD`, and `SUPPLEMENTAL_QUERY_RULES`
- `agent.py`: Reflexion loop appended after `task.summary` is set; reflection results appended to `task.reflections` as memory for subsequent rounds
- `config.py`: New `max_reflexion_rounds` (default 1, 0 = disabled)

---

### 4. Self-Consistency — Selective Sampling at Critical Nodes

Applies SC to the two highest-impact nodes (Planner + Summarizer) rather than the full pipeline, reducing single-pass variance while keeping cost controlled.

**Implementation:**
- `services/self_consistency.py` (new): `SelfConsistencyService`
  - Sampling phase uses `sc_llm` (high temperature) for diverse candidates; Judge phase uses main `llm` (temperature=0) for deterministic selection
  - `sample_and_select_plan()`: N samples + Plan Judge → best plan response
  - `sample_and_select_summary()`: N samples + Summary Judge → best summary response
  - `_parse_judge_output()`: parses `best_index`; defaults to 0 on failure
- `prompts.py`: New `sc_plan_judge_system_prompt` (5-dimension rubric: coverage breadth, complementarity, executability, etc.) and `sc_summary_judge_system_prompt` (5-dimension rubric: evidence coverage, accuracy, chain_output quality, etc.)
- `agent.py`: `_init_llm()` refactored to support multi-temperature LLM instances; adds `self.sc_llm` and `self.sc_service` (initialized only when SC is enabled)
- `config.py`: Three new SC config fields (see Configuration section)

---

### 5. RAG / Truthfulness Constraints — Evidence Binding and Verifiability

Introduces strict **truthfulness constraints** at both the Summarizer output and Reporter generation stages, separating evidence-backed conclusions from inferential summaries and enforcing source citations and freshness warnings.

**Implementation:**
- `prompts.py`:
  - Summarizer: New `<RAG_TRUTHFULNESS_CONSTRAINTS>` requiring each claim to cite a source (title / url / date); claims with no single source must be indexed in `inferred_claims` and labeled `[Inferred]`; sources older than 18 months trigger entries in `freshness_warnings` when `freshness=latest`
  - Reporter: New `<TRUTHFULNESS_RULES>` splitting the report into evidence-backed conclusions and inferential summaries
- `services/summarizer.py`: Extended `_apply_chain_data()` to parse three new RAG fields from `<chain_output>`: `sources → source_citations`, `inferred_claims`, `freshness_warnings`
- `services/reporter.py`: Injects all RAG contract fields into the Reporter prompt; labels inferred claims with `[Inferred]`; appends `source_citations`, `freshness_warnings`, and `inferred_claims` index per task


## 🚀 Quick Start

### Prerequisites

```bash
python --version  # Python 3.10 or higher
node --version    # Node.js 16 or higher
npm --version     # npm 8 or higher
```

### Backend

**1. Create and activate a conda environment**

```bash
conda create -n deepresearch python=3.11 -y
conda activate deepresearch
```

**2. Install dependencies**

```bash
cd PE-DeepResearch-Agent/backend
python -m pip install "hello-agents==0.2.9" huggingface_hub \
    fastapi "tavily-python>=0.5.0" "python-dotenv==1.0.1" "requests>=2.31.0" \
    "openai>=1.12.0" "uvicorn[standard]>=0.32.0" "ddgs>=9.6.1" "loguru>=0.7.3"
```

**3. Configure environment variables**

```bash
cp .env.example .env
```

Edit `.env` and fill in at least these four fields:

```env
LLM_PROVIDER=custom
LLM_MODEL_ID=your-model-name
LLM_API_KEY=your-api-key
LLM_BASE_URL=your-api-base-url
```

> The default search engine is `duckduckgo` — no API key required. To use Tavily, set `SEARCH_API=tavily` and add `TAVILY_API_KEY` in `.env`.

**4. Start the backend**

```bash
python src/main.py
```

You should see:

```
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### Frontend

Open a new terminal window:

```bash
cd PE-DeepResearch-Agent/frontend
npm install
npm run dev
```
You should see:

```
  VITE v5.0.0  ready in 500 ms

  ➜  Local:   http://localhost:5174/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

Then open your browser and visit `http://localhost:5173`.


## ⚙️ Configuration

All options can be overridden via environment variables or the `Configuration` object:

| Field | Env Variable | Default | Description |
|-------|-------------|---------|-------------|
| `max_web_research_loops` | `MAX_WEB_RESEARCH_LOOPS` | `3` | Max ReAct search iterations per sub-task |
| `max_reflexion_rounds` | `MAX_REFLEXION_ROUNDS` | `1` | Max Reflexion review rounds; `0` = disabled |
| `sc_plan_samples` | `SC_PLAN_SAMPLES` | `3` | Planner SC sample count; `1` = disabled |
| `sc_summary_samples` | `SC_SUMMARY_SAMPLES` | `3` | Summarizer SC sample count; `1` = disabled |
| `sc_temperature` | `SC_TEMPERATURE` | `0.7` | SC sampling temperature; recommended range 0.5–1.0 |


## 🛠️ Tech Stack

- **Base Framework**: hello-agents
- **Prompt Engineering Techniques**: Prompt Chaining, ReAct, Reflexion, Self-Consistency, RAG + Truthfulness Constraints
- **Core Service Modules**:
  - `services/react_search.py`: ReAct dynamic search loop engine
  - `services/reflexion.py`: Reflexion self-evaluation review engine
  - `services/self_consistency.py`: Self-Consistency sampling and Judge service
  - `services/planner.py`: Structured task planning service
  - `services/summarizer.py`: Contract-based summarization service
  - `services/reporter.py`: RAG-aware report generation service
- **Tools & APIs**: Web Search API (Tavily / Perplexity / DuckDuckGo / SearXNG), LLM API, structured output parsing
- **Backend**: Python, FastAPI
- **Frontend**: Vue3, TypeScript


## 📁 Project Structure

```
PE-DeepResearch-Agent/
├── backend/
│   └── src/
│       ├── agent.py               # Main agent coordinator
│       ├── config.py              # Configuration (ReAct / Reflexion / SC params)
│       ├── models.py              # Data models (TodoItem with stage-contract fields)
│       ├── prompts.py             # System prompts for all stages
│       ├── main.py                # FastAPI entrypoint
│       └── services/
│           ├── planner.py         # Task planning (SC-integrated)
│           ├── react_search.py    # ReAct search loop + Reflexion targeted search
│           ├── reflexion.py       # Reflexion review engine
│           ├── self_consistency.py# SC sampling and Judge service
│           ├── summarizer.py      # Summarization (SC + RAG contracts)
│           ├── reporter.py        # Report generation (consumes RAG contract fields)
│           ├── text_processing.py # chain_output parsing utility
│           └── notes.py           # Note tool
├── frontend/                      # Vue3 + TypeScript frontend
├── LICENSE
└── README.md
```


## 📄 License

MIT License

## 🙏 Acknowledgements

Thanks to the [Datawhale community](https://github.com/datawhalechina) and the [hello-agents](https://github.com/datawhalechina/hello-agents) project for the foundational deep research agent architecture, and to [DAIR.AI](https://github.com/dair-ai) and the [Prompt-Engineering-Guide](https://github.com/dair-ai/Prompt-Engineering-Guide) for the systematic prompt engineering reference.
