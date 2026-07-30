"""voicekit — shared library for QQ chat analysis and CosyVoice voice cloning.

This package centralizes configuration, audio helpers, the CosyVoice engine
wrapper, and per-user extract/clone logic so that scripts stay thin and no
privacy data or absolute paths are hardcoded.
"""

from .config import Config, load_config, PROJECT_ROOT

__all__ = ["Config", "load_config", "PROJECT_ROOT"]
