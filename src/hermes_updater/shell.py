"""subprocessラッパー・UAC昇格・ポート→PID特定・HTTPヘルスチェック。

このモジュールは外部システム(Hermes Agent / hermes-webui)を一切直接importせず、
常にコマンドライン(CLI/PowerShell/HTTP)経由で操作する(実装計画書1節の方針)。
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import requests

from hermes_updater.logger import get_logger

log = get_logger("shell")

CREATE_NO_WINDOW = 0x08000000


@dataclass
class ShellResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    elevation_denied: bool = False

    @property
    def success(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.elevation_denied


def run(args: list[str], timeout: Optional[float] = None, cwd: Optional[str] = None) -> ShellResult:
    """通常権限でコマンドを実行する。"""
    log.debug("run: %s", " ".join(args))
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW,
        )
        return ShellResult(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired as e:
        log.warning("command timed out after %ss: %s", timeout, " ".join(args))
        return ShellResult(
            returncode=-1,
            stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
            stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
            timed_out=True,
        )
    except FileNotFoundError as e:
        log.error("command not found: %s (%s)", args[0] if args else "?", e)
        return ShellResult(returncode=-1, stderr=str(e))


def _ps_quote(value: str) -> str:
    """PowerShellのシングルクォート文字列として安全な形にエスケープする
    (シングルクォートは''に二重化するのがPowerShellのリテラルエスケープ)。
    """
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script: str, timeout: Optional[float] = None) -> ShellResult:
    """非対話PowerShellでスクリプト文字列を実行する。"""
    return run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


# UACプロンプトへのユーザーの反応時間を含むため、通常のsubprocessタイムアウトより長めに取る
ELEVATED_DEFAULT_TIMEOUT = 120


def run_elevated(exe: str, args: list[str], timeout: Optional[float] = ELEVATED_DEFAULT_TIMEOUT) -> ShellResult:
    """UAC昇格して`exe`を実行し、終了コードのみ取得する(Start-Process -Verb RunAsは
    出力リダイレクトと併用できないため、標準出力/エラーは取得しない)。

    ユーザーがUACプロンプトで拒否した場合は `elevation_denied=True` を返す。
    UACプロンプトへの応答待ちでタイムアウトした場合は `timed_out=True` を返す
    (「拒否」ではなく「未応答」であることを区別するため、汎用失敗扱いにしない)。
    """
    arg_list = ",".join(_ps_quote(a) for a in args)
    script = (
        "$ErrorActionPreference = 'Stop'; "
        "try { "
        f"$p = Start-Process -FilePath {_ps_quote(exe)} -ArgumentList {arg_list} "
        "-Verb RunAs -Wait -PassThru -WindowStyle Hidden; "
        "Write-Output \"EXITCODE:$($p.ExitCode)\" "
        "} catch { "
        "Write-Output 'ELEVATION_DENIED'; "
        "Write-Output $_.Exception.Message "
        "}"
    )
    result = run_powershell(script, timeout=timeout)
    if result.timed_out:
        log.warning("run_elevated: timed out waiting for UAC response for: %s %s", exe, args)
        return ShellResult(returncode=-1, stdout=result.stdout, stderr=result.stderr, timed_out=True)
    if "ELEVATION_DENIED" in result.stdout:
        log.warning("elevation denied or failed for: %s %s", exe, args)
        return ShellResult(returncode=-1, stdout=result.stdout, stderr=result.stderr, elevation_denied=True)
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("EXITCODE:"):
            try:
                code = int(line.split(":", 1)[1])
            except ValueError:
                code = -1
            return ShellResult(returncode=code, stdout=result.stdout, stderr=result.stderr)
    # PowerShell自体が失敗した(スクリプトエラー等)
    log.error("run_elevated: unexpected output, treating as failure: %r", result.stdout)
    return ShellResult(returncode=-1, stdout=result.stdout, stderr=result.stderr)


def find_pid_by_port(port: int) -> Optional[int]:
    """指定ポートでLISTENしているプロセスのPIDを返す(未使用ならNone)。"""
    script = (
        f"(Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -First 1 -ExpandProperty OwningProcess)"
    )
    result = run_powershell(script, timeout=15)
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return int(text.splitlines()[0].strip())
    except ValueError:
        log.warning("find_pid_by_port: could not parse PID from %r", text)
        return None


def taskkill_pid(pid: int, elevated: bool = True, timeout: float = ELEVATED_DEFAULT_TIMEOUT) -> ShellResult:
    """`taskkill /F /T /PID <pid>` を実行する(既定でUAC昇格)。"""
    args = ["/F", "/T", "/PID", str(pid)]
    if elevated:
        return run_elevated("taskkill.exe", args, timeout=timeout)
    return run(["taskkill.exe", *args], timeout=timeout)


def start_scheduled_task(task_name: str, timeout: float = 30) -> ShellResult:
    """`Start-ScheduledTask -TaskName <task_name>` を実行する。"""
    return run_powershell(f"Start-ScheduledTask -TaskName {_ps_quote(task_name)}", timeout=timeout)


def http_get_json(url: str, timeout: float = 5) -> Optional[dict]:
    """GETしてJSONをdictで返す。接続失敗・タイムアウト・非2xxはNone。"""
    try:
        resp = requests.get(url, timeout=timeout)
        if not resp.ok:
            log.debug("http_get_json: %s returned %s", url, resp.status_code)
            return None
        return resp.json()
    except requests.RequestException as e:
        log.debug("http_get_json: %s failed: %s", url, e)
        return None


def http_post(url: str, json_body: Optional[dict] = None, timeout: float = 60) -> Optional[requests.Response]:
    """POSTしてResponseをそのまま返す(ステータスコードを呼び出し側で判定したい場合)。
    接続失敗・タイムアウトはNone。
    """
    try:
        return requests.post(url, json=json_body, timeout=timeout)
    except requests.RequestException as e:
        log.debug("http_post: %s failed: %s", url, e)
        return None


def http_post_json(url: str, json_body: Optional[dict] = None, timeout: float = 60) -> Optional[dict]:
    """POSTしてJSONをdictで返す。接続失敗・タイムアウト・非2xx・非JSONはNone。"""
    resp = http_post(url, json_body, timeout=timeout)
    if resp is None:
        return None
    if not resp.ok:
        log.debug("http_post_json: %s returned %s", url, resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError:
        log.debug("http_post_json: %s returned non-JSON body", url)
        return None


def wait_for_health(url: str, retries: int = 5, delay: float = 2.0, timeout: float = 5) -> bool:
    """`url`が200を返すまで`retries`回、`delay`秒間隔でリトライする。"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                return True
        except requests.RequestException:
            pass
        if attempt < retries - 1:
            time.sleep(delay)
    return False
