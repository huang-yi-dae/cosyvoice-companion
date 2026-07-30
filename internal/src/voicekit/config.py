"""Configuration loading and path resolution.

Merges non-sensitive defaults from ``config/config.yaml`` with local secrets
from ``.env`` (ACTIVE_QQ, SQLCIPHER_KEY, display names). All relative paths in
the YAML are resolved against the project root. Per-user paths are resolved via
templates so that switching between QQ users requires no code changes — only
changing ``ACTIVE_QQ`` in ``.env`` or passing ``qq=`` / ``--user``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from dotenv import load_dotenv

# internal/src/voicekit/config.py -> project root is 3 levels up
PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass
class Config:
    """Resolved project configuration with helpers for path resolution."""

    raw: Dict[str, Any]
    active_qq: Optional[str] = None
    sqlcipher_key: Optional[str] = None
    user_name: Optional[str] = None
    partner_name: Optional[str] = None
    _override_qq: Optional[str] = field(default=None, repr=False)

    # ---- generic helpers -------------------------------------------------
    def abspath(self, rel: str) -> Path:
        """Resolve a config-relative path against the project root."""
        p = Path(rel)
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def private_root(self) -> Path:
        return self.abspath(self.raw["paths"]["private_root"])

    # ---- vendored CosyVoice / tools -------------------------------------
    @property
    def cosyvoice_repo(self) -> Path:
        return self.abspath(self.raw["paths"]["cosyvoice_repo"])

    @property
    def model_dir(self) -> Path:
        return self.abspath(self.raw["paths"]["model_dir"])

    def tool(self, name: str) -> Path:
        return self.abspath(self.raw["paths"]["tools"][name])

    # ---- audio / tts / web ----------------------------------------------
    @property
    def sample_rate(self) -> int:
        return int(self.raw["audio"]["sample_rate"])

    @property
    def target_sr(self) -> int:
        return int(self.raw["audio"]["target_sr"])

    @property
    def default_prompt_text(self) -> str:
        return self.raw["tts"]["default_prompt_text"]

    @property
    def web(self) -> Dict[str, Any]:
        return self.raw["web"]

    @property
    def index_html(self) -> Path:
        return self.abspath(self.raw["web"]["index_html"])

    @property
    def chat_log_name(self) -> str:
        return self.raw["paths"].get("chat_log_name", "chat_log.json")

    # ---- active user resolution -----------------------------------------
    def resolve_qq(self, qq: Optional[str] = None) -> str:
        """Return the QQ to operate on: explicit arg > override > ACTIVE_QQ."""
        chosen = qq or self._override_qq or self.active_qq
        if not chosen:
            raise ValueError(
                "No QQ specified. Pass qq=/--user, or set ACTIVE_QQ in .env."
            )
        return str(chosen)

    def with_user(self, qq: str) -> "Config":
        """Return a shallow copy bound to a specific QQ (for --user override)."""
        return Config(
            raw=self.raw,
            active_qq=self.active_qq,
            sqlcipher_key=self.sqlcipher_key,
            user_name=self.user_name,
            partner_name=self.partner_name,
            _override_qq=str(qq),
        )

    # ---- per-user paths --------------------------------------------------
    def user_path(self, key: str, qq: Optional[str] = None, create: bool = False) -> Path:
        """Resolve a per-user subdir from paths.user_subdirs.<key>."""
        qq = self.resolve_qq(qq)
        template = self.raw["paths"]["user_subdirs"][key]
        rel = template.format(qq=qq)
        path = self.private_root / rel
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path

    def user_dir(self, qq: Optional[str] = None) -> Path:
        """Root directory for a given user (private_root/users/<qq>)."""
        qq = self.resolve_qq(qq)
        return self.private_root / "users" / qq

    def chat_log(self, qq: Optional[str] = None) -> Path:
        return self.user_path("decrypted", qq) / self.chat_log_name

    # ---- shared paths ----------------------------------------------------
    def shared_path(self, key: str, create: bool = False) -> Path:
        rel = self.raw["paths"]["shared"][key]
        path = self.private_root / rel
        if create:
            path.mkdir(parents=True, exist_ok=True)
        return path


def load_config(
    config_path: Optional[os.PathLike] = None,
    env_path: Optional[os.PathLike] = None,
) -> Config:
    """Load YAML defaults + .env secrets into a :class:`Config`."""
    config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    env_path = Path(env_path) if env_path else DEFAULT_ENV_PATH

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if env_path.exists():
        load_dotenv(env_path)

    return Config(
        raw=raw,
        active_qq=os.getenv("ACTIVE_QQ") or None,
        sqlcipher_key=os.getenv("SQLCIPHER_KEY") or None,
        user_name=os.getenv("USER_NAME") or None,
        partner_name=os.getenv("PARTNER_NAME") or None,
    )


if __name__ == "__main__":
    # Quick self-check: print resolved paths.
    cfg = load_config()
    print("PROJECT_ROOT   :", PROJECT_ROOT)
    print("private_root   :", cfg.private_root, "(exists:", cfg.private_root.exists(), ")")
    print("cosyvoice_repo :", cfg.cosyvoice_repo, "(exists:", cfg.cosyvoice_repo.exists(), ")")
    print("model_dir      :", cfg.model_dir, "(exists:", cfg.model_dir.exists(), ")")
    print("silk_decoder   :", cfg.tool("silk_decoder"))
    print("active_qq      :", cfg.active_qq)
    if cfg.active_qq:
        print("user_dir       :", cfg.user_dir())
        print("voices_wav     :", cfg.user_path("voices_wav"))
        print("chat_log       :", cfg.chat_log())
    print("shared/saved   :", cfg.shared_path("saved"))
