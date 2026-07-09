"""更新チェック・適用シーケンス (実装計画書 4節・5節、Phase16準拠)。

WebUI自身の `api/updates.py` (2026-07-05時点のソース) を実機で確認し、以下のレスポンス
スキーマに合わせてある:

``GET/POST /api/updates/check`` ->
    {"webui": {"behind": int|None, "no_git"?, "error"?, "ignored"?, ...},
     "agent": {...同様...}, "checked_at": float, "include_agent": bool,
     "disabled"?: bool}

``POST /api/updates/apply`` (body: {"target": "webui"|"agent"}) ->
    {"ok": bool, "message": str, "restart_blocked"?: bool, "conflict"?: bool,
     "diverged"?: bool, "stash_conflict"?: bool, "restart_scheduled"?: bool}
"""

from __future__ import annotations

import re
import shutil
from typing import Callable, Optional

from hermes_updater import shell
from hermes_updater.logger import get_logger
from hermes_updater.models import ApplyResult, CheckResult, StepResult, UpdateConfig

log = get_logger("updater")

OnStep = Optional[Callable[[StepResult], None]]


def _add_step(steps: list[StepResult], on_step: OnStep, name: str, success: bool, detail: str) -> StepResult:
    """StepResultを記録しつつ、Issue #9向けの進捗コールバックを都度発火する。"""
    step = StepResult(name, success, detail)
    steps.append(step)
    if on_step:
        try:
            on_step(step)
        except Exception:
            log.exception("on_step callback failed")
    return step

WEBUI_CHECK_TIMEOUT = 5
WEBUI_APPLY_TIMEOUT = 60
AGENT_UPDATE_TIMEOUT = 300
HEALTH_RETRIES = 10
HEALTH_DELAY = 2.0

_AGENT_CHECK_UP_TO_DATE_RE = re.compile(r"Already up to date")
_AGENT_CHECK_BEHIND_RE = re.compile(r"Update available:\s*(\d+)\s*commits?\s*behind")
_AGENT_CHECK_SHALLOW_RE = re.compile(r"Update available \(behind")
_AGENT_VERSION_UP_TO_DATE_RE = re.compile(r"Up to date")


def check_updates(config: UpdateConfig) -> CheckResult:
    """FR-1/FR-2: WebUI APIを優先し、応答不能ならCLI/gitフォールバックする。"""
    api_data = shell.http_post_json(
        f"{config.webui_base_url}/api/updates/check", {"force": False}, timeout=WEBUI_CHECK_TIMEOUT
    )

    agent_behind: int | None = None
    webui_behind: int | None = None
    agent_source: str | None = None
    webui_source: str | None = None
    error_parts: list[str] = []

    if api_data and not api_data.get("disabled"):
        agent_info = api_data.get("agent") or {}
        webui_info = api_data.get("webui") or {}
        raw_agent_behind = agent_info.get("behind")
        raw_webui_behind = webui_info.get("behind")
        if raw_agent_behind is not None:
            agent_behind = int(raw_agent_behind)
            agent_source = "webui_api"
        if raw_webui_behind is not None:
            webui_behind = int(raw_webui_behind)
            webui_source = "webui_api"
        if agent_info.get("error"):
            error_parts.append(f"agent(webui_api): {agent_info['error']}")
        if webui_info.get("error"):
            error_parts.append(f"webui(webui_api): {webui_info['error']}")
    else:
        log.warning("WebUI update-check API unreachable or disabled; falling back to CLI/git")

    if agent_behind is None:
        agent_behind, agent_err = _check_agent_fallback()
        agent_source = "fallback_cli"
        if agent_err:
            error_parts.append(f"agent(fallback): {agent_err}")

    if webui_behind is None:
        webui_behind, webui_err = _check_webui_fallback(config.hermes_webui_path, config.webui_branch)
        webui_source = "fallback_cli"
        if webui_err:
            error_parts.append(f"webui(fallback): {webui_err}")

    overall_source = "webui_api" if (agent_source == "webui_api" and webui_source == "webui_api") else "fallback_cli"
    # 判定不能(venv破損等)をhas_update=Falseの「更新なし」と区別するためのフラグ
    # (実装計画書4節: 判定不能はvenv破損等の異常系として別途通知する)
    undetermined = agent_behind is None or webui_behind is None

    return CheckResult(
        agent_behind=agent_behind or 0,
        webui_behind=webui_behind or 0,
        source=overall_source,
        agent_source=agent_source,
        webui_source=webui_source,
        error="; ".join(error_parts) if error_parts else None,
        undetermined=undetermined,
    )


def _check_agent_fallback() -> tuple[int | None, str | None]:
    """`hermes update --check`をパースする(判定不能ならNoneを返し呼び出し側で異常扱い)。"""
    if not shutil.which("hermes"):
        return None, "hermes command not found on PATH"
    result = shell.run(["hermes", "update", "--check"], timeout=60)
    output = result.stdout or ""
    if _AGENT_CHECK_UP_TO_DATE_RE.search(output):
        return 0, None
    match = _AGENT_CHECK_BEHIND_RE.search(output)
    if match:
        return int(match.group(1)), None
    if _AGENT_CHECK_SHALLOW_RE.search(output):
        # shallow clone: 件数不明だが更新はある("Update available (behind ...)")
        return 1, None
    detail = (output.strip() or result.stderr.strip() or "no output")[:300]
    log.warning("hermes update --check: unrecognized output, treating as undetermined: %r", detail)
    return None, f"unrecognized output (possible venv breakage): {detail}"


