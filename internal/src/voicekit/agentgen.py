"""Generate a roleplay agent (SystemPrompt + knowledge base) from a chat log.

Purely statistical / heuristic — no LLM or API key required. Given a user's
cleaned ``chat_log_clean.json`` it derives:

  * ``SystemPrompt.txt`` — a persona prompt from the user's own text messages
    (reply length, punctuation habits, frequent short phrases).
  * ``knowledge-base/chat_NNNN.txt`` — dialogue snippets in the ``我:`` /
    ``对方:`` line format the existing companion agents use.

Output goes to ``<private_root>/agents/<agent_name>/`` (agent_name from the
``pipeline.agent_name_template`` config, e.g. ``companion-<qq>``). The result
folder can be pointed at directly from Cherry Studio (paste SystemPrompt.txt,
add knowledge-base as the knowledge source) — see the README.
"""

from __future__ import annotations

import collections
import json
from typing import Callable, List, Optional

from .config import Config

LogFn = Callable[[str], None]

# Split into a new snippet file when the gap between messages exceeds this.
_TIME_GAP_SECONDS = 6 * 3600
_MAX_MSGS_PER_SNIPPET = 40


def _emit(on_log: Optional[LogFn], msg: str) -> None:
    if on_log:
        on_log(msg)
    else:
        print(msg)


def _load_messages(config: Config, qq: str) -> list:
    src = config.clean_log(qq)
    if not src.exists():
        src = config.find_chat_log(qq) or src
    if not src.exists():
        return []
    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("messages", [])


def build_prompt(qq: str, messages: list) -> str:
    """Derive a persona System Prompt from the user's own text messages."""
    texts = [
        str(m.get("content", "")).strip()
        for m in messages
        if m.get("type") == "text" and str(m.get("sender")) == str(qq)
    ]
    texts = [t for t in texts if t]
    total = len(texts)
    if not total:
        return (
            "你现在要扮演一个人。你不是 AI，你就是这个人。\n\n"
            "## 你是谁\n你正在和一个你在意的人聊天，聊天风格从真实聊天记录中学习。\n\n"
            "## 严格遵守的规则\n1. 回复简短、口语化。\n2. 保持一致的语气。\n"
        )

    avg_len = sum(len(t) for t in texts) / total
    short = [t for t in texts if len(t) <= 6]
    top_short = [w for w, _ in collections.Counter(short).most_common(12)]
    excl = sum(t.count("！") + t.count("!") for t in texts)
    excl_ratio = excl / total

    style_len = "极简（多为短句/短语）" if avg_len < 10 else (
        "简短" if avg_len < 20 else "中等长度")
    excl_note = "几乎不用感叹号，语气克制" if excl_ratio < 0.05 else "情绪外放，常用感叹号"
    common = "、".join(top_short) if top_short else "（无高频短语）"

    return (
        "你现在要扮演一个人。你不是 AI，你就是这个人。\n\n"
        "## 你是谁\n"
        "你正在和一个你在意的人聊天。以下风格从真实聊天记录中统计得出。\n\n"
        "## 语言风格\n"
        f"- 回复长度：{style_len}（平均约 {avg_len:.0f} 字）\n"
        f"- 标点习惯：{excl_note}\n"
        f"- 高频短语（可直接使用）：{common}\n\n"
        "## 严格遵守的规则\n"
        "1. 回复保持上面统计出的长度与语气，不要长篇大论。\n"
        "2. 使用高频短语，贴近真实说话方式。\n"
        "3. 不寒暄、不客套、不用讨好语气。\n"
        "4. 结合知识库中的真实对话片段，模仿其中「我」的说话方式。\n\n"
        f"（基于 {total} 条本人文本消息自动生成，可手动微调后保存。）"
    )


def _parse_ts(time_str: str) -> Optional[int]:
    import datetime
    try:
        return int(datetime.datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S").timestamp())
    except (ValueError, TypeError):
        return None


def _chunk_messages(messages: list, qq: str) -> List[List[str]]:
    """Group messages into dialogue snippets (lists of ``我/对方:`` lines)."""
    chunks: List[List[str]] = []
    current: List[str] = []
    prev_ts: Optional[int] = None

    for m in messages:
        content = str(m.get("content", "")).strip()
        if not content:
            continue
        ts = _parse_ts(str(m.get("time", "")))
        gap = prev_ts is not None and ts is not None and (ts - prev_ts) > _TIME_GAP_SECONDS
        if current and (gap or len(current) >= _MAX_MSGS_PER_SNIPPET):
            chunks.append(current)
            current = []
        speaker = "我" if str(m.get("sender")) == str(qq) else "对方"
        current.append(f"{speaker}: {content}")
        prev_ts = ts if ts is not None else prev_ts

    if current:
        chunks.append(current)
    # Keep only snippets that contain at least one line from each side.
    return [c for c in chunks if any(ln.startswith("我:") for ln in c)
            and any(ln.startswith("对方:") for ln in c)]


def generate_agent(
    config: Config,
    qq: Optional[str] = None,
    name: Optional[str] = None,
    *,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Generate SystemPrompt.txt + knowledge-base for a user's roleplay agent."""
    qq = config.resolve_qq(qq)
    agent_name = name or config.agent_name(qq)
    out_dir = config.agents_root / agent_name
    kb_dir = out_dir / "knowledge-base"
    result = {"ok": False, "agent": agent_name, "dir": str(out_dir), "error": None}

    messages = _load_messages(config, qq)
    if not messages:
        result["error"] = (
            f"No messages for {qq}. Run the export + clean steps first."
        )
        return result

    out_dir.mkdir(parents=True, exist_ok=True)
    kb_dir.mkdir(parents=True, exist_ok=True)

    prompt = build_prompt(qq, messages)
    prompt_path = out_dir / "SystemPrompt.txt"
    prompt_path.write_text(prompt, encoding="utf-8")

    # Clear stale snippets, then write fresh ones (capped by config).
    for old in kb_dir.glob("chat_*.txt"):
        old.unlink()
    chunks = _chunk_messages(messages, qq)
    cap = int(config.pipeline.get("knowledge_max_snippets", 300))
    chunks = chunks[:cap]
    for i, chunk in enumerate(chunks, 1):
        (kb_dir / f"chat_{i:04d}.txt").write_text("\n".join(chunk) + "\n", encoding="utf-8")

    result.update(
        ok=True,
        prompt_path=str(prompt_path),
        knowledge_dir=str(kb_dir),
        knowledge_files=len(chunks),
        prompt_chars=len(prompt),
    )
    _emit(on_log, f"[agent] {agent_name}: prompt {len(prompt)} chars, "
                  f"{len(chunks)} knowledge snippets -> {out_dir}")
    return result
