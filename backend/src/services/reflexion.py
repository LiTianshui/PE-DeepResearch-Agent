"""Reflexion reviewer: self-evaluation of task summaries to close research gaps.

Prompt-Engineering-Guide 把 Reflexion 描述为：在 Agent 的执行轨迹之后，
加入 self-evaluation、self-reflection 和 memory，使 Agent 能根据上一轮的
轨迹修正下一轮的行为。

本模块在每轮 Summarize 之后插入 Reviewer LLM 调用，从四个维度评估摘要质量：
  1. 证据充分性   — claims 是否有具体数据支撑
  2. 来源多样性   — 是否过度依赖单一来源
  3. 时效性验证   — 时间敏感信息是否来自近期
  4. 矛盾检测     — 是否有未处理的冲突结论

若评估未通过（quality=fail），Reviewer 给出 supplemental_queries，
触发 ReActSearchService.execute_targeted() 补充检索，然后重新总结。
反思结果以 dict 形式追加到 task.reflections，供后续轮次参考（memory）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent

from config import Configuration
from models import TodoItem
from prompts import reflexion_reviewer_system_prompt
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)

# 从 Reviewer 输出中提取 JSON 对象（宽松匹配，支持换行）
_JSON_PATTERN = re.compile(r"\{.*\}", re.DOTALL)

# Reflexion 判断为通过的 quality 值
_PASS_VALUES = {"pass", "通过", "ok", "sufficient"}


class ReflexionService:
    """在每次 Summarize 之后执行 Reflexion 质量审查。

    核心方法 review() 接受：
      - task     : 包含 Planner 契约 + Summarizer 契约（claims/evidence 等）
      - summary  : Summarizer 输出的当前摘要文本
      - context  : 传给 Summarizer 的原始搜索上下文（用于 Reviewer 溯源）

    返回 reflection dict，结构：
    {
      "quality":               "pass" | "fail",
      "evidence_sufficient":   bool,
      "source_diversity":      "high" | "medium" | "low",
      "time_sensitive_verified": bool,
      "conflicting_conclusions": [...],
      "gaps":                  [...],
      "supplemental_queries":  [...],
      "reflection":            "一段自然语言的反思"
    }
    """

    def __init__(self, llm: HelloAgentsLLM, config: Configuration) -> None:
        self._llm = llm
        self._config = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(
        self,
        task: TodoItem,
        summary: str,
        context: str,
    ) -> dict[str, Any]:
        """对任务摘要进行 Reflexion 质量审查。

        Parameters
        ----------
        task    : 当前研究任务（已包含 Planner 契约和 Summarizer 契约字段）
        summary : Summarizer 最新输出的 Markdown 摘要
        context : 传入 Summarizer 的原始搜索上下文（可截断）
        """
        prompt = self._build_prompt(task, summary, context)

        reviewer = ToolAwareSimpleAgent(
            name="Reflexion审查员",
            llm=self._llm,
            system_prompt=reflexion_reviewer_system_prompt,
            enable_tool_calling=False,
            tool_registry=None,
        )
        try:
            raw = reviewer.run(prompt)
        finally:
            reviewer.clear_history()

        if self._config.strip_thinking_tokens:
            raw = strip_thinking_tokens(raw)

        reflection = self._parse_output(raw)
        logger.info(
            "Reflexion review | task='%s' | quality=%s | gaps=%s | supp_queries=%s",
            task.title,
            reflection.get("quality"),
            reflection.get("gaps", []),
            reflection.get("supplemental_queries", []),
        )
        return reflection

    @staticmethod
    def is_pass(reflection: dict[str, Any]) -> bool:
        """判断一个 reflection dict 是否通过质量审查。"""
        return str(reflection.get("quality", "fail")).lower() in _PASS_VALUES

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, task: TodoItem, summary: str, context: str) -> str:
        """构建传给 Reviewer LLM 的 prompt。"""

        # 截断上下文，避免超出模型窗口
        ctx = context[:3000] + "\n…（已截断，仅展示前 3000 字符）" if len(context) > 3000 else context

        # ── Planner 契约 ──────────────────────────────────────────────
        planner_lines = [f"- 子问题：{task.intent}"]
        if task.search_intent:
            planner_lines.append(f"- 检索意图：{task.search_intent}")
        if task.success_criteria:
            planner_lines.append(f"- 验收标准：{task.success_criteria}")
        planner_section = "\n".join(planner_lines)

        # ── Summarizer 契约（Prompt Chaining 上游输出）─────────────────
        chain_section = ""
        if task.claims:
            claims_str = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(task.claims))
            evidence_str = (
                "\n".join(f"  {i+1}. {e}" for i, e in enumerate(task.evidence))
                if task.evidence else "  （无）"
            )
            missing_str = (
                "\n".join(f"  - {m}" for m in task.missing_info)
                if task.missing_info else "  （无）"
            )
            chain_section = (
                "\n【Summarizer 阶段契约（供审查参考）】\n"
                f"- claims:\n{claims_str}\n"
                f"- evidence:\n{evidence_str}\n"
                f"- missing_info:\n{missing_str}\n"
                f"- confidence: {task.confidence or '未知'}\n"
            )

        # ── ReAct 搜索轨迹 ────────────────────────────────────────────
        react_section = ""
        if task.react_queries:
            queries_str = "、".join(f'"{q}"' for q in task.react_queries)
            react_section = (
                f"\n【ReAct 搜索轨迹（共 {task.react_loop_count} 轮）】\n"
                f"- 使用的搜索词：{queries_str}\n"
            )

        # ── 历史反思记录（memory）────────────────────────────────────
        prev_section = ""
        if task.reflections:
            prev_lines = []
            for i, r in enumerate(task.reflections):
                prev_lines.append(
                    f"  第 {i+1} 轮：{r.get('reflection', '（无文字反思）')}"
                    f"（补充词：{r.get('supplemental_queries', [])}）"
                )
            prev_section = (
                f"\n【历史反思记录（{len(task.reflections)} 轮，请勿重复相同方向）】\n"
                + "\n".join(prev_lines) + "\n"
            )

        return (
            f"【研究主题】{task.intent or task.title}\n"
            f"【Planner 契约】\n{planner_section}"
            f"{chain_section}"
            f"{react_section}"
            f"{prev_section}\n"
            f"【任务总结（全文）】\n{summary}\n\n"
            f"【原始搜索上下文（截断）】\n{ctx}\n\n"
            "请对以上总结进行质量审查，仅输出 JSON，不含任何其他文字。"
        )

    @staticmethod
    def _parse_output(raw: str) -> dict[str, Any]:
        """从 Reviewer LLM 输出中解析 reflection dict。"""
        text = raw.strip()

        # 优先尝试整段解析
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "quality" in data:
                return data
        except json.JSONDecodeError:
            pass

        # 退而求其次：提取第一个 JSON 对象
        match = _JSON_PATTERN.search(text)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict):
                    return data
            except json.JSONDecodeError:
                pass

        logger.warning(
            "Reflexion reviewer output unparseable, defaulting to pass: %s", text[:300]
        )
        return {
            "quality": "pass",
            "reflection": "审查输出解析失败，默认通过",
            "gaps": [],
            "supplemental_queries": [],
        }
