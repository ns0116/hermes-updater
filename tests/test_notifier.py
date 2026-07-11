"""notifier.py のユニットテスト。

win11toast は unittest.mock.patch で差し替え、純粋 Python 部分のみ検証する。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hermes_updater import notifier
from hermes_updater.models import CheckResult


# ---- describe_step ----

def test_describe_step_known_key():
    result = notifier.describe_step("gateway_stop")
    assert result
    assert "停止" in result


def test_describe_step_unknown_key_returns_raw():
    assert notifier.describe_step("unknown_step_xyz") == "unknown_step_xyz"


# ---- notify_update_available ----

def test_notify_update_available_agent_only():
    result = CheckResult(agent_behind=3, webui_behind=0)
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_update_available(result)
    mock_notify.assert_called_once()
    title, message = mock_notify.call_args[0]
    assert "Hermes Agent" in message
    assert "3件" in message
    assert "Hermes WebUI" not in message


def test_notify_update_available_webui_only():
    result = CheckResult(agent_behind=0, webui_behind=1)
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_update_available(result)
    title, message = mock_notify.call_args[0]
    assert "Hermes WebUI" in message
    assert "Hermes Agent" not in message


def test_notify_update_available_both():
    result = CheckResult(agent_behind=2, webui_behind=5)
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_update_available(result)
    title, message = mock_notify.call_args[0]
    assert "Hermes Agent" in message
    assert "Hermes WebUI" in message


# ---- notify_check_undetermined ----

def test_notify_check_undetermined_truncates_long_error():
    long_error = "x" * 500
    result = CheckResult(undetermined=True, error=long_error)
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_check_undetermined(result)
    title, message = mock_notify.call_args[0]
    assert len(message) < 300


def test_notify_check_undetermined_no_error_uses_fallback():
    result = CheckResult(undetermined=True, error=None)
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_check_undetermined(result)
    title, message = mock_notify.call_args[0]
    assert "原因不明" in message


# ---- notify_apply_result ----

def test_notify_apply_result_success_uses_label():
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_apply_result("webui", True, None)
    title, message = mock_notify.call_args[0]
    assert "Hermes WebUI" in message
    assert "完了" in message


def test_notify_apply_result_failure_agent_uses_label():
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_apply_result("agent", False, "hermes_update_failed")
    title, message = mock_notify.call_args[0]
    assert "Hermes Agent" in message
    assert "完了" not in message


def test_notify_apply_result_known_aborted_reason_shows_human_message():
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_apply_result("webui", False, "webui_busy")
    title, message = mock_notify.call_args[0]
    assert "使用中" in message


def test_notify_apply_result_unknown_aborted_reason_shows_raw():
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_apply_result("webui", False, "totally_unknown_reason_xyz")
    title, message = mock_notify.call_args[0]
    assert "totally_unknown_reason_xyz" in message


def test_notify_apply_result_timeout_has_venv_hint():
    with patch.object(notifier, "notify") as mock_notify:
        notifier.notify_apply_result("agent", False, "hermes_update_timeout")
    title, message = mock_notify.call_args[0]
    assert "venv" in message or "手動" in message


# ---- notify: win11toast の ImportError / Exception フォールバック ----

def test_notify_suppresses_import_error():
    import sys

    # win11toast を存在しないモジュールとして差し替える
    real = sys.modules.pop("win11toast", None)
    try:
        notifier.notify("title", "msg")  # ImportError が外に伝播しないこと
    finally:
        if real is not None:
            sys.modules["win11toast"] = real


def test_notify_suppresses_toast_exception():
    mock_mod = MagicMock()
    mock_mod.notify.side_effect = RuntimeError("toast failed")
    with patch.dict("sys.modules", {"win11toast": mock_mod}):
        notifier.notify("title", "msg")  # 例外が外に伝播しないこと
