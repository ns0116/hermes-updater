"""`config.json` / `state.json` の読み書き。

実行時データは `%LOCALAPPDATA%\\HermesUpdater\\` 配下に置く
(NFR-4: 人間可読なJSONで永続化し、障害調査時に手動確認できること)。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from hermes_updater.models import AppState, UpdateConfig

APP_DIR_NAME = "HermesUpdater"


def get_app_data_dir() -> Path:
    """`%LOCALAPPDATA%\\HermesUpdater` を返す(存在しなければ作成)。"""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        # LOCALAPPDATAが定義されない特殊環境向けフォールバック
        local_app_data = str(Path.home() / "AppData" / "Local")
    app_dir = Path(local_app_data) / APP_DIR_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_config_path(base_dir: Path | None = None) -> Path:
    return (base_dir or get_app_data_dir()) / "config.json"


def get_state_path(base_dir: Path | None = None) -> Path:
    return (base_dir or get_app_data_dir()) / "state.json"


def get_logs_dir(base_dir: Path | None = None) -> Path:
    logs_dir = (base_dir or get_app_data_dir()) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def _atomic_write_json(path: Path, data: dict) -> None:
    """同一ディレクトリに一時ファイルを書いてからreplaceし、書き込み中のクラッシュで壊れたJSONを残さない。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def load_config(base_dir: Path | None = None) -> UpdateConfig:
    """`config.json`を読み込む。存在しなければデフォルトを生成して書き込む。"""
    path = get_config_path(base_dir)
    if not path.exists():
        config = UpdateConfig()
        save_config(config, base_dir)
        return config
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return UpdateConfig.from_dict(data)


def save_config(config: UpdateConfig, base_dir: Path | None = None) -> None:
    _atomic_write_json(get_config_path(base_dir), config.to_dict())


def load_state(base_dir: Path | None = None) -> AppState:
    """`state.json`を読み込む。存在しなければ初期状態を返す(書き込みはしない)。"""
    path = get_state_path(base_dir)
    if not path.exists():
        return AppState()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return AppState.from_dict(data)


def save_state(state: AppState, base_dir: Path | None = None) -> None:
    _atomic_write_json(get_state_path(base_dir), state.to_dict())
