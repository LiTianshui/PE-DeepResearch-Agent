"""Service that consolidates task results into the final report."""

from __future__ import annotations

import json

from hello_agents import ToolAwareSimpleAgent

from models import SummaryState
from config import Configuration
from utils import strip_thinking_tokens
from services.text_processing import strip_tool_calls


class ReportingService:
    """Generates the final structured report."""

    def __init__(self, report_agent: ToolAwareSimpleAgent, config: Configuration) -> None:
        self._agent = report_agent
        self._config = config

    def generate_report(self, state: SummaryState) -> str:
        """Generate a structured report based on completed tasks.

        Reporter 是 Prompt Chaining 的第三阶段，优先消费上游的结构化契约：
        - Planner 契约：intent/search_intent/freshness/success_criteria
        - Summarizer 契约：claims/evidence/missing_info/confidence
        同时保留原始 summary 文本作为补充上下文。
        """

        tasks_block = []
        for task in state.todo_items:
            summary_block = task.summary or "暂无可用信息"
            sources_block = task.sources_summary or "暂无来源"

            # ── Planner 阶段契约 ──────────────────────────────────────
            planner_lines = [f"- 子问题：{task.intent}"]
            if task.search_intent:
                planner_lines.append(f"- 检索意图：{task.search_intent}")
            if task.freshness:
                planner_lines.append(f"- 时效性：{task.freshness}")
            if task.success_criteria:
                planner_lines.append(f"- 验收标准：{task.success_criteria}")
            planner_section = "\n".join(planner_lines)

            # ── Summarizer 阶段契约 ───────────────────────────────────
            if task.claims:
                # 标记每条 claim 是否为推断性结论
                claims_lines = []
                for i, c in enumerate(task.claims):
                    prefix = "【综合推断】" if i in task.inferred_claims else ""
                    claims_lines.append(f"  {i+1}. {prefix}{c}")
                claims_text = "\n".join(claims_lines)

                evidence_text = (
                    "\n".join(f"  {i+1}. {e}" for i, e in enumerate(task.evidence))
                    if task.evidence
                    else "  （暂无）"
                )

                # ── RAG：来源绑定 ──────────────────────────────────────
                if task.source_citations:
                    citations_lines = []
                    for s in task.source_citations:
                        idx = s.get("claim_index", "?")
                        title = s.get("title") or "未知来源"
                        url = s.get("url")
                        date = s.get("date") or "日期未知"
                        link = f"[{title}]({url})" if url else title
                        citations_lines.append(f"  - claim {idx}：{link}（{date}）")
                    citations_text = "\n".join(citations_lines)
                else:
                    citations_text = "  （暂无来源记录）"

                # ── RAG：推断性结论索引 ────────────────────────────────
                inferred_text = (
                    "、".join(str(i) for i in task.inferred_claims)
                    if task.inferred_claims
                    else "无"
                )

                # ── RAG：时效性告警 ────────────────────────────────────
                freshness_text = (
                    "\n".join(f"  ⚠️ {w}" for w in task.freshness_warnings)
                    if task.freshness_warnings
                    else "  （无告警）"
                )

                missing_text = (
                    "\n".join(f"  - {m}" for m in task.missing_info)
                    if task.missing_info
                    else "  （无缺口）"
                )
                confidence_text = task.confidence or "未知"
                summarizer_section = (
                    f"- 关键断言（claims，带推断标记）：\n{claims_text}\n"
                    f"- 支撑证据（evidence）：\n{evidence_text}\n"
                    f"- 来源绑定（source_citations）：\n{citations_text}\n"
                    f"- 推断性结论索引（inferred_claims）：{inferred_text}\n"
                    f"- 时效性告警（freshness_warnings）：\n{freshness_text}\n"
                    f"- 信息缺口（missing_info）：\n{missing_text}\n"
                    f"- 置信度（confidence）：{confidence_text}"
                )
            else:
                # 无结构化契约时退回到纯文本总结
                summarizer_section = f"- 任务总结（非结构化）：\n{summary_block}"

            tasks_block.append(
                f"### 任务 {task.id}: {task.title}\n"
                f"**[Planner 契约]**\n{planner_section}\n"
                f"**[Summarizer 契约]**\n{summarizer_section}\n"
                f"- 执行状态：{task.status}\n"
                f"- 来源概览：\n{sources_block}\n"
            )

        note_references = []
        for task in state.todo_items:
            if task.note_id:
                note_references.append(
                    f"- 任务 {task.id}《{task.title}》：note_id={task.note_id}"
                )

        notes_section = "\n".join(note_references) if note_references else "- 暂无可用任务笔记"

        read_template = json.dumps({"action": "read", "note_id": "<note_id>"}, ensure_ascii=False)
        create_conclusion_template = json.dumps(
            {
                "action": "create",
                "title": f"研究报告：{state.research_topic}",
                "note_type": "conclusion",
                "tags": ["deep_research", "report"],
                "content": "请在此沉淀最终报告要点",
            },
            ensure_ascii=False,
        )

        prompt = (
            f"研究主题：{state.research_topic}\n"
            f"任务概览：\n{''.join(tasks_block)}\n"
            f"可用任务笔记：\n{notes_section}\n"
            f"请针对每条任务笔记使用格式：[TOOL_CALL:note:{read_template}] 读取内容，整合所有信息后撰写报告。\n"
            f"如需输出汇总结论，可追加调用：[TOOL_CALL:note:{create_conclusion_template}] 保存报告要点。"
        )

        response = self._agent.run(prompt)
        self._agent.clear_history()

        report_text = response.strip()
        if self._config.strip_thinking_tokens:
            report_text = strip_thinking_tokens(report_text)

        report_text = strip_tool_calls(report_text).strip()

        return report_text or "报告生成失败，请检查输入。"

