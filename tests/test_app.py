from hermes_updater import updater
from hermes_updater.app import UpdaterApp
from hermes_updater.models import ApplyResult, CheckResult


def _make_app(tmp_path, monkeypatch, check_result: CheckResult):
    monkeypatch.setattr(updater, "check_updates", lambda config: check_result)
    return UpdaterApp(base_dir=tmp_path)


def test_check_now_notifies_once_for_same_pending_state(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=2, webui_behind=0, source="webui_api")
    app = _make_app(tmp_path, monkeypatch, result)

    notified = []
    app.on_update_available = lambda r: notified.append(r)

    app.check_now()
    app.check_now()  # 同一のpending状態 -> 2回目は通知しない (実装計画書4節)

    assert len(notified) == 1
    assert app.state.pending_update is True


def test_check_now_renotifies_when_behind_count_changes(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=2, webui_behind=0, source="webui_api")
    app = _make_app(tmp_path, monkeypatch, result)
    notified = []
    app.on_update_available = lambda r: notified.append(r)

    app.check_now()
    updater.check_updates = lambda config: CheckResult(agent_behind=3, webui_behind=0, source="webui_api")
    app.check_now()

    assert len(notified) == 2


def test_check_now_no_notification_when_notifications_disabled(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=1, webui_behind=0, source="webui_api")
    app = _make_app(tmp_path, monkeypatch, result)
    app.config.enable_notifications = False
    notified = []
    app.on_update_available = lambda r: notified.append(r)

    app.check_now()

    assert notified == []
    assert app.state.pending_update is True


def test_on_check_complete_fires_every_check_regardless_of_notify_dedup(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=2, webui_behind=0, source="webui_api")
    app = _make_app(tmp_path, monkeypatch, result)
    completed = []
    app.on_check_complete = lambda r: completed.append(r)

    app.check_now()
    app.check_now()  # 通知は重複排除されるが、on_check_completeは毎回呼ばれる

    assert len(completed) == 2


def test_on_check_complete_fires_when_update_resolves(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=2, webui_behind=0, source="webui_api")
    app = _make_app(tmp_path, monkeypatch, result)
    completed = []
    app.on_check_complete = lambda r: completed.append(r)

    app.check_now()
    updater.check_updates = lambda config: CheckResult(agent_behind=0, webui_behind=0, source="webui_api")
    app.check_now()

    assert len(completed) == 2
    assert completed[0].has_update is True
    assert completed[1].has_update is False


def test_apply_now_aggregates_success_and_error(tmp_path, monkeypatch):
    app = UpdaterApp(base_dir=tmp_path)
    monkeypatch.setattr(
        updater, "apply_webui_update",
        lambda config, on_step=None: ApplyResult(target="webui", success=True, steps=[]),
    )
    monkeypatch.setattr(
        updater, "apply_agent_update",
        lambda config, on_step=None: ApplyResult(target="agent", success=False, aborted_reason="uac_denied", steps=[]),
    )

    results = app.apply_now(["webui", "agent"])

    assert results["webui"].success
    assert not results["agent"].success
    assert app.state.last_update_success is False
    assert "agent:uac_denied" in app.state.last_error


def test_check_now_notifies_undetermined_once(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=0, webui_behind=0, undetermined=True, error="venv broken")
    app = _make_app(tmp_path, monkeypatch, result)
    notified = []
    app.on_check_undetermined = lambda r: notified.append(r)

    app.check_now()
    app.check_now()  # 同一の判定不能状態 -> 2回目は通知しない

    assert len(notified) == 1


def test_check_now_renotifies_undetermined_after_it_clears(tmp_path, monkeypatch):
    result = CheckResult(agent_behind=0, webui_behind=0, undetermined=True, error="venv broken")
    app = _make_app(tmp_path, monkeypatch, result)
    notified = []
    app.on_check_undetermined = lambda r: notified.append(r)

    app.check_now()
    updater.check_updates = lambda config: CheckResult(agent_behind=0, webui_behind=0, undetermined=False)
    app.check_now()
    updater.check_updates = lambda config: CheckResult(agent_behind=0, webui_behind=0, undetermined=True, error="broken again")
    app.check_now()

    assert len(notified) == 2


def test_apply_now_ignores_concurrent_duplicate_call(tmp_path, monkeypatch):
    app = UpdaterApp(base_dir=tmp_path)
    monkeypatch.setattr(
        updater, "apply_webui_update",
        lambda config: ApplyResult(target="webui", success=True, steps=[]),
    )
    app._apply_lock.acquire()  # 実行中を模擬
    try:
        results = app.apply_now(["webui"])
    finally:
        app._apply_lock.release()

    assert results == {}


def test_check_now_returns_cached_result_when_already_running(tmp_path, monkeypatch):
    app = UpdaterApp(base_dir=tmp_path)
    cached = CheckResult(agent_behind=9, webui_behind=0)
    app.state.last_check_result = cached
    monkeypatch.setattr(updater, "check_updates", lambda config: (_ for _ in ()).throw(AssertionError("should not run")))

    app._check_lock.acquire()  # 実行中を模擬
    try:
        result = app.check_now()
    finally:
        app._check_lock.release()

    assert result is cached


def test_safe_check_now_swallows_exceptions(tmp_path, monkeypatch):
    app = UpdaterApp(base_dir=tmp_path)
    monkeypatch.setattr(app, "check_now", lambda: (_ for _ in ()).throw(ValueError("boom")))

    app._safe_check_now()  # 例外が伝播しないことを確認(スケジューラスレッドを落とさない)


def test_apply_now_fires_on_apply_start_and_on_apply_step(tmp_path, monkeypatch):
    app = UpdaterApp(base_dir=tmp_path)

    def fake_apply_webui_update(config, on_step=None):
        if on_step:
            from hermes_updater.models import StepResult
            on_step(StepResult("git_pull_webui", True, "ok"))
        return ApplyResult(target="webui", success=True, steps=[])

    monkeypatch.setattr(updater, "apply_webui_update", fake_apply_webui_update)

    started = []
    steps = []
    app.on_apply_start = lambda targets: started.append(targets)
    app.on_apply_step = lambda target, step: steps.append((target, step.name))

    app.apply_now(["webui"])

    assert started == [["webui"]]
    assert steps == [("webui", "git_pull_webui")]


def test_apply_now_does_not_fire_on_apply_start_when_already_running(tmp_path, monkeypatch):
    app = UpdaterApp(base_dir=tmp_path)
    monkeypatch.setattr(
        updater, "apply_webui_update",
        lambda config, on_step=None: ApplyResult(target="webui", success=True, steps=[]),
    )
    started = []
    app.on_apply_start = lambda targets: started.append(targets)

    app._apply_lock.acquire()  # 実行中を模擬
    try:
        results = app.apply_now(["webui"])
    finally:
        app._apply_lock.release()

    assert results == {}
    assert started == []


def test_safe_interval_seconds_clamps_invalid_value(tmp_path):
    app = UpdaterApp(base_dir=tmp_path)
    app.config.check_interval_hours = 0
    assert app._safe_interval_seconds() == 24 * 3600

    app.config.check_interval_hours = -5
    assert app._safe_interval_seconds() == 24 * 3600

    app.config.check_interval_hours = 6
    assert app._safe_interval_seconds() == 6 * 3600
