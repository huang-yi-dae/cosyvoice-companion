"""Model catalog + on-demand download for the /models manager.

Downloads CosyVoice models from ModelScope into ``paths.models_root/<name>`` so
the web model selector can show download status and fetch a model on demand.
The heavy download runs in a background thread (see the web layer); this module
stays synchronous and streams progress through an ``on_log`` callback.
"""

from __future__ import annotations

from typing import Callable, Optional

from .config import Config

LogFn = Callable[[str], None]

# Models that need extra assets beyond the generic *.pt/*.onnx/*.yaml check.
# CosyVoice2 loads a CosyVoice-BlankEN subdir + a v2 speech tokenizer; a partial
# download otherwise only fails later at synthesis time with a cryptic error.
_REQUIRED_EXTRAS: dict[str, list[str]] = {
    "CosyVoice2-0.5B": ["CosyVoice-BlankEN", "speech_tokenizer_v2.onnx"],
}


def _missing_required_extras(config: Config, name: str, target) -> list[str]:
    """Return required asset names missing from a downloaded model dir."""
    missing: list[str] = []
    for rel in _REQUIRED_EXTRAS.get(name, []):
        if not (target / rel).exists():
            missing.append(rel)
    return missing


def list_catalog(config: Config) -> list[dict]:
    """Curated model catalog merged with on-disk download status."""
    return config.model_catalog()


def download_model(
    config: Config,
    name: str,
    *,
    on_log: Optional[LogFn] = None,
) -> dict:
    """Download a catalog model from ModelScope into models_root/<name>.

    Returns ``{ok, name, repo_id, path, error}``. Safe to call again if the
    model is already present (returns early as a no-op success).
    """
    def log(msg: str) -> None:
        if on_log:
            on_log(msg)

    repo_id = config.model_repo_id(name)
    if not repo_id:
        return {"ok": False, "name": name, "repo_id": None, "path": None,
                "error": f"未知模型: {name}（不在 config.yaml 的 models.catalog 中）"}

    target = config.model_download_dir(name)
    if config.model_is_downloaded(target):
        log(f"[models] {name} 已存在，跳过下载。")
        return {"ok": True, "name": name, "repo_id": repo_id,
                "path": str(target), "error": None, "skipped": True}

    try:
        from modelscope import snapshot_download
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "name": name, "repo_id": repo_id, "path": str(target),
                "error": f"modelscope 不可用: {e}. 请先安装: pip install modelscope"}

    target.parent.mkdir(parents=True, exist_ok=True)
    log(f"[models] 开始从 ModelScope 下载 {repo_id} -> {target}")
    try:
        snapshot_download(repo_id, local_dir=str(target))
    except Exception as e:  # noqa: BLE001 — surface any download/network error
        return {"ok": False, "name": name, "repo_id": repo_id, "path": str(target),
                "error": f"下载失败: {type(e).__name__}: {e}"}

    if not config.model_is_downloaded(target):
        return {"ok": False, "name": name, "repo_id": repo_id, "path": str(target),
                "error": "下载完成但未检测到模型文件，请检查磁盘空间或重试。"}

    missing = _missing_required_extras(config, name, target)
    if missing:
        return {"ok": False, "name": name, "repo_id": repo_id, "path": str(target),
                "error": f"下载不完整，缺少必需文件: {', '.join(missing)}。"
                         f"请重新下载 {name}（该模型需要这些文件才能加载）。"}

    log(f"[models] {name} 下载完成。")
    return {"ok": True, "name": name, "repo_id": repo_id,
            "path": str(target), "error": None}
