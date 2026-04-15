"""Utility helpers for normalizing agent generated text."""

from __future__ import annotations

import json
import re

# 匹配 Summarizer 输出的结构化契约块
_CHAIN_OUTPUT_PATTERN = re.compile(
    r"<chain_output>\s*(.*?)\s*</chain_output>",
    re.DOTALL | re.IGNORECASE,
)


def strip_tool_calls(text: str) -> str:
    """移除文本中的工具调用标记。"""

    if not text:
        return text

    pattern = re.compile(r"\[TOOL_CALL:[^\]]+\]")
    return pattern.sub("", text)


def extract_chain_output(text: str) -> tuple[dict, str]:
    """从 Summarizer 输出中提取 <chain_output> 结构化契约。

    返回 (parsed_dict, cleaned_text)：
    - parsed_dict：解析出的 claims/evidence/missing_info/confidence 字典；
      若未找到或解析失败则返回空字典。
    - cleaned_text：移除 <chain_output>…</chain_output> 块后的正文。
    """
    if not text:
        return {}, text

    match = _CHAIN_OUTPUT_PATTERN.search(text)
    if not match:
        return {}, text

    json_str = match.group(1).strip()
    cleaned = _CHAIN_OUTPUT_PATTERN.sub("", text).strip()

    try:
        data = json.loads(json_str)
        if not isinstance(data, dict):
            data = {}
    except json.JSONDecodeError:
        data = {}

    return data, cleaned

