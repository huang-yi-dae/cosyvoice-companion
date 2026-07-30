"""CosyVoice engine wrapper.

Centralizes the sys.path insertion for the vendored CosyVoice repo, the
``load_wav`` monkey-patch, model loading, and the zero-shot inference call —
all previously duplicated across many scripts and driven by hardcoded paths.
"""

from __future__ import annotations

import sys
from functools import partial
from pathlib import Path
from typing import Iterator, Optional

from .audio import load_wav_fixed
from .config import Config


class CosyVoiceEngine:
    """Lazy wrapper around CosyVoice's AutoModel driven by :class:`Config`."""

    def __init__(self, config: Config):
        self.config = config
        self._model = None

    # ---- setup -----------------------------------------------------------
    def _prepare_paths(self) -> None:
        repo = str(self.config.cosyvoice_repo)
        matcha = str(self.config.cosyvoice_repo / "third_party" / "Matcha-TTS")
        for p in (repo, matcha):
            if p not in sys.path:
                sys.path.insert(0, p)

    def _patch_load_wav(self) -> None:
        import cosyvoice.utils.file_utils as file_utils

        file_utils.load_wav = partial(
            load_wav_fixed, min_sr=self.config.target_sr
        )

    # ---- model -----------------------------------------------------------
    @property
    def model(self):
        if self._model is None:
            self.load()
        return self._model

    def load(self):
        """Import CosyVoice, patch load_wav, and load the model once."""
        self._prepare_paths()
        self._patch_load_wav()

        from cosyvoice.cli.cosyvoice import AutoModel

        self._model = AutoModel(model_dir=str(self.config.model_dir))
        return self._model

    @property
    def sample_rate(self) -> int:
        return self.model.sample_rate

    # ---- inference -------------------------------------------------------
    def zero_shot(
        self,
        text: str,
        reference_wav,
        prompt_text: Optional[str] = None,
        stream: bool = False,
    ) -> Iterator:
        """Yield zero-shot cloned speech results for ``text``."""
        prompt_text = prompt_text or self.config.default_prompt_text
        yield from self.model.inference_zero_shot(
            text, prompt_text, str(reference_wav), stream=stream
        )

    def clone_to_file(
        self,
        text: str,
        reference_wav,
        output_path,
        prompt_text: Optional[str] = None,
    ) -> Path:
        """Synthesize ``text`` in the reference voice and write a WAV file."""
        import soundfile as sf

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for result in self.zero_shot(text, reference_wav, prompt_text):
            audio = result["tts_speech"].numpy().squeeze()
            sf.write(str(output_path), audio, self.sample_rate)
        return output_path
