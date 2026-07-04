"""pystrayトレイアイコン・右クリックメニュー (FR-5)。"""

from __future__ import annotations

import os
import threading

import pystray
from PIL import Image, ImageDraw

from hermes_updater import config as config_module
from hermes_updater import notifier
from hermes_updater.app import UpdaterApp
from hermes_updater.logger import get_logger
from hermes_updater.models import CheckResult

log = get_logger("ui")

_COLOR_IDLE = "#4A90D9"
_COLOR_PENDING = "#E0A030"
_COLOR_ATTENTION = "#D9534F"


def _build_icon_image(color: str) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=color)
    draw.text((size // 2 - 6, size // 2 - 10), "H", fill="white")
    return img


# 状態は「通常」「更新あり」「要確認(判定不能)」の3種類のみなので、切替のたびに
# 再描画せず起動時に1度だけ生成して使い回す。
_ICON_IDLE = _build_icon_image(_COLOR_IDLE)
_ICON_PENDING = _build_icon_image(_COLOR_PENDING)
_ICON_ATTENTION = _build_icon_image(_COLOR_ATTENTION)


def run_tray_app(app: UpdaterApp) -> None:
    """トレイアイコンを表示し、メインスレッドをブロックする(Windowsではメインスレッド必須)。"""
    icon: pystray.Icon

    def on_update_available(result: CheckResult) -> None:
        notifier.notify_update_available(result)
        icon.icon = _ICON_PENDING if result.has_update else _ICON_IDLE

    def on_check_undetermined(result: CheckResult) -> None:
        notifier.notify_check_undetermined(result)
        icon.icon = _ICON_ATTENTION

    app.on_update_available = on_update_available
    app.on_check_undetermined = on_check_undetermined

    def check_now_action(icon, item):
        threading.Thread(target=app.check_now, daemon=True).start()

    def make_apply_action(targets: list[str]):
        def _action(icon, item):
            def _run():
                results = app.apply_now(targets)
                for name, result in results.items():
                    notifier.notify_apply_result(name, result.success, result.aborted_reason)
                if results and all(r.success for r in results.values()):
                    icon.icon = _ICON_IDLE
            threading.Thread(target=_run, daemon=True).start()
        return _action

    def show_status(icon, item):
        r = app.state.last_check_result
        message = f"Agent: {r.agent_behind}件 / WebUI: {r.webui_behind}件\n取得経路: {r.source}"
        notifier.notify("Hermes Updater - 状態", message)

    def open_logs(icon, item):
        os.startfile(config_module.get_logs_dir(app.base_dir))  # type: ignore[attr-defined]

    def open_config(icon, item):
        os.startfile(config_module.get_config_path(app.base_dir))  # type: ignore[attr-defined]

    def reload_config_action(icon, item):
        app.reload_config()
        notifier.notify("Hermes Updater", "設定を再読み込みしました")

    def quit_action(icon, item):
        app.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("今すぐチェック", check_now_action),
        pystray.MenuItem("状態を表示", show_status),
        pystray.MenuItem(
            "更新を適用",
            pystray.Menu(
                pystray.MenuItem("WebUIのみ", make_apply_action(["webui"])),
                pystray.MenuItem("Agentのみ", make_apply_action(["agent"])),
                pystray.MenuItem("両方", make_apply_action(["webui", "agent"])),
            ),
        ),
        pystray.MenuItem("ログを開く", open_logs),
        pystray.MenuItem("設定を開く", open_config),
        pystray.MenuItem("設定を再読み込み", reload_config_action),
        pystray.MenuItem("終了", quit_action),
    )

    initial_icon = _ICON_PENDING if app.state.pending_update else _ICON_IDLE
    icon = pystray.Icon("hermes_updater", initial_icon, "Hermes Updater", menu)

    app.start_background()
    icon.run()
