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


def _load_and_build_status_icons(app: UpdaterApp) -> tuple[Image.Image, Image.Image, Image.Image]:
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
                log.info(f"Loaded official hermes-agent icon from: {path}")
                break
        except Exception as e:
            log.warning(f"Failed to load icon from {path}: {e}")
            
    if base_img is None:
        log.warning("No official hermes-agent icon found. Falling back to dynamically generated icons.")
        return (
            _build_fallback_icon(_COLOR_IDLE),
            _build_fallback_icon(_COLOR_PENDING),
            _build_fallback_icon(_COLOR_ATTENTION),
        )
        
    # トレイアイコンの標準サイズにリサイズ
    size = 64
    base_img = base_img.resize((size, size), Image.Resampling.LANCZOS)
    
    # 3状態のアイコンを生成
    icon_idle = base_img.copy()
    _draw_status_badge(icon_idle, "#2ECC71")  # 緑バッジ
    
    icon_pending = base_img.copy()
    _draw_status_badge(icon_pending, "#F39C12")  # オレンジバッジ
    
    icon_attention = base_img.copy()
    _draw_status_badge(icon_attention, "#E74C3C")  # 赤バッジ
    
    return icon_idle, icon_pending, icon_attention


def run_tray_app(app: UpdaterApp) -> None:
    """トレイアイコンを表示し、メインスレッドをブロックする(Windowsではメインスレッド必須)。"""
    icon: pystray.Icon

    # アイコン群をビルド
    icon_idle, icon_pending, icon_attention = _load_and_build_status_icons(app)

    def on_update_available(result: CheckResult) -> None:
        notifier.notify_update_available(result)
        icon.icon = icon_pending if result.has_update else icon_idle

    def on_check_undetermined(result: CheckResult) -> None:
        notifier.notify_check_undetermined(result)
        icon.icon = icon_attention

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
                    icon.icon = icon_idle
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

    def open_app(icon, item):
        # 1. ローカルのデスクトップアプリの実行可能ファイルを起動してみる
        install_path = Path(app.config.hermes_install_path)
        desktop_exe = install_path / "hermes-agent" / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
        if desktop_exe.exists():
            try:
                os.startfile(desktop_exe)
                return
            except Exception as e:
                log.warning(f"Failed to start desktop app executable: {e}")

        # 2. スタートメニューのショートカットを起動してみる
        app_data_roaming = os.environ.get("APPDATA")
        if app_data_roaming:
            shortcut_path = Path(app_data_roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Hermes.lnk"
            if shortcut_path.exists():
                try:
                    os.startfile(shortcut_path)
                    return
                except Exception as e:
                    log.warning(f"Failed to start desktop app shortcut: {e}")

        # 3. フォールバック: WebUIをブラウザで開く
        try:
            import webbrowser
            webbrowser.open(app.config.webui_base_url)
        except Exception as e:
            log.error(f"Failed to open WebUI fallback: {e}")

    def reload_config_action(icon, item):
        app.reload_config()
        # 設定再読み込みに伴い、アイコンを再生成して適用する
        nonlocal icon_idle, icon_pending, icon_attention
        icon_idle, icon_pending, icon_attention = _load_and_build_status_icons(app)
        if app.state.last_check_result.undetermined:
            icon.icon = icon_attention
        elif app.state.pending_update:
            icon.icon = icon_pending
        else:
            icon.icon = icon_idle
        notifier.notify("Hermes Updater", "設定を再読み込みしました")

    def quit_action(icon, item):
        app.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Hermesを開く", open_app, default=True),
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

    initial_icon = icon_pending if app.state.pending_update else icon_idle
    icon = pystray.Icon("hermes_updater", initial_icon, "Hermes Updater", menu)

    app.start_background()
    icon.run()

