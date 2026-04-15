"""ReAct-style search loop: Reason → Act(search) → Observe → repeat.

Prompt-Engineering-Guide 对 ReAct 的定义：把 reasoning 和 acting 结合起来，
让模型一边推理、一边调用外部工具。本模块将这一思路应用于搜索：

  THINK（Observer LLM 推断信息缺口 + 改写 query）
    ↓
  ACT（SearchTool 执行新 query）
    ↓
  OBSERVE（收集结果，追加到已知信息池）
    ↓
  重复，直到 Observer 判定 DONE 或达到最大轮次上限

与原来"单次搜索后直接总结"的线性流程相比，ReAct 循环实现了：
- 动态 query 改写与同义词扩展
- 发现争议/缺口后自动追加搜索
- 多轮信息累积后再交给 Summarizer 综合
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent

from config import Configuration
from models import SummaryState, TodoItem
from prompts import react_observer_system_prompt
from services.search import dispatch_search, prepare_research_context
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)

# 从 Observer 输出中提取第一个 JSON 对象
_JSON_PATTERN = re.compile(r"\{.*?\}", re.DOTALL)


@dataclass
class ReActSearchResult:
    """ReAct 循环的聚合结果，供 agent._execute_task() 消费。"""

    # 所有轮次搜索上下文合并后的正文（传给 Summarizer）
    merged_context: str = field(default="")
    # 最近一轮的来源摘要（用于展示）
    sources_summary: str = field(default="暂无来源")
    # 所有轮次的 notice 消息
    all_notices: list[str] = field(default_factory=list)
    # 按轮次记录的搜索词（用于可观测性 + 传给 Summarizer 上下文）
    queries_used: list[str] = field(default_factory=list)
    # 实际执行的循环次数
    loop_count: int = field(default=0)
    # 最后一个后端标识
    backend: str = field(default="unknown")
    # 供流式路径 yield 的事件列表
    search_events: list[dict[str, Any]] = field(default_factory=list)


class ReActSearchService:
    """为单个研究任务执行 ReAct 搜索循环。

    循环上限由 config.max_web_research_loops 控制（默认 3）。
    每轮搜索结束后，Observer LLM 推断下一步：
      - DONE   → 停止，将已积累的上下文返回给 Summarizer
      - CONTINUE → 提供改写后的 query，进入下一轮搜索
    """

    def __init__(self, llm: HelloAgentsLLM, config: Configuration) -> None:
        self._llm = llm
        self._config = config
        self._max_loops = max(1, config.max_web_research_loops)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        task: TodoItem,
        state: SummaryState,
        step: Optional[int] = None,
    ) -> ReActSearchResult:
        """运行完整的 ReAct 搜索循环，返回聚合结果。

        Parameters
        ----------
        task  : 当前研究任务（含 Planner 阶段契约字段）
        state : 全局研究状态（用于传递 loop_count 偏移量）
        step  : 流式步骤编号（用于前端进度事件）
        """
        result = ReActSearchResult()
        current_query = task.query
        all_contexts: list[str] = []

        for loop_idx in range(self._max_loops):
            logger.info(
                "ReAct loop %d/%d | task='%s' | query='%s'",
                loop_idx + 1,
                self._max_loops,
                task.title,
                current_query,
            )

            # ── ACT：执行搜索 ─────────────────────────────────────────
            search_payload, notices, answer_text, backend = dispatch_search(
                current_query,
                self._config,
                state.research_loop_count + loop_idx,
            )
            result.all_notices.extend(notices)
            result.backend = backend
            result.queries_used.append(current_query)

            # 向流式层推送：本轮搜索已触发
            result.search_events.append({
                "type": "react_search_step",
                "task_id": task.id,
                "loop": loop_idx + 1,
                "max_loops": self._max_loops,
                "query": current_query,
                "backend": backend,
                "step": step,
            })
            for notice in notices:
                if notice:
                    result.search_events.append({
                        "type": "status",
                        "message": notice,
                        "task_id": task.id,
                        "step": step,
                    })

            # 搜索无结果 → 本轮跳过，结束循环
            if not search_payload or not search_payload.get("results"):
                logger.info("ReAct loop %d: empty results, stopping.", loop_idx + 1)
                break

            # ── OBSERVE：收集本轮结果 ─────────────────────────────────
            sources_summary, context = prepare_research_context(
                search_payload, answer_text, self._config
            )
            # 每轮上下文加轮次标签，方便 Summarizer 识别信息来源
            tagged_context = (
                f"[ReAct 第 {loop_idx + 1} 轮 | query=\"{current_query}\"]\n{context}"
            )
            all_contexts.append(tagged_context)
            result.sources_summary = sources_summary   # 保留最新一轮的来源
            result.loop_count = loop_idx + 1

            # 已到最后一轮，无需再推断
            if loop_idx >= self._max_loops - 1:
                logger.info("ReAct loop %d: reached max_loops, stopping.", loop_idx + 1)
                break

            # ── THINK：Observer 推断下一步行动 ───────────────────────
            next_action = self._reason_next_action(task, result.queries_used, all_contexts)
            action_type = next_action.get("action", "DONE").upper()
            reason = next_action.get("reason", "")
            next_query = next_action.get("query", "").strip()

            # 将 Observer 推断结果作为事件推送给前端
            result.search_events.append({
                "type": "react_thought",
                "task_id": task.id,
                "loop": loop_idx + 1,
                "action": action_type,
                "next_query": next_query,
                "reason": reason,
                "step": step,
            })

            if action_type != "CONTINUE":
                logger.info(
                    "ReAct observer → DONE at loop %d. reason=%s",
                    loop_idx + 1,
                    reason,
                )
                break

            # query 没有实质变化时也视为 DONE，避免重复搜索
            if not next_query or next_query == current_query:
                logger.info(
                    "ReAct observer returned same/empty query at loop %d, stopping.",
                    loop_idx + 1,
                )
                break

            current_query = next_query
            logger.info(
                "ReAct observer → CONTINUE | new_query='%s' | reason=%s",
                current_query,
                reason,
            )

        # 合并所有轮次的上下文
        result.merged_context = "\n\n---\n\n".join(all_contexts)
        return result

    # ------------------------------------------------------------------
    # Supplemental search (used by Reflexion)
    # ------------------------------------------------------------------

    def execute_targeted(
        self,
        task: TodoItem,
        state: SummaryState,
        queries: list[str],
        step: Optional[int] = None,
    ) -> ReActSearchResult:
        """执行 Reflexion 指定的补充搜索，不经过 Observer 推断。

        与 execute() 的区别：直接执行给定的 queries 列表，
        每条 query 只搜索一次，不触发 ReAct 推断循环。
        用于 Reflexion 发现缺口后的精准补充检索。
        """
        result = ReActSearchResult()
        all_contexts: list[str] = []

        for i, query in enumerate(queries):
            logger.info(
                "Reflexion supplemental search %d/%d | task='%s' | query='%s'",
                i + 1,
                len(queries),
                task.title,
                query,
            )

            search_payload, notices, answer_text, backend = dispatch_search(
                query,
                self._config,
                state.research_loop_count + i,
            )
            result.all_notices.extend(notices)
            result.backend = backend
            result.queries_used.append(query)

            result.search_events.append({
                "type": "reflexion_search_step",
                "task_id": task.id,
                "index": i + 1,
                "total": len(queries),
                "query": query,
                "backend": backend,
                "step": step,
            })
            for notice in notices:
                if notice:
                    result.search_events.append({
                        "type": "status",
                        "message": notice,
                        "task_id": task.id,
                        "step": step,
                    })

            if not search_payload or not search_payload.get("results"):
                logger.info("Reflexion supplemental search %d: empty results.", i + 1)
                continue

            sources_summary, context = prepare_research_context(
                search_payload, answer_text, self._config
            )
            all_contexts.append(
                f"[Reflexion 补充检索 {i + 1} | query=\"{query}\"]\n{context}"
            )
            result.sources_summary = sources_summary
            result.loop_count = i + 1

        result.merged_context = "\n\n---\n\n".join(all_contexts)
        return result

    # ------------------------------------------------------------------
    # Internal: THINK step
    # ------------------------------------------------------------------

    def _reason_next_action(
        self,
        task: TodoItem,
        queries_used: list[str],
        all_contexts: list[str],
    ) -> dict[str, Any]:
        """调用 Observer LLM，推断下一步搜索行动。"""

        # 截断合并上下文，避免超出 LLM 上下文窗口
        combined = "\n\n---\n\n".join(all_contexts)
        if len(combined) > 3000:
            combined = combined[:3000] + "\n…（已截断，仅展示前 3000 字符）"

        queries_str = "\n".join(
            f"  轮次 {i + 1}：{q}" for i, q in enumerate(queries_used)
        )

        prompt = (
            f"【任务子问题】{task.intent or task.title}\n"
            f"【检索意图】{task.search_intent or '未指定'}\n"
            f"【验收标准】{task.success_criteria or '未指定'}\n\n"
            f"【已使用的搜索词（{len(queries_used)} 轮）】\n{queries_str}\n\n"
            f"【已收集信息（截断至 3000 字符）】\n{combined}\n\n"
            "请根据以上信息判断下一步行动，仅输出 JSON，不含任何其他文字。"
        )

        observer = ToolAwareSimpleAgent(
            name="ReAct观察者",
            llm=self._llm,
            system_prompt=react_observer_system_prompt,
            enable_tool_calling=False,
            tool_registry=None,
        )
        try:
            raw = observer.run(prompt)
        finally:
            observer.clear_history()

        if self._config.strip_thinking_tokens:
            raw = strip_thinking_tokens(raw)

        return self._parse_observer_output(raw)

    @staticmethod
    def _parse_observer_output(raw: str) -> dict[str, Any]:
        """从 Observer LLM 输出中解析 action dict。"""
        text = raw.strip()

        # 优先尝试解析整个文本
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "action" in data:
                return data
        except json.JSONDecodeError:
            pass

        # 退而求其次：提取第一个 JSON 对象
        match = _JSON_PATTERN.search(text)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "action" in data:
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning("ReAct observer output unparseable, defaulting to DONE: %s", text[:300])
        return {"action": "DONE"}
