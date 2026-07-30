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
    dashscope_api_key: Optional[str] = None
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

    @property
    def models_root(self) -> Path:
        """Directory containing all downloaded models (for the selector)."""
        rel = self.raw["paths"].get("models_root")
        return self.abspath(rel) if rel else self.model_dir.parent

    def list_models(self) -> list[dict]:
        """List available (downloaded) models under ``models_root``.

        A directory is considered a usable model if it contains model assets
        (``*.pt``/``*.onnx``/``*.yaml``). The default model is flagged.
        """
        root = self.models_root
        default_name = self.model_dir.name
        models: list[dict] = []
        if root.exists():
            for d in sorted(root.iterdir()):
                if not d.is_dir():
                    continue
                has_assets = any(
                    d.glob(pat) for pat in ("*.pt", "*.onnx", "*.yaml", "*.json")
                )
                models.append({
                    "name": d.name,
                    "path": str(d),
                    "available": bool(has_assets),
                    "is_default": d.name == default_name,
                    "clone_ready": self.model_clone_ready(d.name),
                })
        return models

    def model_path(self, name: Optional[str] = None) -> Path:
        """Resolve a model directory by name (defaults to the configured one)."""
        if not name or name == self.model_dir.name:
            return self.model_dir
        return self.models_root / name

    # ---- model catalog / download --------------------------------------
    @property
    def models(self) -> Dict[str, Any]:
        return self.raw.get("models", {})

    def model_download_dir(self, name: str) -> Path:
        """Local directory a catalog model is downloaded into."""
        return self.models_root / name

    def model_is_downloaded(self, path: Path) -> bool:
        """A model is usable if its dir holds recognizable model assets."""
        if not path.exists() or not path.is_dir():
            return False
        return any(
            next(path.glob(pat), None) is not None
            for pat in ("*.pt", "*.onnx", "cosyvoice*.yaml")
        )

    def model_catalog(self) -> list[dict]:
        """Curated catalog merged with on-disk download status.

        Entry: {name, repo_id, size_mb, kind, description, downloaded,
        is_default, est_minutes}.
        """
        est_speed = float(self.models.get("est_speed_mbps", 5) or 5)
        default_name = self.model_dir.name
        out: list[dict] = []
        for item in self.models.get("catalog", []) or []:
            name = item.get("name")
            if not name:
                continue
            path = self.model_download_dir(name)
            size_mb = float(item.get("size_mb", 0) or 0)
            est_minutes = round(size_mb / est_speed / 60, 1) if est_speed > 0 else 0
            out.append({
                "name": name,
                "repo_id": item.get("repo_id", ""),
                "size_mb": size_mb,
                "kind": item.get("kind", ""),
                "description": item.get("description", ""),
                "path": str(path),
                "downloaded": self.model_is_downloaded(path),
                "is_default": name == default_name,
                "clone_ready": bool(item.get("clone_ready", True)),
                "est_minutes": est_minutes,
            })
        return out

    def model_repo_id(self, name: str) -> Optional[str]:
        """ModelScope repo id for a catalog model name, if known."""
        for item in self.models.get("catalog", []) or []:
            if item.get("name") == name:
                return item.get("repo_id")
        return None

    def model_clone_ready(self, name: str) -> bool:
        """Whether a model suits the studio's zero-shot cloning flow.

        Unknown models default to True (assume usable); catalog entries can opt
        out via ``clone_ready: false`` (e.g. SFT/Instruct need other interfaces).
        """
        for item in self.models.get("catalog", []) or []:
            if item.get("name") == name:
                return bool(item.get("clone_ready", True))
        return True

    def tool(self, name: str) -> Path:
        return self.abspath(self.raw["paths"]["tools"][name])

    @property
    def ntqq_key_script(self) -> Path:
        """PowerShell script that extracts the NTQQ SQLCipher key."""
        return self.abspath(self.raw["paths"]["ntqq_key_script"])

    @property
    def env_path(self) -> Path:
        """Location of the local ``.env`` file (for writing the extracted key)."""
        return DEFAULT_ENV_PATH

    # ---- automation pipeline --------------------------------------------
    @property
    def pipeline(self) -> Dict[str, Any]:
        return self.raw.get("pipeline", {})

    def cipher_pragmas(self) -> Dict[str, Any]:
        """SQLCipher PRAGMA values for the NTQQ database."""
        p = self.pipeline
        return {
            "cipher_page_size": p.get("cipher_page_size", 4096),
            "kdf_iter": p.get("kdf_iter", 4000),
            "cipher_hmac_algorithm": p.get("cipher_hmac_algorithm", "HMAC_SHA1"),
            "cipher": p.get("cipher", "aes-256-cbc"),
        }

    def encrypted_db(self, qq: Optional[str] = None) -> Path:
        """Path to the raw (encrypted) NTQQ DB inside the user's decrypted dir."""
        name = self.raw["paths"].get("encrypted_db_name", "nt_msg.clean.db")
        return self.user_path("decrypted", qq) / name

    def decrypted_db(self, qq: Optional[str] = None) -> Path:
        """Path to the plaintext DB produced by the decrypt step."""
        name = self.raw["paths"].get("decrypted_db_name", "nt_msg_decrypted.db")
        return self.user_path("decrypted", qq) / name

    def clean_log(self, qq: Optional[str] = None) -> Path:
        """Path to the cleaned chat log inside the user's decrypted dir."""
        name = self.raw["paths"].get("clean_log_name", "chat_log_clean.json")
        return self.user_path("decrypted", qq) / name

    def agent_name(self, qq: Optional[str] = None) -> str:
        """Roleplay agent directory name for a user (from agent_name_template)."""
        qq = self.resolve_qq(qq)
        tpl = self.pipeline.get("agent_name_template", "companion-{qq}")
        return tpl.format(qq=qq)

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

    # ---- tts providers ---------------------------------------------------
    def tts_provider_default(self) -> str:
        """Default synthesis provider name ("local" or "dashscope")."""
        return self.raw.get("tts", {}).get("provider", "local") or "local"

    def tts_providers(self) -> Dict[str, Any]:
        """Configured provider map from ``tts.providers`` (may be empty)."""
        return self.raw.get("tts", {}).get("providers", {}) or {}

    def dashscope_cfg(self) -> Dict[str, Any]:
        """Config block for the DashScope cloud provider (may be empty)."""
        return self.tts_providers().get("dashscope", {}) or {}

    def dashscope_voices(self) -> list[dict]:
        """Pre-registered cloud voices: [{id, label}, ...]."""
        voices = self.dashscope_cfg().get("voices") or []
        out: list[dict] = []
        for v in voices:
            if isinstance(v, dict) and v.get("id"):
                out.append({"id": v["id"], "label": v.get("label") or v["id"]})
        return out

    def languages(self) -> list[dict]:
        """Supported synthesis languages: [{code, tag, label}, ...].

        Falls back to a single "auto" entry if none configured.
        """
        langs = self.raw.get("tts", {}).get("languages")
        if not langs:
            return [{"code": "auto", "tag": "", "label": "自动（跟随样本）"}]
        return [dict(lang) for lang in langs]

    def language_tag(self, code: Optional[str]) -> str:
        """CosyVoice language tag for a language code ("" for auto/unknown)."""
        if not code or code == "auto":
            return ""
        for lang in self.languages():
            if lang.get("code") == code:
                return lang.get("tag", "") or ""
        return ""

    @property
    def web(self) -> Dict[str, Any]:
        return self.raw["web"]

    @property
    def index_html(self) -> Path:
        return self.abspath(self.raw["web"]["index_html"])

    @property
    def manage_html(self) -> Path:
        return self.abspath(self.raw["web"]["manage_html"])

    @property
    def pipeline_html(self) -> Path:
        return self.abspath(self.raw["web"]["pipeline_html"])

    @property
    def models_html(self) -> Path:
        return self.abspath(self.raw["web"]["models_html"])

    @property
    def static_dir(self) -> Path:
        return self.abspath(self.raw["web"]["static_dir"])

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
            dashscope_api_key=self.dashscope_api_key,
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

    def list_users(self) -> list[dict]:
        """Discover QQ users under private_root/users with basic metadata."""
        users_root = self.private_root / "users"
        out: list[dict] = []
        if not users_root.exists():
            return out
        for d in sorted(users_root.iterdir()):
            if not d.is_dir():
                continue
            qq = d.name
            wav_dir = self.user_path("voices_wav", qq)
            cloned_dir = self.user_path("voices_cloned", qq)
            n_wav = len(list(wav_dir.glob("*.wav"))) if wav_dir.exists() else 0
            n_cloned = len(list(cloned_dir.glob("*.wav"))) if cloned_dir.exists() else 0
            out.append({
                "qq": qq,
                "voice_count": n_wav,
                "cloned_count": n_cloned,
                "has_chat_log": self.find_chat_log(qq) is not None,
                "is_active": qq == (self._override_qq or self.active_qq),
            })
        return out

    def find_chat_log(self, qq: Optional[str] = None) -> Optional[Path]:
        """Locate a user's chat_log.json across known layouts."""
        qq = self.resolve_qq(qq)
        candidates = [
            self.user_path("decrypted", qq) / self.chat_log_name,
            self.user_dir(qq) / "reports" / "analysis_detail" / self.chat_log_name,
        ]
        for c in candidates:
            if c.exists():
                return c
        return None

    # ---- agents / roleplay ----------------------------------------------
    @property
    def agents_root(self) -> Path:
        rel = self.raw["paths"].get("agents_subdir", "agents")
        return self.private_root / rel

    def list_agents(self) -> list[str]:
        root = self.agents_root
        if not root.exists():
            return []
        return sorted(d.name for d in root.iterdir() if d.is_dir())

    # ---- persisted web state --------------------------------------------
    @property
    def state_file(self) -> Path:
        rel = self.raw["paths"].get("state_file", "web_state.json")
        return self.private_root / rel

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
        dashscope_api_key=os.getenv("DASHSCOPE_API_KEY") or None,
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