def _check_webui_fallback(webui_path: str, branch: str) -> tuple[int | None, str | None]:
    """`git fetch` + `rev-list --count HEAD..origin/<branch>`で件数を取得する。"""
    fetch_result = shell.run(["git", "-C", webui_path, "fetch", "origin", branch], timeout=30)
    if not fetch_result.success:
        detail = (fetch_result.stderr.strip() or fetch_result.stdout.strip() or "fetch failed")[:300]
        return None, detail
    rev_result = shell.run(
        ["git", "-C", webui_path, "rev-list", f"HEAD..origin/{branch}", "--count"], timeout=15
    )
    if not rev_result.success:
        detail = (rev_result.stderr.strip() or "rev-list failed")[:300]
        return None, detail
    try:
        return int(rev_result.stdout.strip()), None
    except ValueError:
        return None, f"unparseable rev-list output: {rev_result.stdout.strip()[:200]}"


def apply_webui_update(config: UpdateConfig, on_step: OnStep = None) -> ApplyResult:
    """5.1節: WebUI自身の更新(API優先、応答不能時のみ手動フォールバック)。"""
    steps: list[StepResult] = []
    response = shell.http_post(
        f"{config.webui_base_url}/api/updates/apply", {"target": "webui"}, timeout=WEBUI_APPLY_TIMEOUT
    )

    if response is not None:
        try:
            data = response.json()
        except ValueError:
            data = {}
        _add_step(steps, on_step, "webui_api_apply", response.ok, f"HTTP {response.status_code}: {data}")
        if data.get("restart_blocked"):
            log.info("WebUI update blocked: active stream/session in progress")
            return ApplyResult(target="webui", success=False, aborted_reason="webui_busy", steps=steps)
        if data.get("ok"):
            if data.get("conflict") or data.get("diverged") or data.get("stash_conflict"):
                log.warning("WebUI apply succeeded with warning: %s", data.get("message"))
            return ApplyResult(target="webui", success=True, steps=steps)
        if data.get("conflict") or data.get("diverged") or data.get("stash_conflict"):
            log.warning("WebUI apply reported conflict/diverge: %s", data.get("message"))
            return ApplyResult(target="webui", success=False, aborted_reason="conflict", steps=steps)
        log.error("WebUI apply API failed: %s", data.get("message"))
        return ApplyResult(target="webui", success=False, aborted_reason="apply_api_failed", steps=steps)

    log.warning("WebUI apply API unreachable; falling back to manual git pull + task restart")
    return _apply_webui_manual_fallback(config, steps, on_step)


def _kill_webui_process(config: UpdateConfig, steps: list[StepResult], on_step: OnStep = None) -> Optional[str]:
    """WebUIプロセスを停止する(WebUI/Agent両方の適用シーケンスで共通)。

    戻り値:
    - ``None``: 停止できた、またはそもそも起動していなかった(続行してよい)
    - ``"uac_denied"``: UACで拒否された(何も変更していないので即中断してよい)
    - ``"taskkill_failed"``: kill自体が失敗し停止できたか不明(以降のリスクのある
      ステップ=hermes update/git pullはスキップすべきだが、WebUI再起動は試みる)
    """
    pid = shell.find_pid_by_port(config.webui_port)
    if pid is None:
        _add_step(steps, on_step, "taskkill_webui", True, "port not in use, skipped")
        return None
    kill_result = shell.taskkill_pid(pid, elevated=True)
    if kill_result.elevation_denied:
        _add_step(steps, on_step, "taskkill_webui", False, "elevation denied by user")
        return "uac_denied"
    if not kill_result.success:
        # taskkillはUAC昇格(Start-Process -Verb RunAs -Wait)を経由するため実行までに
        # 数秒〜10秒のラグがあり、その間にWebUI自身の自己再起動(update APIの
        # restart_scheduled)で対象PIDが既に終了していることがある(EXITCODE:128 =
        # 対象PIDが既に存在しない。Issue #6)。ポートを再確認し、既に未使用なら
        # 結果的に停止済みとみなして成功扱いにする。
        recheck_pid = shell.find_pid_by_port(config.webui_port)
        if recheck_pid is None:
            _add_step(
                steps, on_step, "taskkill_webui", True,
                f"taskkill failed ({kill_result.stdout or kill_result.stderr}) but port no longer "
                "in use; process already stopped",
            )
            return None
        _add_step(steps, on_step, "taskkill_webui", False, kill_result.stdout or kill_result.stderr)
        log.error("Failed to kill WebUI process (PID %s)", pid)
        return "taskkill_failed"
    _add_step(steps, on_step, "taskkill_webui", True, kill_result.stdout or kill_result.stderr)
    return None


