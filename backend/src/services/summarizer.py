"""Task summarization utilities."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Tuple

from hello_agents import ToolAwareSimpleAgent

from models import SummaryState, TodoItem
from config import Configuration
from utils import strip_thinking_tokens
from services.notes import build_note_guidance
from services.text_processing import extract_chain_output, strip_tool_calls


def _apply_chain_data(task: TodoItem, data: dict) -> None:
    """将 Summarizer 阶段契约数据写入 TodoItem。

    只接受格式正确的列表/字符串值，忽略空或类型错误的字段，
    确保已有数据不被意外清空。
    """
    claims = data.get("claims")
    if isinstance(claims, list) and claims:
        task.claims = [str(c) for c in claims]

    evidence = data.get("evidence")
    if isinstance(evidence, list) and evidence:
        task.evidence = [str(e) for e in evidence]

    missing_info = data.get("missing_info")
    if isinstance(missing_info, list) and missing_info:
        task.missing_info = [str(m) for m in missing_info]

    confidence = data.get("confidence")
    if isinstance(confidence, str) and confidence.strip():
        task.confidence = confidence.strip().lower()


class SummarizationService:
    """Handles synchronous and streaming task summarization."""

    def __init__(
        self,
        summarizer_factory: Callable[[], ToolAwareSimpleAgent],
        config: Configuration,
    ) -> None:
        self._agent_factory = summarizer_factory
        self._config = config

    def summarize_task(self, state: SummaryState, task: TodoItem, context: str) -> str:
        """Generate a task-specific summary using the summarizer agent.

        同时解析 <chain_output> 契约块，将 claims/evidence/missing_info/confidence
        写入 task，供 Reporter 阶段直接消费。
        """

        prompt = self._build_prompt(state, task, context)

        agent = self._agent_factory()
        try:
            response = agent.run(prompt)
        finally:
            agent.clear_history()

        summary_text = response.strip()
        if self._config.strip_thinking_tokens:
            summary_text = strip_thinking_tokens(summary_text)

        # 提取并存储 Summarizer 阶段契约，同时从可见文本中移除 chain_output 块
        chain_data, summary_text = extract_chain_output(summary_text)
        _apply_chain_data(task, chain_data)

        summary_text = strip_tool_calls(summary_text).strip()

        return summary_text or "暂无可用信息"

    def stream_task_summary(
        self, state: SummaryState, task: TodoItem, context: str
    ) -> Tuple[Iterator[str], Callable[[], str]]:
        """Stream the summary text for a task while collecting full output."""

        prompt = self._build_prompt(state, task, context)
        remove_thinking = self._config.strip_thinking_tokens
        raw_buffer = ""
        visible_output = ""
        emit_index = 0
        agent = self._agent_factory()

        def flush_visible() -> Iterator[str]:
            nonlocal emit_index, raw_buffer
            while True:
                start = raw_buffer.find("<think>", emit_index)
                if start == -1:
                    if emit_index < len(raw_buffer):
                        segment = raw_buffer[emit_index:]
                        emit_index = len(raw_buffer)
                        if segment:
                            yield segment
                    break

                if start > emit_index:
                    segment = raw_buffer[emit_index:start]
                    emit_index = start
                    if segment:
                        yield segment

                end = raw_buffer.find("</think>", start)
                if end == -1:
                    break
                emit_index = end + len("</think>")

        def generator() -> Iterator[str]:
            nonlocal raw_buffer, visible_output, emit_index
            try:
                for chunk in agent.stream_run(prompt):
                    raw_buffer += chunk
                    if remove_thinking:
                        for segment in flush_visible():
                            visible_output += segment
                            if segment:
                                yield segment
                    else:
                        visible_output += chunk
                        if chunk:
                            yield chunk
            finally:
                if remove_thinking:
                    for segment in flush_visible():
                        visible_output += segment
                        if segment:
                            yield segment
                agent.clear_history()

        def get_summary() -> str:
            if remove_thinking:
                cleaned = strip_thinking_tokens(visible_output)
            else:
                cleaned = visible_output

            # 提取并存储 Summarizer 阶段契约，从可见文本中移除 chain_output 块
            chain_data, cleaned = extract_chain_output(cleaned)
            _apply_chain_data(task, chain_data)

            return strip_tool_calls(cleaned).strip()

        return generator(), get_summary

    def _build_prompt(self, state: SummaryState, task: TodoItem, context: str) -> str:
        """Construct the summarization prompt shared by both modes.

        注入来自 Planner 阶段契约的结构化字段，使 Summarizer 知道：
        - 子问题是什么（intent / subproblem）
        - 检索意图类型（search_intent）
        - 时效性要求（freshness）
        - 满意答案的验收标准（success_criteria）
        """
        # 拼接 Planner 契约上下文
        planner_contract_lines = [
            f"【Planner 阶段契约】",
            f"- 子问题（subproblem）：{task.intent}",
        ]
        if task.search_intent:
            planner_contract_lines.append(f"- 检索意图（search_intent）：{task.search_intent}")
        if task.freshness:
            planner_contract_lines.append(f"- 时效性（freshness）：{task.freshness}")
        if task.success_criteria:
            planner_contract_lines.append(f"- 验收标准（success_criteria）：{task.success_criteria}")
        planner_contract = "\n".join(planner_contract_lines)

        return (
            f"研究主题：{state.research_topic}\n"
            f"任务名称：{task.title}\n"
            f"检索查询：{task.query}\n\n"
            f"{planner_contract}\n\n"
            f"【搜索上下文】\n{context}\n\n"
            f"{build_note_guidance(task)}\n"
            "请按照以上协作要求先同步笔记，然后严格遵循 <FORMAT> 输出：\n"
            "（1）以 `## 任务总结` 开头的 Markdown 正文；\n"
            "（2）紧随其后的 <chain_output> JSON 块（包含 claims/evidence/missing_info/confidence）。"
        )
