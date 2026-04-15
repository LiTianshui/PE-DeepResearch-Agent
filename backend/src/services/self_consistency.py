"""Self-Consistency: sample multiple reasoning paths and select the most consistent one.

Prompt-Engineering-Guide 的定义：通过对同一问题采样多条推理路径，
选择最一致的答案来提升输出质量，减少单次生成的随机偏差。

本模块在两个关键节点提供局部 SC 增强（cost 可控）：

  1. Planner 节点：采样 N 组子任务方案 → Judge 评选覆盖最全面的那组
     - 减少任务拆解过偏（如偏重某一维度、任务重叠过多）的概率

  2. Summarizer 节点：对同一搜索结果生成 N 份总结 → Judge 评选证据覆盖最好的那份
     - 减少单次总结失真（幻觉/遗漏重要 claim）的概率

采样阶段使用 sc_temperature（较高温度）以保证候选集多样性；
评审阶段（Judge）使用主 LLM（temperature=0）以保证判断确定性。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from hello_agents import HelloAgentsLLM, ToolAwareSimpleAgent

from config import Configuration
from models import TodoItem
from prompts import sc_plan_judge_system_prompt, sc_summary_judge_system_prompt
from utils import strip_thinking_tokens

logger = logging.getLogger(__name__)

_JSON_PATTERN = re.compile(r"\{.*?\}", re.DOTALL)


class SelfConsistencyService:
    """局部 Self-Consistency 增强：Planner + Summarizer 两个关键节点。

    Parameters
    ----------
    sampling_llm : 高温度 LLM（sc_temperature），用于生成多样候选
    judge_llm    : 低温度 LLM（temperature=0），用于确定性判断
    config       : 全局配置（sc_plan_samples / sc_summary_samples）
    """

    def __init__(
        self,
        sampling_llm: HelloAgentsLLM,
        judge_llm: HelloAgentsLLM,
        config: Configuration,
    ) -> None:
        self._sampling_llm = sampling_llm
        self._judge_llm = judge_llm
        self._config = config

    # ------------------------------------------------------------------
    # Planner SC
    # ------------------------------------------------------------------

    def sample_and_select_plan(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """采样 sc_plan_samples 份规划方案，用 Judge 选出最优的原始 response。

        Parameters
        ----------
        system_prompt : Planner agent 的系统提示（与主流程保持一致）
        user_prompt   : 包含研究主题的用户提示

        Returns
        -------
        str : 最优候选的原始 LLM 输出（JSON 格式的任务列表），
              可直接传入 PlanningService._extract_tasks() 解析。
        """
        n = self._config.sc_plan_samples
        candidates = self._run_samples(system_prompt, user_prompt, n)

        if len(candidates) == 1:
            return candidates[0]

        best_idx = self._judge_plans(candidates, user_prompt)
        logger.info("SC Plan Judge selected candidate %d / %d", best_idx + 1, len(candidates))
        return candidates[best_idx]

    # ------------------------------------------------------------------
    # Summarizer SC
    # ------------------------------------------------------------------

    def sample_and_select_summary(
        self,
        system_prompt: str,
        user_prompt: str,
        task: TodoItem,
    ) -> str:
        """采样 sc_summary_samples 份总结，用 Judge 选出证据覆盖最好的原始 response。

        Parameters
        ----------
        system_prompt : Summarizer agent 的系统提示
        user_prompt   : 包含搜索上下文和 Planner 契约的用户提示
        task          : 当前任务（供 Judge 了解目标子问题）

        Returns
        -------
        str : 最优候选的原始 LLM 输出（含 Markdown + <chain_output>），
              可直接传入后续的 extract_chain_output() 解析。
        """
        n = self._config.sc_summary_samples
        candidates = self._run_samples(system_prompt, user_prompt, n)

        if len(candidates) == 1:
            return candidates[0]

        best_idx = self._judge_summaries(candidates, task)
        logger.info("SC Summary Judge selected candidate %d / %d", best_idx + 1, len(candidates))
        return candidates[best_idx]

    # ------------------------------------------------------------------
    # Internal: sampling
    # ------------------------------------------------------------------

    def _run_samples(
        self,
        system_prompt: str,
        user_prompt: str,
        n: int,
    ) -> list[str]:
        """用采样 LLM 生成 n 份候选输出。

        每次创建独立 agent，run 后立即清空历史，保证彼此独立。
        tool calling 关闭，避免 NoteTool 等副作用干扰采样。
        """
        candidates: list[str] = []
        for i in range(n):
            agent = ToolAwareSimpleAgent(
                name=f"SC采样者_{i + 1}",
                llm=self._sampling_llm,
                system_prompt=system_prompt,
                enable_tool_calling=False,
                tool_registry=None,
            )
            try:
                raw = agent.run(user_prompt)
            finally:
                agent.clear_history()

            if self._config.strip_thinking_tokens:
                raw = strip_thinking_tokens(raw)

            candidates.append(raw.strip())
            logger.debug("SC sample %d/%d collected (len=%d)", i + 1, n, len(raw))

        return candidates

    # ------------------------------------------------------------------
    # Internal: judge calls
    # ------------------------------------------------------------------

    def _judge_plans(self, candidates: list[str], user_prompt: str) -> int:
        """调用 Plan Judge LLM，返回最优候选的 0-based 索引。"""

        # 构建评审 prompt：列出所有候选，截断过长的
        sections = []
        for i, c in enumerate(candidates):
            snippet = c[:1200] + "\n…（已截断）" if len(c) > 1200 else c
            sections.append(f"【方案 {i + 1}】\n{snippet}")

        judge_prompt = (
            f"研究主题：{self._extract_topic_hint(user_prompt)}\n\n"
            + "\n\n".join(sections)
            + f"\n\n共 {len(candidates)} 个方案，请选出最优的一个。"
            f"仅输出 JSON：{{\"best_index\": <0-based整数>, \"reason\": \"...\"}}"
        )

        return self._call_judge(sc_plan_judge_system_prompt, judge_prompt, len(candidates))

    def _judge_summaries(self, candidates: list[str], task: TodoItem) -> int:
        """调用 Summary Judge LLM，返回最优候选的 0-based 索引。"""

        sections = []
        for i, c in enumerate(candidates):
            snippet = c[:1500] + "\n…（已截断）" if len(c) > 1500 else c
            sections.append(f"【总结 {i + 1}】\n{snippet}")

        judge_prompt = (
            f"任务子问题：{task.intent}\n"
            f"验收标准：{task.success_criteria or '未指定'}\n\n"
            + "\n\n".join(sections)
            + f"\n\n共 {len(candidates)} 份总结，请选出最优的一份。"
            f"仅输出 JSON：{{\"best_index\": <0-based整数>, \"reason\": \"...\"}}"
        )

        return self._call_judge(sc_summary_judge_system_prompt, judge_prompt, len(candidates))

    def _call_judge(
        self,
        system_prompt: str,
        user_prompt: str,
        n_candidates: int,
    ) -> int:
        """运行 Judge LLM，解析 best_index，返回 0-based 整数。

        解析失败时默认返回 0（使用第一个候选）。
        """
        agent = ToolAwareSimpleAgent(
            name="SC评审员",
            llm=self._judge_llm,
            system_prompt=system_prompt,
            enable_tool_calling=False,
            tool_registry=None,
        )
        try:
            raw = agent.run(user_prompt)
        finally:
            agent.clear_history()

        if self._config.strip_thinking_tokens:
            raw = strip_thinking_tokens(raw)

        return self._parse_judge_output(raw.strip(), n_candidates)

    # ------------------------------------------------------------------
    # Internal: parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_judge_output(raw: str, n_candidates: int) -> int:
        """从 Judge 输出中提取 best_index，失败时返回 0。"""
        def _clamp(idx: Any) -> int:
            try:
                v = int(idx)
                return max(0, min(v, n_candidates - 1))
            except (TypeError, ValueError):
                return 0

        # 尝试解析整段 JSON
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "best_index" in data:
                return _clamp(data["best_index"])
        except json.JSONDecodeError:
            pass

        # 提取第一个 JSON 对象
        match = _JSON_PATTERN.search(raw)
        if match:
            try:
                data = json.loads(match.group())
                if isinstance(data, dict) and "best_index" in data:
                    return _clamp(data["best_index"])
            except json.JSONDecodeError:
                pass

        logger.warning("SC judge output unparseable, defaulting to index 0: %s", raw[:200])
        return 0

    @staticmethod
    def _extract_topic_hint(user_prompt: str) -> str:
        """从 user_prompt 中提取研究主题行（用于 judge prompt 上下文）。"""
        for line in user_prompt.splitlines():
            line = line.strip()
            if line.startswith("研究主题") or line.startswith("Research"):
                return line
        return user_prompt[:80]
