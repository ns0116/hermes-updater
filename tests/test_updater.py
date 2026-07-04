from hermes_updater import shell, updater
from hermes_updater.models import UpdateConfig
from hermes_updater.shell import ShellResult


def _cfg(**overrides) -> UpdateConfig:
    cfg = UpdateConfig()
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


# ---- _check_agent_fallback: 実機で確認した `hermes update --check` の出力形式 ----

def test_agent_fallback_up_to_date(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "hermes.exe")
    monkeypatch.setattr(
        shell, "run",
        lambda args, timeout=None: ShellResult(0, stdout="→ Fetching from upstream...\n✓ Already up to date.\n"),
    )
    behind, err = updater._check_agent_fallback()
    assert behind == 0
    assert err is None


def test_agent_fallback_behind_n(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "hermes.exe")
    monkeypatch.setattr(
        shell, "run",
        lambda args, timeout=None: ShellResult(
            0, stdout="♕ Update available: 3 commits behind upstream/main.\n  Run 'hermes update' to install.\n"
        ),
    )
    behind, err = updater._check_agent_fallback()
    assert behind == 3
    assert err is None


def test_agent_fallback_shallow_unknown_count(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "hermes.exe")
    monkeypatch.setattr(
        shell, "run",
        lambda args, timeout=None: ShellResult(0, stdout="♕ Update available (behind upstream/main).\n"),
    )
    behind, err = updater._check_agent_fallback()
    assert behind == 1
    assert err is None


def test_agent_fallback_unparseable_is_undetermined(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: "hermes.exe")
    monkeypatch.setattr(shell, "run", lambda args, timeout=None: ShellResult(1, stdout="", stderr="Traceback (...)"))
    behind, err = updater._check_agent_fallback()
    assert behind is None
    assert "venv breakage" in err


def test_agent_fallback_no_hermes_on_path(monkeypatch):
    monkeypatch.setattr(updater.shutil, "which", lambda name: None)
    behind, err = updater._check_agent_fallback()
    assert behind is None
    assert "not found" in err


# ---- _check_webui_fallback ----

def test_webui_fallback_parses_rev_list_count(monkeypatch):
    calls = []

    def fake_run(args, timeout=None):
        calls.append(args)
        if "fetch" in args:
            return ShellResult(0)
        return ShellResult(0, stdout="5\n")

    monkeypatch.setattr(shell, "run", fake_run)
    behind, err = updater._check_webui_fallback(r"C:\hermes-webui", "master")
    assert behind == 5
    assert err is None
    assert any("fetch" in c for c in calls)


def test_webui_fallback_fetch_failure(monkeypatch):
    monkeypatch.setattr(shell, "run", lambda args, timeout=None: ShellResult(1, stderr="could not resolve host"))
    behind, err = updater._check_webui_fallback(r"C:\hermes-webui", "master")
    assert behind is None
    assert "resolve host" in err


# ---- check_updates: WebUI API優先、フォールバック統合 ----

def test_check_updates_uses_webui_api_when_available(monkeypatch):
    monkeypatch.setattr(
        shell, "http_post_json",
        lambda url, body, timeout=None: {
            "webui": {"name": "webui", "behind": 2},
            "agent": {"name": "agent", "behind": 0},
            "checked_at": 123.0,
            "include_agent": True,
        },
    )
    result = updater.check_updates(_cfg())
    assert result.agent_behind == 0
    assert result.webui_behind == 2
    assert result.source == "webui_api"
    assert result.agent_source == "webui_api"
    assert result.webui_source == "webui_api"


def test_check_updates_falls_back_when_api_unreachable(monkeypatch):
    monkeypatch.setattr(shell, "http_post_json", lambda url, body, timeout=None: None)
    monkeypatch.setattr(updater, "_check_agent_fallback", lambda: (1, None))
    monkeypatch.setattr(updater, "_check_webui_fallback", lambda path, branch: (0, None))
    result = updater.check_updates(_cfg())
    assert result.agent_behind == 1
    assert result.webui_behind == 0
    assert result.source == "fallback_cli"


def test_check_updates_partial_fallback_when_one_field_unknown(monkeypatch):
    # WebUI APIはagent側の情報を持っているがwebui側はno_git等で不明 -> webuiのみフォールバック
    monkeypatch.setattr(
        shell, "http_post_json",
        lambda url, body, timeout=None: {
            "webui": {"name": "webui", "behind": None, "error": "fetch failed"},
            "agent": {"name": "agent", "behind": 4},
            "checked_at": 123.0,
            "include_agent": True,
        },
    )
    monkeypatch.setattr(updater, "_check_webui_fallback", lambda path, branch: (7, None))
    result = updater.check_updates(_cfg())
    assert result.agent_behind == 4
    assert result.agent_source == "webui_api"
    assert result.webui_behind == 7
    assert result.webui_source == "fallback_cli"
    assert result.source == "fallback_cli"


def test_check_updates_disabled_setting_falls_back(monkeypatch):
    monkeypatch.setattr(shell, "http_post_json", lambda url, body, timeout=None: {"disabled": True})
    monkeypatch.setattr(updater, "_check_agent_fallback", lambda: (0, None))
    monkeypatch.setattr(updater, "_check_webui_fallback", lambda path, branch: (0, None))
    result = updater.check_updates(_cfg())
    assert result.source == "fallback_cli"


