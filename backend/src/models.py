"""State models used by the deep research workflow."""

import operator
from dataclasses import dataclass, field
from typing import List, Optional

from typing_extensions import Annotated


@dataclass(kw_only=True)
class TodoItem:
    """单个待办任务项。

    Prompt Chaining 阶段契约字段：
    - Planner 契约：search_intent / freshness / success_criteria
    - Summarizer 契约：claims / evidence / missing_info / confidence
    这些字段由对应阶段的 Agent 严格输出，并作为下一阶段的输入。
    """

    id: int
    title: str
    intent: str
    query: str
    status: str = field(default="pending")
    summary: Optional[str] = field(default=None)
    sources_summary: Optional[str] = field(default=None)
    notices: list[str] = field(default_factory=list)
    note_id: Optional[str] = field(default=None)
    note_path: Optional[str] = field(default=None)
    stream_token: Optional[str] = field(default=None)

    # ── Planner 阶段契约 ──────────────────────────────────────────────
    # 检索意图（如"寻找最新数据"、"梳理技术原理"）
    search_intent: Optional[str] = field(default=None)
    # 时效性要求：latest | historical | both
    freshness: str = field(default="both")
    # 满意答案的评判标准（1-2 句）
    success_criteria: Optional[str] = field(default=None)

    # ── Summarizer 阶段契约 ───────────────────────────────────────────
    # 关键 claim 列表（每条为独立的事实性断言）
    claims: list[str] = field(default_factory=list)
    # 每条 claim 对应的支撑证据/来源摘要
    evidence: list[str] = field(default_factory=list)
    # 本轮搜索未能覆盖的信息缺口
    missing_info: list[str] = field(default_factory=list)
    # 整体置信度：high | medium | low
    confidence: Optional[str] = field(default=None)

    # ── ReAct 循环可观测字段 ──────────────────────────────────────────
    # 本任务实际执行的所有搜索词（按轮次顺序）
    react_queries: list[str] = field(default_factory=list)
    # 实际完成的 ReAct 循环次数
    react_loop_count: int = field(default=0)

    # ── Reflexion 记忆字段 ────────────────────────────────────────────
    # 每轮 Reflexion 审查的完整输出（quality/gaps/reflection 等），
    # 按轮次追加；下一轮审查时可作为历史参考，避免重复相同方向。
    reflections: list[dict] = field(default_factory=list)


@dataclass(kw_only=True)
class SummaryState:
    research_topic: str = field(default=None)  # Report topic
    search_query: str = field(default=None)  # Deprecated placeholder
    web_research_results: Annotated[list, operator.add] = field(default_factory=list)
    sources_gathered: Annotated[list, operator.add] = field(default_factory=list)
    research_loop_count: int = field(default=0)  # Research loop count
    running_summary: str = field(default=None)  # Legacy summary field
    todo_items: Annotated[list, operator.add] = field(default_factory=list)
    structured_report: Optional[str] = field(default=None)
    report_note_id: Optional[str] = field(default=None)
    report_note_path: Optional[str] = field(default=None)


@dataclass(kw_only=True)
class SummaryStateInput:
    research_topic: str = field(default=None)  # Report topic


@dataclass(kw_only=True)
class SummaryStateOutput:
    running_summary: str = field(default=None)  # Backward-compatible文本
    report_markdown: Optional[str] = field(default=None)
    todo_items: List[TodoItem] = field(default_factory=list)

