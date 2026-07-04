from pathlib import Path

from hermes_updater import config
from hermes_updater.models import AppState, CheckResult, UpdateConfig


def test_load_config_creates_default(tmp_path: Path):
    cfg = config.load_config(tmp_path)
    assert cfg.check_interval_hours == 24
    assert cfg.check_on_startup is True
    assert (tmp_path / "config.json").exists()


def test_save_and_load_config_roundtrip(tmp_path: Path):
    cfg = UpdateConfig(check_interval_hours=6, enable_notifications=False)
    config.save_config(cfg, tmp_path)
    loaded = config.load_config(tmp_path)
    assert loaded.check_interval_hours == 6
    assert loaded.enable_notifications is False


def test_load_state_missing_returns_default(tmp_path: Path):
    state = config.load_state(tmp_path)
    assert state.pending_update is False
    assert state.last_check_result.agent_behind == 0


def test_save_and_load_state_roundtrip(tmp_path: Path):
    state = AppState(
        last_check_ts=123.0,
        last_check_result=CheckResult(agent_behind=2, webui_behind=1, source="fallback_cli"),
        pending_update=True,
    )
    config.save_state(state, tmp_path)
    loaded = config.load_state(tmp_path)
    assert loaded.pending_update is True
    assert loaded.last_check_result.agent_behind == 2
    assert loaded.last_check_result.webui_behind == 1
    assert loaded.last_check_result.source == "fallback_cli"


def test_get_logs_dir_creates_directory(tmp_path: Path):
    logs_dir = config.get_logs_dir(tmp_path)
    assert logs_dir.exists()
    assert logs_dir.name == "logs"
