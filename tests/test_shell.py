from hermes_updater import shell
from hermes_updater.shell import ShellResult


def test_run_elevated_parses_exit_code(monkeypatch):
    monkeypatch.setattr(shell, "run_powershell", lambda script, timeout=None: ShellResult(0, stdout="EXITCODE:0\n"))
    result = shell.run_elevated("taskkill.exe", ["/F", "/PID", "123"])
    assert result.success
    assert result.returncode == 0
    assert not result.elevation_denied


def test_run_elevated_nonzero_exit_is_failure(monkeypatch):
    monkeypatch.setattr(shell, "run_powershell", lambda script, timeout=None: ShellResult(0, stdout="EXITCODE:128\n"))
    result = shell.run_elevated("taskkill.exe", ["/F", "/PID", "123"])
    assert not result.success
    assert result.returncode == 128


def test_run_elevated_detects_uac_denial(monkeypatch):
    monkeypatch.setattr(
        shell, "run_powershell",
        lambda script, timeout=None: ShellResult(0, stdout="ELEVATION_DENIED\nThe operation was canceled by the user.\n"),
    )
    result = shell.run_elevated("taskkill.exe", ["/F", "/PID", "123"])
    assert result.elevation_denied
    assert not result.success


def test_find_pid_by_port_parses_pid(monkeypatch):
    monkeypatch.setattr(shell, "run_powershell", lambda script, timeout=None: ShellResult(0, stdout="4821\n"))
    assert shell.find_pid_by_port(8788) == 4821


def test_find_pid_by_port_returns_none_when_unused(monkeypatch):
    monkeypatch.setattr(shell, "run_powershell", lambda script, timeout=None: ShellResult(0, stdout=""))
    assert shell.find_pid_by_port(8788) is None


def test_taskkill_pid_uses_elevation_by_default(monkeypatch):
    captured = {}

    def fake_run_elevated(exe, args, timeout=None):
        captured["exe"] = exe
        captured["args"] = args
        return ShellResult(0, stdout="EXITCODE:0")

    monkeypatch.setattr(shell, "run_elevated", fake_run_elevated)
    result = shell.taskkill_pid(4821)
    assert result.success
    assert captured["exe"] == "taskkill.exe"
    assert captured["args"] == ["/F", "/T", "/PID", "4821"]


def test_wait_for_health_succeeds_on_200(monkeypatch):
    class FakeResponse:
        status_code = 200

    monkeypatch.setattr(shell.requests, "get", lambda url, timeout=None: FakeResponse())
    assert shell.wait_for_health("http://127.0.0.1:8788/health", retries=1, delay=0)


def test_wait_for_health_fails_after_retries(monkeypatch):
    def raise_conn_error(url, timeout=None):
        raise shell.requests.ConnectionError("refused")

    monkeypatch.setattr(shell.requests, "get", raise_conn_error)
    assert not shell.wait_for_health("http://127.0.0.1:8788/health", retries=2, delay=0)


def test_ps_quote_escapes_embedded_single_quote():
    assert shell._ps_quote("Bob's Task") == "'Bob''s Task'"


def test_run_elevated_escapes_single_quotes_in_args(monkeypatch):
    captured = {}

    def fake_run_powershell(script, timeout=None):
        captured["script"] = script
        return ShellResult(0, stdout="EXITCODE:0\n")

    monkeypatch.setattr(shell, "run_powershell", fake_run_powershell)
    shell.run_elevated("taskkill.exe", ["/PID", "Bob's PID"])
    assert "Bob''s PID" in captured["script"]


def test_start_scheduled_task_escapes_task_name(monkeypatch):
    captured = {}

    def fake_run_powershell(script, timeout=None):
        captured["script"] = script
        return ShellResult(0)

    monkeypatch.setattr(shell, "run_powershell", fake_run_powershell)
    shell.start_scheduled_task("Bob's WebUI Task")
    assert "Bob''s WebUI Task" in captured["script"]


def test_run_elevated_distinguishes_timeout_from_generic_failure(monkeypatch):
    monkeypatch.setattr(
        shell, "run_powershell", lambda script, timeout=None: ShellResult(-1, timed_out=True)
    )
    result = shell.run_elevated("taskkill.exe", ["/F", "/PID", "123"])
    assert result.timed_out
    assert not result.elevation_denied
    assert not result.success
