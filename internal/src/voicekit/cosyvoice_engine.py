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


from .tts_base import TTSProvider


class CosyVoiceEngine(TTSProvider):
    """Lazy wrapper around CosyVoice's AutoModel driven by :class:`Config`."""

    # Local zero-shot cloning always needs a reference sample at synth time.
    needs_reference = True

    def __init__(self, config: Config, model_dir=None):
        self.config = config
        self._model = None
        self._model_dir = Path(model_dir) if model_dir else config.model_dir

    @property
    def name(self) -> str:
        return self._model_dir.name

    @property
    def model_dir(self) -> Path:
        return self._model_dir

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

        self._model = AutoModel(model_dir=str(self._model_dir))
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
        language_tag: str = "",
    ) -> Iterator:
        """Yield cloned speech results for ``text``.

        With no ``language_tag`` this is standard zero-shot cloning (language
        follows the reference + prompt text). With a CosyVoice language tag
        (e.g. ``<|en|>``) it switches to cross-lingual inference so the output
        language matches the requested one while keeping the reference timbre.
        """
        if language_tag:
            yield from self.model.inference_cross_lingual(
                language_tag + text, str(reference_wav), stream=stream
            )
            return
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
        language_tag: str = "",
    ) -> Path:
        """Synthesize ``text`` in the reference voice and write a WAV file."""
        import soundfile as sf

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        for result in self.zero_shot(text, reference_wav, prompt_text,
                                     language_tag=language_tag):
            audio = result["tts_speech"].numpy().squeeze()
            sf.write(str(output_path), audio, self.sample_rate)
        return output_path

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
        """:class:`TTSProvider` entry point — clone ``text`` in the reference voice.

        Maps the language *code* to a CosyVoice tag via the config and delegates
        to :meth:`clone_to_file`. ``voice`` is ignored (local cloning uses the
        reference sample, not a pre-registered voice id).
        """
        if reference_wav is None:
            raise ValueError("本地克隆需要参考语音样本（reference_wav）。")
        language_tag = self.config.language_tag(language)
        return self.clone_to_file(
            text, reference_wav, output_path, prompt_text,
            language_tag=language_tag,
        )
