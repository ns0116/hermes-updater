"""設定・状態・チェック結果のデータモデル。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

CheckSource = Literal["webui_api", "fallback_cli"]


def _default_hermes_install_path() -> str:
    """`%LOCALAPPDATA%\\hermes`(実機のデフォルトインストール先)。"""
    local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    return str(Path(local_app_data) / "hermes")


def _default_hermes_webui_path() -> str:
    return str(Path(_default_hermes_install_path()) / "hermes-webui")


@dataclass
class UpdateConfig:
    """`config.json` に対応する設定値。"""

    check_interval_hours: float = 24
    check_on_startup: bool = True
    enable_notifications: bool = True
    hermes_install_path: str = field(default_factory=_default_hermes_install_path)
    hermes_webui_path: str = field(default_factory=_default_hermes_webui_path)
    webui_host: str = "127.0.0.1"
    webui_port: int = 8788
    webui_task_name: str = "HermesWebUI-Native-Start"
    webui_branch: str = "master"
    # v0.1スコープ外だが、config.jsonのみで有効化できる設計に留める(実装計画12節)
    auto_apply_updates: bool = False

    @property
    def webui_base_url(self) -> str:
        return f"http://{self.webui_host}:{self.webui_port}"

    def to_dict(self) -> dict:
        return {
            "check_interval_hours": self.check_interval_hours,
            "check_on_startup": self.check_on_startup,
            "enable_notifications": self.enable_notifications,
            "hermes_install_path": self.hermes_install_path,
            "hermes_webui_path": self.hermes_webui_path,
            "webui_host": self.webui_host,
            "webui_port": self.webui_port,
            "webui_task_name": self.webui_task_name,
            "webui_branch": self.webui_branch,
            "auto_apply_updates": self.auto_apply_updates,
        }

    @staticmethod
    def from_dict(data: dict) -> "UpdateConfig":
        import logging
        log = logging.getLogger("hermes_updater.models")
        defaults = UpdateConfig()

        raw_interval = data.get("check_interval_hours", defaults.check_interval_hours)
        if isinstance(raw_interval, (int, float)) and raw_interval > 0:
            check_interval_hours = float(raw_interval)
        else:
            log.warning("check_interval_hours=%r は無効な値です。デフォルト値 %g を使用します", raw_interval, defaults.check_interval_hours)
            check_interval_hours = defaults.check_interval_hours

        raw_port = data.get("webui_port", defaults.webui_port)
        if isinstance(raw_port, int) and 1 <= raw_port <= 65535:
            webui_port = raw_port
        else:
            log.warning("webui_port=%r は無効な値です（1〜65535の整数が必要）。デフォルト値 %d を使用します", raw_port, defaults.webui_port)
            webui_port = defaults.webui_port

        raw_branch = data.get("webui_branch", defaults.webui_branch)
        if isinstance(raw_branch, str) and raw_branch.strip():
            webui_branch = raw_branch
        else:
            log.warning("webui_branch=%r は無効な値です（空でない文字列が必要）。デフォルト値 %r を使用します", raw_branch, defaults.webui_branch)
            webui_branch = defaults.webui_branch

        return UpdateConfig(
            check_interval_hours=check_interval_hours,
            check_on_startup=data.get("check_on_startup", defaults.check_on_startup),
            enable_notifications=data.get("enable_notifications", defaults.enable_notifications),
            hermes_install_path=data.get("hermes_install_path", defaults.hermes_install_path),
            hermes_webui_path=data.get("hermes_webui_path", defaults.hermes_webui_path),
            webui_host=data.get("webui_host", defaults.webui_host),
            webui_port=webui_port,
            webui_task_name=data.get("webui_task_name", defaults.webui_task_name),
            webui_branch=webui_branch,
            auto_apply_updates=data.get("auto_apply_updates", defaults.auto_apply_updates),
        )


@dataclass
class CheckResult:
    """更新チェックの結果。"""

    agent_behind: int = 0
    webui_behind: int = 0
    source: CheckSource = "fallback_cli"
    agent_source: Optional[CheckSource] = None
    webui_source: Optional[CheckSource] = None
    error: Optional[str] = None
    # WebUI APIもフォールバックも判定できなかった(venv破損等の異常系。実装計画書4節)
    undetermined: bool = False

    @property
    def has_update(self) -> bool:
        return self.agent_behind > 0 or self.webui_behind > 0

    def to_dict(self) -> dict:
        return {
            "agent_behind": self.agent_behind,
            "webui_behind": self.webui_behind,
            "source": self.source,
            "agent_source": self.agent_source,
            "webui_source": self.webui_source,
            "error": self.error,
            "undetermined": self.undetermined,
        }

    @staticmethod
    def from_dict(data: dict) -> "CheckResult":
        return CheckResult(
            agent_behind=data.get("agent_behind", 0),
            webui_behind=data.get("webui_behind", 0),
            source=data.get("source", "fallback_cli"),
            agent_source=data.get("agent_source"),
            webui_source=data.get("webui_source"),
            error=data.get("error"),
            undetermined=data.get("undetermined", False),
        )


@dataclass
class AppState:
    """`state.json` に対応するアプリの永続状態。"""

    last_check_ts: float = 0
    last_check_result: CheckResult = field(default_factory=CheckResult)
    pending_update: bool = False
    last_update_ts: float = 0
    last_update_success: Optional[bool] = None
    last_error: Optional[str] = None
    # 同一pending状態への再通知を防ぐため、最後に通知したcheck resultのハッシュ的な要約を保持
    last_notified_agent_behind: int = 0
    last_notified_webui_behind: int = 0
    # 判定不能(venv破損等)の通知も同様に、状態が変わらない限り再通知しない
    last_notified_undetermined: bool = False

    def to_dict(self) -> dict:
        return {
            "last_check_ts": self.last_check_ts,
            "last_check_result": self.last_check_result.to_dict(),
            "pending_update": self.pending_update,
            "last_update_ts": self.last_update_ts,
            "last_update_success": self.last_update_success,
            "last_error": self.last_error,
            "last_notified_agent_behind": self.last_notified_agent_behind,
            "last_notified_webui_behind": self.last_notified_webui_behind,
            "last_notified_undetermined": self.last_notified_undetermined,
        }

    @staticmethod
    def from_dict(data: dict) -> "AppState":
        return AppState(
            last_check_ts=data.get("last_check_ts", 0),
            last_check_result=CheckResult.from_dict(data.get("last_check_result", {})),
            pending_update=data.get("pending_update", False),
            last_update_ts=data.get("last_update_ts", 0),
            last_update_success=data.get("last_update_success"),
            last_error=data.get("last_error"),
            last_notified_agent_behind=data.get("last_notified_agent_behind", 0),
            last_notified_webui_behind=data.get("last_notified_webui_behind", 0),
            last_notified_undetermined=data.get("last_notified_undetermined", False),
        )


@dataclass
class StepResult:
    """更新適用シーケンスの各ステップの結果。"""

    name: str
    success: bool
    detail: str = ""


@dataclass
class ApplyResult:
    """更新適用シーケンス全体の結果。"""

    target: Literal["webui", "agent"]
    success: bool
    aborted_reason: Optional[str] = None
    steps: list[StepResult] = field(default_factory=list)
