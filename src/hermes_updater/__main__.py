"""エントリポイント。

- 引数なし: トレイ常駐アプリとして起動 (`pythonw.exe -m hermes_updater`)
- `--check`: 1回だけ更新チェックしてCLIに結果を出力(実装計画書10節: 段階的動作確認用)
- `--apply webui,agent`: 指定ターゲットの更新を適用してCLIに結果を出力
- `--status`: 現在の永続状態を表示
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from hermes_updater.app import UpdaterApp
from hermes_updater.logger import setup_logging
from hermes_updater.notifier import describe_step

# hermes CLI/WebUIの出力には✓等のUnicode記号が含まれるため、日本語Windowsのcp932コンソールでも
# 落ちないようにUTF-8+置換モードへ切り替える(subprocess側の対策はshell.pyを参照)。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# AUMID(AppUserModelID)未設定だとタスクバー設定・トースト通知の送信元表示が
# pythonw.exe起動時の既定識別情報(「Python」)にフォールバックしてしまうため、
# トレイアイコン・トースト通知を扱う前に明示設定する(GitHub Issue #3)。
if sys.platform == "win32":
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("HermesUpdater.TrayApp.1")
    except OSError:
        pass


def _print_check_result(result) -> None:
    print(f"agent_behind={result.agent_behind} webui_behind={result.webui_behind}")
    print(f"source={result.source} (agent={result.agent_source}, webui={result.webui_source})")
    if result.error:
        print(f"warnings: {result.error}")


def _print_apply_results(results: dict) -> None:
    for name, r in results.items():
        print(f"[{name}] success={r.success} aborted_reason={r.aborted_reason}")
        for step in r.steps:
            status = "OK" if step.success else "FAIL"
            detail = step.detail.strip().replace("\n", " ")[:200]
            print(f"  - {step.name}: {status} {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes_updater")
    parser.add_argument("--check", action="store_true", help="更新の有無を1回だけチェックする")
    parser.add_argument(
        "--apply", metavar="TARGETS", help="カンマ区切りで指定 (webui,agent) して更新を適用する"
    )
    parser.add_argument("--status", action="store_true", help="現在の永続状態を表示する")
    args = parser.parse_args(argv)

    setup_logging()
    app = UpdaterApp()

    if args.check:
        result = app.check_now()
        _print_check_result(result)
        return 0

    if args.apply:
        targets = [t.strip() for t in args.apply.split(",") if t.strip()]
        invalid = [t for t in targets if t not in ("webui", "agent")]
        if invalid:
            print(f"invalid targets: {invalid} (must be 'webui' or 'agent')", file=sys.stderr)
            return 2

        # Issue #9: 完了までサイレントだった適用処理に、開始・各ステップの実況を出す
        app.on_apply_start = lambda ts: print(f"更新の適用を開始します: {', '.join(ts)}")
        app.on_apply_step = lambda target, step: print(
            f"  [{target}] {describe_step(step.name)}: {'OK' if step.success else 'FAIL'}"
        )

        results = app.apply_now(targets)
        _print_apply_results(results)
        return 0 if all(r.success for r in results.values()) else 1

    if args.status:
        state = app.state
        if state.last_check_ts == 0.0:
            print("状態: まだ一度もチェックが実行されていません。")
            print("  hermes-updater --check を実行してください。")
            return 0
        ts_str = datetime.fromtimestamp(state.last_check_ts).strftime("%Y-%m-%d %H:%M:%S")
        print(f"pending_update={state.pending_update}")
        print(f"last_check={ts_str}")
        _print_check_result(state.last_check_result)
        print(f"last_update_success={state.last_update_success}")
        print(f"last_error={state.last_error}")
        return 0

    from hermes_updater import ui

    ui.run_tray_app(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
