"""Windowsトースト通知 (win11toast)。

スパイクタスク(PRD 8節)の結論: win10toastは保守が不安定なため、
2026-07時点でリリース頻度の高いwin11toast(0.36.x)を採用する。
"""

from __future__ import annotations

from typing import Optional

from hermes_updater.logger import get_logger
from hermes_updater.models import CheckResult

log = get_logger("notifier")

# aborted_reasonの内部トークンをそのままトーストに出さず、利用者向けの文言にマッピングする
_ABORTED_REASON_MESSAGES = {
    "uac_denied": "管理者権限の昇格が拒否されました。再度お試しください",
    "taskkill_failed": "WebUIプロセスの停止に失敗しました",
    "webui_busy": "WebUIが使用中のため更新をスキップしました。後で再試行してください",
    "conflict": "WebUIリポジトリの競合により一部のみ更新されました",
    "apply_api_failed": "WebUIの更新APIが失敗しました",
    "hermes_update_failed": "hermes updateの実行に失敗しました",
    "version_check_failed": "更新後のバージョン確認に失敗しました",
    "webui_task_restart_failed": "WebUIタスクの再起動に失敗しました",
    "webui_health_check_failed": "WebUIの起動確認(health check)に失敗しました",
    "webui_pull_failed": "WebUIのgit pullに失敗しました(fast-forward不可の可能性)",
}


def notify(title: str, message: str) -> None:
    try:
        from win11toast import notify as _notify
    except ImportError:
        log.warning("win11toast not installed; notification suppressed: %s / %s", title, message)
        return
    try:
        _notify(title, message)
    except Exception:
        log.exception("failed to show toast notification")


def notify_update_available(result: CheckResult) -> None:
    """FR-4: 更新が1件以上ある場合のトースト通知。"""
    parts = []
    if result.agent_behind > 0:
        parts.append(f"Hermes Agent: {result.agent_behind}件")
    if result.webui_behind > 0:
        parts.append(f"Hermes WebUI: {result.webui_behind}件")
    message = " / ".join(parts) + " の更新があります"
    notify("Hermes Updater", message)


def notify_check_undetermined(result: CheckResult) -> None:
    """更新有無が判定不能(venv破損等)な場合の通知(実装計画書4節)。"""
    detail = result.error or "原因不明"
    notify("Hermes Updater - 要確認", f"更新の有無を判定できませんでした: {detail[:200]}")


def notify_apply_result(target: str, success: bool, aborted_reason: Optional[str]) -> None:
    if success:
        notify("Hermes Updater", f"{target} の更新が完了しました")
    else:
        reason = _ABORTED_REASON_MESSAGES.get(aborted_reason, aborted_reason or "不明なエラー")
        notify("Hermes Updater", f"{target} の更新に失敗しました: {reason}")
