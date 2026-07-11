"""共有テストフィクスチャ。

test_app.py / test_updater.py で重複していた _cfg() / _make_app() を
pytestフィクスチャとして統一する。
"""

from __future__ import annotations

import pytest

from hermes_updater import updater
from hermes_updater.app import UpdaterApp
from hermes_updater.models import CheckResult, UpdateConfig


@pytest.fixture
def make_config():
    """キーワード引数でフィールドを上書きした UpdateConfig を返すファクトリ。"""
    def _factory(**overrides) -> UpdateConfig:
        cfg = UpdateConfig()
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg
    return _factory


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    """UpdaterApp を返すファクトリ。check_result を渡すと check_updates をモックする。"""
    def _factory(check_result: CheckResult | None = None) -> UpdaterApp:
        if check_result is not None:
            monkeypatch.setattr(updater, "check_updates", lambda config: check_result)
        return UpdaterApp(base_dir=tmp_path)
    return _factory
