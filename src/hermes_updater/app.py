"""ライフサイクル・バックグラウンドスケジューラ (実装計画書 4節)。

トレイUIなし(ヘッドレス)でも `run_forever()` だけで動作確認できるように、
UI/通知への依存はコールバック(`on_update_available`)経由に留める。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from hermes_updater import config as config_module
from hermes_updater import updater
from hermes_updater.logger import get_logger
from hermes_updater.models import ApplyResult, CheckResult, StepResult

log = get_logger("app")


def _log_apply_result(target: str, result: ApplyResult) -> None:
    """FR-7: 各ステップの成否・出力をログファイルに記録する。"""
    for step in result.steps:
        detail = step.detail.strip().replace("\n", " ")[:500]
        level = log.info if step.success else log.warning
        level("[%s] step=%s success=%s detail=%s", target, step.name, step.success, detail)
    log.info("[%s] apply result: success=%s aborted_reason=%s", target, result.success, result.aborted_reason)


class UpdaterApp:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir
        self.config = config_module.load_config(base_dir)
        self.state = config_module.load_state(base_dir)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        # check_now/apply_nowの多重実行(トレイメニュー連打・スケジューラとの競合)を防ぐ非ブロッキングロック
        self._check_lock = threading.Lock()
        self._apply_lock = threading.Lock()
        # UI/通知層から差し込まれるコールバック。CheckResultを受け取る。
        self.on_update_available: Optional[Callable[[CheckResult], None]] = None
        self.on_check_undetermined: Optional[Callable[[CheckResult], None]] = None
        # 通知の要否に関わらず、チェック完了のたびに必ず呼ばれる(アイコン表示の更新用)。
        self.on_check_complete: Optional[Callable[[CheckResult], None]] = None
        # Issue #9: 更新適用の開始・各ステップ完了を通知するコールバック(UI/CLI層で進捗表示に使う)。
        self.on_apply_start: Optional[Callable[[list[str]], None]] = None
        self.on_apply_step: Optional[Callable[[str, StepResult], None]] = None

    def reload_config(self) -> None:
        with self._lock:
            self.config = config_module.load_config(self.base_dir)

    def check_now(self) -> CheckResult:
        """FR-5「今すぐチェック」・スケジューラの両方から呼ばれる、必ず実チェックを行うパス。

        既にチェックが進行中の場合は多重実行せず、直近の結果をそのまま返す。
        """
        if not self._check_lock.acquire(blocking=False):
            log.info("check already in progress, skipping duplicate request")
            return self.state.last_check_result
        try:
            return self._check_now_impl()
        finally:
            self._check_lock.release()

    def _check_now_impl(self) -> CheckResult:
        log.info("starting update check")
        result = updater.check_updates(self.config)
        log.info(
            "check complete: agent_behind=%d webui_behind=%d source=%s error=%s",
            result.agent_behind, result.webui_behind, result.source, result.error,
        )

        should_notify_update = False
        should_notify_undetermined = False
        with self._lock:
            self.state.last_check_result = result
            self.state.last_check_ts = time.time()
            self.state.pending_update = result.has_update
            if result.has_update:
                already_notified = (
                    result.agent_behind == self.state.last_notified_agent_behind
                    and result.webui_behind == self.state.last_notified_webui_behind
                )
                should_notify_update = self.config.enable_notifications and not already_notified
                if should_notify_update:
                    self.state.last_notified_agent_behind = result.agent_behind
                    self.state.last_notified_webui_behind = result.webui_behind
            else:
                # 更新が解消されたら、次回再出現時にまた通知できるようにリセットする
                self.state.last_notified_agent_behind = 0
                self.state.last_notified_webui_behind = 0

            if result.undetermined:
                should_notify_undetermined = self.config.enable_notifications and not self.state.last_notified_undetermined
                self.state.last_notified_undetermined = True
            else:
                self.state.last_notified_undetermined = False

            config_module.save_state(self.state, self.base_dir)

        if should_notify_update and self.on_update_available:
            try:
                self.on_update_available(result)
            except Exception:
                log.exception("on_update_available callback failed")
        if should_notify_undetermined and self.on_check_undetermined:
            try:
                self.on_check_undetermined(result)
            except Exception:
                log.exception("on_check_undetermined callback failed")
        if self.on_check_complete:
            try:
                self.on_check_complete(result)
            except Exception:
                log.exception("on_check_complete callback failed")
        return result

    def apply_now(self, targets: Iterable[str]) -> dict[str, ApplyResult]:
        """FR-6: 対象ごとの更新適用シーケンスを実行する。

        既に適用が進行中の場合は多重実行せず、空の結果を返す
        (taskkill・hermes updateといった実害のある操作の同時実行を防ぐため)。
        """
        if not self._apply_lock.acquire(blocking=False):
            log.warning("apply already in progress, ignoring duplicate request")
            return {}
        try:
            return self._apply_now_impl(targets)
        finally:
            self._apply_lock.release()

    def _apply_now_impl(self, targets: Iterable[str]) -> dict[str, ApplyResult]:
        targets = list(targets)
        if self.on_apply_start:
            try:
                self.on_apply_start(targets)
            except Exception:
                log.exception("on_apply_start callback failed")

        results: dict[str, ApplyResult] = {}
        # 5.1→5.2の順を推奨(実装計画書「方針」): 先にWebUI自身、その後Agent
        if "webui" in targets:
            log.info("applying webui update")
            results["webui"] = updater.apply_webui_update(self.config, on_step=self._apply_step_callback("webui"))
            _log_apply_result("webui", results["webui"])
        if "agent" in targets:
            log.info("applying agent update")
            results["agent"] = updater.apply_agent_update(self.config, on_step=self._apply_step_callback("agent"))
            _log_apply_result("agent", results["agent"])

        with self._lock:
            self.state.last_update_ts = time.time()
            if results:
                self.state.last_update_success = all(r.success for r in results.values())
            errors = [f"{t}:{r.aborted_reason}" for t, r in results.items() if r.aborted_reason]
            self.state.last_error = "; ".join(errors) if errors else None
            config_module.save_state(self.state, self.base_dir)

        return results

    def _apply_step_callback(self, target: str) -> Callable[[StepResult], None]:
        def _on_step(step: StepResult) -> None:
            if self.on_apply_step:
                try:
                    self.on_apply_step(target, step)
                except Exception:
                    log.exception("on_apply_step callback failed")
        return _on_step

    def run_forever(self) -> None:
        """バックグラウンドスケジューラ本体。`stop()`が呼ばれるまでブロックする。

        1回のチェックで予期しない例外が起きても、スケジューラスレッド自体は
        停止させない(以降永久にチェックが走らなくなるのを防ぐ)。
        """
        if self.config.check_on_startup:
            elapsed = time.time() - self.state.last_check_ts
            if elapsed >= self._safe_interval_seconds():
                self._safe_check_now()
            else:
                log.info("skipping startup check: last check was %.1fh ago", elapsed / 3600)

        while not self._stop_event.is_set():
            if self._stop_event.wait(timeout=self._safe_interval_seconds()):
                break
            self._safe_check_now()

    def _safe_interval_seconds(self) -> float:
        hours = self.config.check_interval_hours
        if hours <= 0:
            log.warning("check_interval_hours=%s is invalid; using default 24", hours)
            hours = 24
        return hours * 3600

    def _safe_check_now(self) -> None:
        try:
            self.check_now()
        except Exception:
            log.exception("scheduled check_now() failed; will retry at next interval")

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="hermes-updater-scheduler", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        log.info("stopping scheduler")
        self._stop_event.set()
