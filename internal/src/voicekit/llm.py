"""Roleplay chat LLM client — DashScope Generation (Qwen), lazy-imported.

Closes the companion loop: a persona ``SystemPrompt`` (see ``agentgen`` /
``private/agents/<name>/SystemPrompt.txt``) plus the running conversation is
sent to a chat model; the text reply is then voiced by the existing TTS path.

Message assembly and history trimming are pure functions kept import-free, so
they are unit-testable without the ``dashscope`` SDK or network (mirrors the
lazy-import style of :mod:`voicekit.dashscope_tts`).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Aliyun Bailian chat model used for roleplay. Overridable via ``llm.model``.
DEFAULT_MODEL = "qwen-plus"
# Default number of past user/assistant *pairs* to keep as context.
DEFAULT_MAX_TURNS = 6

_VALID_ROLES = ("user", "assistant")


def trim_history(history: Optional[List[Dict[str, str]]], max_turns: int) -> List[Dict[str, str]]:
    """Return the last ``max_turns`` user/assistant pairs from ``history``.

    Entries missing a valid role or non-empty content are dropped. ``history``
    is a list of ``{"role": "user"|"assistant", "content": str}`` dicts.
    """
    if not history or max_turns <= 0:
        return []
    cleaned = [
        {"role": m["role"], "content": m["content"]}
        for m in history
        if isinstance(m, dict)
        and m.get("role") in _VALID_ROLES
        and str(m.get("content") or "").strip()
    ]
    return cleaned[-(max_turns * 2):]


def build_messages(
    system_prompt: str,
    history: Optional[List[Dict[str, str]]],
    user_message: str,
    max_turns: int = DEFAULT_MAX_TURNS,
) -> List[Dict[str, str]]:
    """Assemble an OpenAI-style ``messages`` list: system + trimmed history + turn."""
    messages: List[Dict[str, str]] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.extend(trim_history(history, max_turns))
    messages.append({"role": "user", "content": user_message})
    return messages


class LLMClient:
    """Thin wrapper over DashScope ``Generation`` for multi-turn roleplay chat."""

    def __init__(
        self,
        *,
        api_key: Optional[str],
        model: str = DEFAULT_MODEL,
        max_turns: int = DEFAULT_MAX_TURNS,
    ):
        if not api_key:
            raise ValueError(
                "未配置 DASHSCOPE_API_KEY。请在 .env 填入阿里云百炼 API Key "
                "后重启服务，才能使用陪伴对话。"
            )
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.max_turns = max_turns

    @property
    def name(self) -> str:
        return f"dashscope:{self.model}"

    def chat(
        self,
        system_prompt: str,
        history: Optional[List[Dict[str, str]]],
        user_message: str,
    ) -> str:
        """Send one turn and return the assistant's reply text."""
        if not user_message or not user_message.strip():
            raise ValueError("消息不能为空。")

        try:
            from dashscope import Generation
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "未安装或无法导入 dashscope，请先在 .venv 中执行 "
                "pip install dashscope。原始错误: " + str(e)
            )

        messages = build_messages(system_prompt, history, user_message, self.max_turns)
        response = Generation.call(
            model=self.model,
            api_key=self.api_key,
            messages=messages,
            result_format="message",
        )
        return _extract_reply(response)


def _extract_reply(response: Any) -> str:
    """Pull the assistant text out of a DashScope Generation response."""
    status = getattr(response, "status_code", 200)
    if status != 200:
        message = getattr(response, "message", "") or ""
        raise RuntimeError(f"云端对话失败（{status}）：{message}")

    output = getattr(response, "output", None)
    if output is None:
        raise RuntimeError("云端对话返回空结果。")

    # result_format="message" -> output.choices[0].message.content
    choices = getattr(output, "choices", None) or (
        output.get("choices") if isinstance(output, dict) else None
    )
    if choices:
        msg = choices[0]["message"] if isinstance(choices[0], dict) else choices[0].message
        content = msg["content"] if isinstance(msg, dict) else msg.content
        return (content or "").strip()

    # Fallback for result_format="text".
    text = getattr(output, "text", None) or (
        output.get("text") if isinstance(output, dict) else None
    )
    if text:
        return text.strip()
    raise RuntimeError("云端对话返回空文本。")