def _restart_webui_and_check_health(
    config: UpdateConfig, steps: list[StepResult], on_step: OnStep = None
) -> tuple[bool, bool]:
    """WebUIのタスクスケジューラ再起動＋`/health`確認(WebUI/Agent両方の適用シーケンスで共通)。"""
    start_result = shell.start_scheduled_task(config.webui_task_name)
    _add_step(steps, on_step, "restart_webui_task", start_result.success, start_result.stdout + start_result.stderr)
    if not start_result.success:
        log.error("Failed to restart WebUI scheduled task '%s'", config.webui_task_name)

    healthy = shell.wait_for_health(f"{config.webui_base_url}/health", retries=HEALTH_RETRIES, delay=HEALTH_DELAY)
    _add_step(steps, on_step, "webui_health_check", healthy, "200 OK" if healthy else "health check failed")
    if not healthy:
        log.error("WebUI health check failed after restart")
    return start_result.success, healthy


def _apply_webui_manual_fallback(config: UpdateConfig, steps: list[StepResult], on_step: OnStep = None) -> ApplyResult:
    kill_outcome = _kill_webui_process(config, steps, on_step)
    if kill_outcome == "uac_denied":
        return ApplyResult(target="webui", success=False, aborted_reason="uac_denied", steps=steps)

    pull_failed = True
    if kill_outcome == "taskkill_failed":
        log.error(
            "Skipping git pull because WebUI process could not be confirmed stopped; "
            "will still attempt to restore WebUI"
        )
    else:
        pull_result = shell.run(["git", "-C", config.hermes_webui_path, "pull", "--ff-only"], timeout=30)
        _add_step(steps, on_step, "git_pull_webui", pull_result.success, pull_result.stdout + pull_result.stderr)
        pull_failed = not pull_result.success
        if pull_failed:
            log.warning("WebUI git pull --ff-only failed (non-fast-forward or other); recorded as warning")

    # 失敗時もWebUIは必ず起動状態に戻す(実装計画5.2節「方針」。WebUI自身の更新にも同じ方針を適用)
    start_ok, healthy = _restart_webui_and_check_health(config, steps, on_step)

    if kill_outcome == "taskkill_failed":
        aborted_reason = "taskkill_failed"
    elif pull_failed:
        aborted_reason = "webui_pull_failed"
    elif not start_ok:
        aborted_reason = "webui_task_restart_failed"
    elif not healthy:
        aborted_reason = "webui_health_check_failed"
    else:
        aborted_reason = None

    success = kill_outcome is None and not pull_failed and start_ok and healthy
    return ApplyResult(target="webui", success=success, aborted_reason=aborted_reason, steps=steps)


def apply_agent_update(config: UpdateConfig, on_step: OnStep = None) -> ApplyResult:
    """5.2節: `hermes update` CLI経由の固定手順(Phase16準拠)。"""
    steps: list[StepResult] = []

    gw_stop = shell.run(["hermes", "gateway", "stop"], timeout=30)
    _add_step(steps, on_step, "gateway_stop", gw_stop.success, gw_stop.stdout + gw_stop.stderr)
    if not gw_stop.success:
        log.warning("hermes gateway stop returned non-zero (best-effort, continuing): %s", gw_stop.stderr)

    kill_outcome = _kill_webui_process(config, steps, on_step)
    if kill_outcome == "uac_denied":
        return ApplyResult(target="agent", success=False, aborted_reason="uac_denied", steps=steps)

    update_ok = False
    version_ok = False
    if kill_outcome == "taskkill_failed":
        log.error(
            "Skipping hermes update because WebUI process could not be confirmed stopped; "
            "will still attempt to restore WebUI"
        )
    else:
        update_result = shell.run(["hermes", "update", "--yes"], timeout=AGENT_UPDATE_TIMEOUT)
        update_ok = update_result.success
        _add_step(
            steps, on_step, "hermes_update", update_ok, (update_result.stdout + update_result.stderr)[-2000:]
        )
        if update_ok:
            version_result = shell.run(["hermes", "version"], timeout=30)
            version_ok = bool(_AGENT_VERSION_UP_TO_DATE_RE.search(version_result.stdout or ""))
            _add_step(steps, on_step, "hermes_version_check", version_ok, version_result.stdout)
        else:
            log.error("hermes update --yes failed; WebUI will still be restarted before aborting")

    # 失敗時もWebUIは必ず起動状態に戻す(実装計画5.2節「方針」)
    start_ok, healthy = _restart_webui_and_check_health(config, steps, on_step)

    if kill_outcome == "taskkill_failed":
        aborted_reason = "taskkill_failed"
    elif not update_ok:
        aborted_reason = "hermes_update_failed"
    elif not version_ok:
        aborted_reason = "version_check_failed"
    elif not start_ok:
        aborted_reason = "webui_task_restart_failed"
    elif not healthy:
        aborted_reason = "webui_health_check_failed"
    else:
        aborted_reason = None

    success = kill_outcome is None and update_ok and version_ok and start_ok and healthy
    return ApplyResult(target="agent", success=success, aborted_reason=aborted_reason, steps=steps)