def test_check_updates_undetermined_when_fallback_cannot_parse(monkeypatch):
    monkeypatch.setattr(shell, "http_post_json", lambda url, body, timeout=None: None)
    monkeypatch.setattr(updater, "_check_agent_fallback", lambda: (None, "unrecognized output"))
    monkeypatch.setattr(updater, "_check_webui_fallback", lambda path, branch: (0, None))
    result = updater.check_updates(_cfg())
    assert result.undetermined is True
    assert result.agent_behind == 0  # 表示上は0のままだが undetermined フラグで区別できる
    assert result.has_update is False


def test_check_updates_not_undetermined_when_both_resolved(monkeypatch):
    monkeypatch.setattr(
        shell, "http_post_json",
        lambda url, body, timeout=None: {"webui": {"behind": 0}, "agent": {"behind": 0}},
    )
    result = updater.check_updates(_cfg())
    assert result.undetermined is False


# ---- apply_agent_update: taskkill失敗時もWebUI再起動を必ず試みる ----

def test_apply_agent_update_taskkill_failed_still_restarts_webui(monkeypatch):
    calls = []
    monkeypatch.setattr(shell, "run", lambda args, timeout=None: ShellResult(0))
    monkeypatch.setattr(shell, "find_pid_by_port", lambda port: 4821)
    monkeypatch.setattr(shell, "taskkill_pid", lambda pid, elevated=True: ShellResult(1, stderr="access denied"))

    def fake_start_scheduled_task(name, timeout=30):
        calls.append("restart")
        return ShellResult(0)

    monkeypatch.setattr(shell, "start_scheduled_task", fake_start_scheduled_task)
    monkeypatch.setattr(shell, "wait_for_health", lambda url, retries=10, delay=2.0: True)

    result = updater.apply_agent_update(_cfg())

    assert "restart" in calls, "taskkill失敗時もWebUI再起動を試みるべき"
    assert result.success is False
    assert result.aborted_reason == "taskkill_failed"
    step_names = [s.name for s in result.steps]
    assert "hermes_update" not in step_names, "taskkill失敗時はhermes updateをスキップすべき"
    assert "restart_webui_task" in step_names
    assert "webui_health_check" in step_names


def test_apply_agent_update_uac_denied_aborts_without_restart(monkeypatch):
    calls = []
    monkeypatch.setattr(shell, "run", lambda args, timeout=None: ShellResult(0))
    monkeypatch.setattr(shell, "find_pid_by_port", lambda port: 4821)
    monkeypatch.setattr(
        shell, "taskkill_pid", lambda pid, elevated=True: ShellResult(-1, elevation_denied=True)
    )
    monkeypatch.setattr(
        shell, "start_scheduled_task", lambda name, timeout=30: calls.append("restart") or ShellResult(0)
    )

    result = updater.apply_agent_update(_cfg())

    assert calls == [], "UAC拒否時はWebUIを触っていないため再起動を試みる必要はない"
    assert result.success is False
    assert result.aborted_reason == "uac_denied"


def test_apply_agent_update_gateway_stop_failure_is_logged_honestly(monkeypatch):
    monkeypatch.setattr(
        shell, "run",
        lambda args, timeout=None: ShellResult(1, stderr="boom") if "gateway" in args else ShellResult(0),
    )
    monkeypatch.setattr(shell, "find_pid_by_port", lambda port: None)
    monkeypatch.setattr(shell, "start_scheduled_task", lambda name, timeout=30: ShellResult(0))
    monkeypatch.setattr(shell, "wait_for_health", lambda url, retries=10, delay=2.0: True)

    result = updater.apply_agent_update(_cfg())

    gateway_step = next(s for s in result.steps if s.name == "gateway_stop")
    assert gateway_step.success is False


def test_apply_agent_update_success_path(monkeypatch):
    def fake_run(args, timeout=None):
        if "version" in args:
            return ShellResult(0, stdout="Hermes Agent v1.0\nUp to date\n")
        return ShellResult(0)

    monkeypatch.setattr(shell, "run", fake_run)
    monkeypatch.setattr(shell, "find_pid_by_port", lambda port: None)
    monkeypatch.setattr(shell, "start_scheduled_task", lambda name, timeout=30: ShellResult(0))
    monkeypatch.setattr(shell, "wait_for_health", lambda url, retries=10, delay=2.0: True)

    result = updater.apply_agent_update(_cfg())

    assert result.success is True
    assert result.aborted_reason is None


# ---- _apply_webui_manual_fallback: 失敗時のaborted_reason ----

def test_webui_manual_fallback_pull_failure_sets_aborted_reason(monkeypatch):
    monkeypatch.setattr(shell, "http_post", lambda url, body, timeout=None: None)
    monkeypatch.setattr(shell, "find_pid_by_port", lambda port: None)

    def fake_run(args, timeout=None):
        if "pull" in args:
            return ShellResult(1, stderr="not possible to fast-forward")
        return ShellResult(0)

    monkeypatch.setattr(shell, "run", fake_run)
    monkeypatch.setattr(shell, "start_scheduled_task", lambda name, timeout=30: ShellResult(0))
    monkeypatch.setattr(shell, "wait_for_health", lambda url, retries=10, delay=2.0: True)

    result = updater.apply_webui_update(_cfg())

    assert result.success is False
    assert result.aborted_reason == "webui_pull_failed"
    step_names = [s.name for s in result.steps]
    assert "restart_webui_task" in step_names
    assert "webui_health_check" in step_names
