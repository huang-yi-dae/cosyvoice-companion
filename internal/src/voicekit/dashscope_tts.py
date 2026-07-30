"""Aliyun Bailian (DashScope) CosyVoice cloud TTS provider.

Implements :class:`~voicekit.tts_base.TTSProvider` against DashScope's
``tts_v2`` speech synthesis and the ``voice-enrollment`` customization API.

Design notes (from the DashScope voice-cloning docs):

- Synthesis uses ``dashscope.audio.tts_v2.SpeechSynthesizer(model, voice)`` and
  requests WAV so the file drops straight into the existing ``soundfile`` chain.
- ``needs_reference = False``: a cloud voice is a pre-registered ``voice_id``,
  so no reference sample is needed at synthesis time (main path).
- Voice *enrollment* (advanced path) only accepts a **public, unauthenticated
  audio URL** — not local files / base64. It is exposed via
  :meth:`create_voice` but is optional (requires OSS to host the sample).
- ``target_model`` is bound to the voice: creation and synthesis must use the
  same model, otherwise synthesis fails.

The ``dashscope`` package is imported lazily so importing this module never
fails on machines without it; a missing package or API key raises a clear,
actionable error only when the provider is actually constructed/used.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .tts_base import TTSProvider

# CosyVoice cloud enrollment / synthesis customization endpoint (Beijing).
ENROLLMENT_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization"
)
# WAV_24000HZ_MONO_16BIT — matches the project's 24k output sample rate.
_SAMPLE_RATE = 24000


class DashScopeTTSProvider(TTSProvider):
    """Cloud CosyVoice provider backed by Aliyun Bailian / DashScope."""

    needs_reference = False

    def __init__(
        self,
        *,
        api_key: Optional[str],
        target_model: str = "cosyvoice-v3.5-flash",
        region: str = "cn-beijing",
        voices: Optional[List[dict]] = None,
        oss: Optional[dict] = None,
    ):
        if not api_key:
            raise ValueError(
                "未配置 DASHSCOPE_API_KEY。请在 .env 填入阿里云百炼 API Key "
                "后重启服务，才能使用云端合成。"
            )
        self.api_key = api_key
        self.target_model = target_model
        self.region = region
        self.voices = list(voices or [])
        self.oss = dict(oss or {})

    # ---- TTSProvider interface ------------------------------------------
    @property
    def name(self) -> str:
        return f"dashscope:{self.target_model}"

    @property
    def sample_rate(self) -> int:
        return _SAMPLE_RATE

    def synthesize_to_file(
        self,
        text: str,
        output_path,
        *,
        reference_wav=None,
        voice: Optional[str] = None,
        prompt_text: Optional[str] = None,
        language: Optional[str] = None,
    ) -> Path:
        """Synthesize ``text`` with a pre-registered cloud ``voice`` id -> WAV."""
        if not voice:
            raise ValueError("云端合成需要选择一个音色（voice_id）。")

        try:
            import dashscope
            from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(
                "未安装或无法导入 dashscope，请先在 .venv 中执行 "
                "pip install dashscope。原始错误: " + str(e)
            )

        dashscope.api_key = self.api_key
        synthesizer = SpeechSynthesizer(
            model=self.target_model,
            voice=voice,
            format=AudioFormat.WAV_24000HZ_MONO_16BIT,
        )
        audio = synthesizer.call(text)
        if not audio:
            raise RuntimeError(
                "云端合成返回空音频，请检查 API Key、音色是否审核通过（OK），"
                "以及 target_model 是否与音色绑定的一致。"
            )

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio)
        return output_path

    # ---- voice enrollment (advanced path) -------------------------------
    def _post(self, payload: dict) -> dict:
        try:
            import requests
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("缺少 requests 库，无法调用云端音色接口: " + str(e))

        resp = requests.post(
            ENROLLMENT_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            resp.raise_for_status()
            raise RuntimeError(f"云端接口返回非 JSON: {resp.text[:200]}")
        if resp.status_code >= 400 or data.get("code"):
            msg = data.get("message") or data.get("code") or resp.text[:200]
            raise RuntimeError(f"云端音色接口错误: {msg}")
        return data

    def list_voices(self, prefix: Optional[str] = None) -> List[dict]:
        """List enrolled voices for ``target_model`` (optionally by prefix)."""
        input_obj = {"action": "list_voice", "page_index": 0, "page_size": 100}
        if prefix:
            input_obj["prefix"] = prefix
        data = self._post({"model": "voice-enrollment", "input": input_obj})
        out = data.get("output", {}) or {}
        voices = out.get("voice_list") or out.get("voices") or []
        result: List[dict] = []
        for v in voices:
            if isinstance(v, dict):
                vid = v.get("voice_id") or v.get("voice")
                result.append({"id": vid, "label": vid, "status": v.get("status")})
            elif isinstance(v, str):
                result.append({"id": v, "label": v, "status": None})
        return result

    def create_voice(
        self,
        audio_url: str,
        prefix: str,
        language_hint: Optional[str] = None,
    ) -> str:
        """Enroll a new voice from a public audio URL; returns the ``voice_id``.

        ``audio_url`` must be publicly reachable without auth (e.g. an OSS
        object). The returned voice may take time to reach ``OK`` status before
        it can be used for synthesis.
        """
        input_obj = {
            "action": "create_voice",
            "target_model": self.target_model,
            "prefix": (prefix or "voice")[:10],
            "url": audio_url,
        }
        if language_hint:
            input_obj["language_hints"] = [language_hint]
        data = self._post({"model": "voice-enrollment", "input": input_obj})
        voice_id = (data.get("output", {}) or {}).get("voice_id")
        if not voice_id:
            raise RuntimeError(f"创建音色未返回 voice_id: {data}")
        return voice_id

    def delete_voice(self, voice_id: str) -> bool:
        """Delete an enrolled voice by id."""
        self._post({
            "model": "voice-enrollment",
            "input": {"action": "delete_voice", "voice_id": voice_id},
        })
        return True
