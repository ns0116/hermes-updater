"""pystrayトレイアイコン・右クリックメニュー (FR-5)。"""

from __future__ import annotations

import os
import threading
from pathlib import Path

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
_COLOR_APPLYING = "#8E44AD"


def _build_fallback_icon(color: str) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, size - 4, size - 4), fill=color)
    draw.text((size // 2 - 6, size // 2 - 10), "H", fill="white")
    return img


def _draw_status_badge(img: Image.Image, color: str) -> None:
    size = img.width
    draw = ImageDraw.Draw(img)

    # バッジのサイズとマージン
    margin = 3
    r = 10
    cx = size - r - margin
    cy = size - r - margin

    # 白い縁取りを描画してロゴ詳細からバッジを分離する
    border_color = "#FFFFFF"
    border_width = 3
    draw.ellipse(
        (cx - r - border_width, cy - r - border_width, cx + r + border_width, cy + r + border_width),
        fill=border_color
    )

    # ロゴのテイストに合わせて黒いアウトラインを描画
    outline_color = "#000000"
    draw.ellipse(
        (cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1),
        fill=outline_color
    )

    # バッジ本体を描画
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=color
    )


def _load_and_build_status_icons(app: UpdaterApp) -> tuple[Image.Image, Image.Image, Image.Image, Image.Image]:
    """ローカルの公式 hermes-agent ロゴのロードを試み、ステータスに応じたアイコン群をビルドする。"""
    install_path = Path(app.config.hermes_install_path)
    agent_img_dir = install_path / "hermes-agent" / "website" / "static" / "img"

    paths_to_try = [
        agent_img_dir / "logo.png",
        agent_img_dir / "apple-touch-icon.png",
        agent_img_dir / "favicon-32x32.png",
        agent_img_dir / "favicon.ico",
    ]

    base_img = None
    for path in paths_to_try:
        try:
            if path.exists():
                base_img = Image.open(path).convert("RGBA")
                log.info("Loaded official hermes-agent icon from: %s", path)
                break
        except Exception as e:
            log.warning("Failed to load icon from %s: %s", path, e)

    if base_img is None:
        log.warning("No official hermes-agent icon found. Falling back to dynamically generated icons.")
        return (
            _build_fallback_icon(_COLOR_IDLE),
            _build_fallback_icon(_COLOR_PENDING),
            _build_fallback_icon(_COLOR_ATTENTION),
            _build_fallback_icon(_COLOR_APPLYING),
        )

    # トレイアイコンの標準サイズにリサイズ
    size = 64
    base_img = base_img.resize((size, size), Image.Resampling.LANCZOS)

    # 4状態のアイコンを生成
    icon_idle = base_img.copy()
    _draw_status_badge(icon_idle, "#2ECC71")  # 緑バッジ

    icon_pending = base_img.copy()
    _draw_status_badge(icon_pending, "#F39C12")  # オレンジバッジ

    icon_attention = base_img.copy()
    _draw_status_badge(icon_attention, "#E74C3C")  # 赤バッジ

    # Issue #9: 更新適用中を示す専用状態(紫バッジ)
    icon_applying = base_img.copy()
    _draw_status_badge(icon_applying, _COLOR_APPLYING)

    return icon_idle, icon_pending, icon_attention, icon_applying


def run_tray_app(app: UpdaterApp) -> None:
    """トレイアイコンを表示し、tkinterのメインループを回す。"""
    import tkinter as tk
    from hermes_updater.gui import UpdaterGUI

    root = tk.Tk()
    root.withdraw()  # 初期状態ではウィンドウを非表示にする

    gui = UpdaterGUI(root, app)
    icon: pystray.Icon

    # アイコン群をビルド
    icon_idle, icon_pending, icon_attention, icon_applying = _load_and_build_status_icons(app)

    def _select_icon_for_state() -> Image.Image:
        if app.state.last_check_result.undetermined:
            return icon_attention
        elif app.state.pending_update:
            return icon_pending
        return icon_idle

    def show_gui_safe() -> None:
        root.after(0, gui.show)

    def on_update_available(result: CheckResult) -> None:
        notifier.notify_update_available(result)
        gui.queue.put(("status_update", None))

    def on_check_undetermined(result: CheckResult) -> None:
        notifier.notify_check_undetermined(result)
        gui.queue.put(("status_update", None))

    def on_check_complete(result: CheckResult) -> None:
        # 通知の要否とは無関係に、チェックのたびに必ずアイコンを最新状態へ反映する
        icon.icon = _select_icon_for_state()
        gui.queue.put(("status_update", None))

    def on_apply_start(targets: list[str]) -> None:
        # Issue #9: 適用開始が全く見えない問題への対応(専用アイコン状態 + 開始トースト)
        icon.icon = icon_applying
        icon.title = "Hermes Updater - 更新を適用中..."
        notifier.notify_apply_start(targets)
        gui.queue.put(("apply_start", targets))

    def on_apply_step(target: str, step) -> None:
        # Issue #9: 主要ステップ(WebUI停止/Agent更新/WebUI再起動)ごとの簡易進捗表示
        icon.title = f"Hermes Updater - {target}: {notifier.describe_step(step.name)}"
        gui.queue.put(("apply_step", (target, step)))

    app.on_update_available = on_update_available
    app.on_check_undetermined = on_check_undetermined
    app.on_check_complete = on_check_complete
    app.on_apply_start = on_apply_start
    app.on_apply_step = on_apply_step

    def check_now_action(icon, item):
        threading.Thread(target=app.check_now, daemon=True).start()

    def make_apply_action(targets: list[str]):
        def _action(icon, item):
            show_gui_safe()
            # GUI経由で適用プロセスを呼び出す
            root.after(0, gui.trigger_apply)
        return _action

    def show_status(icon, item):
        show_gui_safe()

    def open_logs(icon, item):
        try:
            os.startfile(config_module.get_logs_dir(app.base_dir))  # type: ignore[attr-defined]
        except OSError as e:
            log.warning("ログディレクトリを開けませんでした: %s", e)

    def open_config(icon, item):
        try:
            os.startfile(config_module.get_config_path(app.base_dir))  # type: ignore[attr-defined]
        except OSError as e:
            log.warning("設定ファイルを開けませんでした: %s", e)

    def open_app(icon, item):
        # 1. ローカルのデスクトップアプリの実行可能ファイルを起動してみる
        install_path = Path(app.config.hermes_install_path)
        desktop_exe = install_path / "hermes-agent" / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
        if desktop_exe.exists():
            try:
                os.startfile(desktop_exe)
                return
            except Exception as e:
                log.warning("Failed to start desktop app executable: %s", e)

        # 2. スタートメニューのショートカットを起動してみる
        app_data_roaming = os.environ.get("APPDATA")
        if app_data_roaming:
            shortcut_path = Path(app_data_roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Hermes.lnk"
            if shortcut_path.exists():
                try:
                    os.startfile(shortcut_path)
                    return
                except Exception as e:
                    log.warning("Failed to start desktop app shortcut: %s", e)

        # 3. フォールバック: WebUIをブラウザで開く
        try:
            import webbrowser
            webbrowser.open(app.config.webui_base_url)
        except Exception as e:
            log.error("Failed to open WebUI fallback: %s", e)

    def reload_config_action(icon, item):
        app.reload_config()
        # 設定再読み込みに伴い、アイコンを再生成して適用する
        nonlocal icon_idle, icon_pending, icon_attention, icon_applying
        icon_idle, icon_pending, icon_attention, icon_applying = _load_and_build_status_icons(app)
        icon.icon = _select_icon_for_state()
        gui.queue.put(("status_update", None))
        notifier.notify("Hermes Updater", "設定を再読み込みしました")

    def quit_action(icon, item):
        app.stop()
        icon.stop()
        root.quit()
        root.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("Hermes Updaterを開く", lambda icon, item: show_gui_safe(), default=True),
        pystray.MenuItem("公式Hermesを開く", open_app),
        pystray.MenuItem("今すぐチェック", check_now_action),
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

    initial_icon = icon_pending if app.state.pending_update else icon_idle
    icon = pystray.Icon("hermes_updater", initial_icon, "Hermes Updater", menu)

    app.start_background()
    
    # pystrayのトレイアイコンを別スレッドで実行
    threading.Thread(target=icon.run, name="hermes-updater-tray", daemon=True).start()

    # メインスレッドでtkinterメインループを実行
    root.mainloop()

