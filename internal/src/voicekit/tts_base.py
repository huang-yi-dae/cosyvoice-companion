"""TTS provider abstraction.

Decouples synthesis callers from any single engine. Both the local CosyVoice
engine and cloud providers (e.g. Aliyun Bailian / DashScope CosyVoice) implement
:class:`TTSProvider` so the web layer can route requests uniformly:

- Local engines set ``needs_reference = True`` — they clone a timbre from one or
  more reference WAVs supplied at synthesis time.
- Cloud voice-id providers set ``needs_reference = False`` — the voice is a
  pre-registered id, so no reference audio is needed at synthesis time.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class TTSProvider(ABC):
    """Common interface shared by local and cloud text-to-speech backends."""

    #: Whether this provider requires a reference WAV at synthesis time
    #: (True for local zero-shot cloning, False for cloud voice-id synthesis).
    needs_reference: bool = True

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider/engine identifier."""

    @property
    @abstractmethod
    def sample_rate(self) -> int:
        """Sample rate (Hz) of the audio this provider writes."""

    @abstractmethod
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
        """Synthesize ``text`` and write an audio file to ``output_path``.

        Args:
            text: Text to synthesize.
            output_path: Destination file path (WAV).
            reference_wav: Reference audio (path) for local cloning providers.
            voice: Voice id for cloud providers.
            prompt_text: Optional prompt text for zero-shot cloning.
            language: Language code (e.g. ``zh``/``en``); providers map it to
                their own tag/hint scheme.

        Returns:
            The written ``output_path`` as a :class:`~pathlib.Path`.
        """
