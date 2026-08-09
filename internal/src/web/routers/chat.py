"""Companion chat + per-user messages/prompt routes.

Extracted from app.py (architecture review §4). Groups the roleplay chat
endpoint with the per-user message-history and persona-prompt endpoints, since
they share the same domain (a user's companion persona + conversation).

Pure-logic helpers (voice_messages / default_prompt / existing_prompt /
regenerate_prompt / load_state / save_state) and the LLM client accessor stay
in app.py and are injected as callables — this router owns HTTP wiring only and
never imports app.py, avoiding an import cycle.
"""

from __future__ import annotations

from typing import Callable, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


class PromptBody(BaseModel):
    content: str


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    qq: Optional[str] = None
    history: List[ChatMessage] = []


def build_router(
    cfg,
    *,
    voice_messages: Callable[[str], List[dict]],
    existing_prompt: Callable[[str], Optional[dict]],
    default_prompt: Callable[[str], str],
    regenerate_prompt: Callable[[str], str],
    load_state: Callable[[], dict],
    save_state: Callable[[dict], None],
    get_llm_client: Callable,
) -> APIRouter:
    """Build the chat/messages/prompt router bound to cfg + injected helpers."""
    router = APIRouter(tags=["chat"])

    @router.get("/api/users/{qq}/messages")
    async def api_messages(qq: str):
        msgs = voice_messages(qq)
        return {"qq": qq, "count": len(msgs), "messages": msgs}

    @router.get("/api/users/{qq}/prompt")
    async def api_get_prompt(qq: str):
        found = existing_prompt(qq)
        if found:
            return {"qq": qq, **found}
        return {"qq": qq, "content": default_prompt(qq), "source": "default"}

    @router.post("/api/users/{qq}/prompt")
    async def api_save_prompt(qq: str, body: PromptBody):
        state = load_state()
        state.setdefault("prompts", {})[str(qq)] = body.content
        save_state(state)
        return {"success": True, "source": "override"}

    @router.post("/api/users/{qq}/prompt/regenerate")
    async def api_regen_prompt(qq: str):
        content = regenerate_prompt(qq)
        state = load_state()
        state.setdefault("prompts", {})[str(qq)] = content
        save_state(state)
        return {"success": True, "content": content, "source": "regenerated"}

    @router.post("/api/chat")
    def companion_chat(request: ChatRequest):
        """Roleplay one turn: persona SystemPrompt + history + message -> reply text.

        The reply is returned as text; the companion page then sends it to
        ``/api/generate`` (or ``/api/generate/stream``) to voice it in the cloned
        voice. Conversation history is supplied by the client (stateless backend).
        """
        if not request.message.strip():
            raise HTTPException(status_code=400, detail="消息不能为空")

        found = existing_prompt(request.qq) if request.qq else existing_prompt(cfg.active_qq or "")
        system_prompt = found["content"] if found else default_prompt(request.qq or "")
        source = found["source"] if found else "default"

        history = [{"role": m.role, "content": m.content} for m in request.history]
        try:
            client = get_llm_client()
            reply = client.chat(system_prompt, history, request.message)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:  # noqa: BLE001 — surface chat errors to the client
            raise HTTPException(status_code=500, detail=str(e))

        return {"reply": reply, "prompt_source": source, "model": client.name}

    return router
