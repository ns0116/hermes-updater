"""TkinterによるGUIアプリケーション (FR-5, FR-6)。"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from pathlib import Path
from typing import Optional

from hermes_updater import config as config_module
from hermes_updater.app import UpdaterApp
from hermes_updater.logger import get_logger
from hermes_updater.notifier import describe_step

log = get_logger("gui")


class UpdaterGUI:
    def __init__(self, root: tk.Tk, app: UpdaterApp):
        self.root = root
        self.app = app
        self.queue: queue.Queue = queue.Queue()
        self.apply_thread: Optional[threading.Thread] = None
        self.check_thread: Optional[threading.Thread] = None
        self.total_steps = 0
        self.current_step = 0

        self.setup_window()
        self.build_ui()
        self.start_queue_poller()

        # 初回のステータス反映
        self.update_status()

    def setup_window(self) -> None:
        self.root.title("Hermes Updater")
        self.root.geometry("540x500")
        self.root.resizable(False, False)

        # モダンなダーク調のカラーパレット
        self.bg_color = "#1E1E1E"
        self.fg_color = "#E0E0E0"
        self.accent_color = "#4A90D9"
        self.card_bg = "#2D2D2D"
        self.border_color = "#3D3D3D"

        self.root.configure(bg=self.bg_color)

        # スタイルの定義
        self.style = ttk.Style()
        self.style.theme_use("clam")

        self.style.configure(".", background=self.bg_color, foreground=self.fg_color)
        self.style.configure("TFrame", background=self.bg_color)
        self.style.configure("Card.TFrame", background=self.card_bg, borderwidth=1, relief="solid")

        # ラベルのスタイル
        self.style.configure("TLabel", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"), foreground="#FFFFFF")
        self.style.configure("Status.TLabel", font=("Segoe UI", 11, "bold"))
        self.style.configure(
            "CardHeader.TLabel", background=self.card_bg, font=("Segoe UI", 11, "bold"), foreground="#FFFFFF"
        )
        self.style.configure("CardBody.TLabel", background=self.card_bg, font=("Segoe UI", 10))

        # ボタンのスタイル
        self.style.configure("TButton", font=("Segoe UI", 10), padding=6, width=12)
        self.style.configure(
            "Primary.TButton", font=("Segoe UI", 10, "bold"), background=self.accent_color, foreground="#FFFFFF"
        )
        self.style.map("Primary.TButton", background=[("active", "#357ABD"), ("pressed", "#2A6295")])

        # プログレスバーのスタイル
        self.style.configure("TProgressbar", thickness=15, troughcolor=self.card_bg, background=self.accent_color)

        # ウィンドウを閉じるボタンのアクションをオーバーライド（トレイ常駐のため非表示化するだけ）
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

    def build_ui(self) -> None:
        # メインコンテナ
        main_frame = ttk.Frame(self.root, padding=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ヘッダー (タイトル & ステータス)
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 15))

        ttk.Label(header_frame, text="Hermes Updater", style="Header.TLabel").pack(anchor=tk.W)
        self.status_label = ttk.Label(
            header_frame, text="更新情報を取得中...", style="Status.TLabel", foreground=self.accent_color
        )
        self.status_label.pack(anchor=tk.W, pady=(5, 0))

        # 情報カードエリア (Agent & WebUI の状態表示)
        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=(0, 15))

        # Agent Card
        self.agent_card = ttk.Frame(info_frame, style="Card.TFrame", padding=10)
        self.agent_card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        ttk.Label(self.agent_card, text="Hermes Agent", style="CardHeader.TLabel").pack(anchor=tk.W)
        self.agent_desc_label = ttk.Label(self.agent_card, text="-", style="CardBody.TLabel")
        self.agent_desc_label.pack(anchor=tk.W, pady=(5, 0))

        # WebUI Card
        self.webui_card = ttk.Frame(info_frame, style="Card.TFrame", padding=10)
        self.webui_card.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        ttk.Label(self.webui_card, text="Hermes WebUI", style="CardHeader.TLabel").pack(anchor=tk.W)
        self.webui_desc_label = ttk.Label(self.webui_card, text="-", style="CardBody.TLabel")
        self.webui_desc_label.pack(anchor=tk.W, pady=(5, 0))

        # 進捗表示エリア (適用時のみ動作)
        self.progress_frame = ttk.Frame(main_frame)
        self.progress_frame.pack(fill=tk.X, pady=(0, 15))

        self.progress_var = tk.DoubleVar()
        self.progressbar = ttk.Progressbar(
            self.progress_frame, variable=self.progress_var, maximum=100, mode="determinate"
        )
        self.progressbar.pack(fill=tk.X, pady=(0, 5))

        self.progress_detail_label = ttk.Label(self.progress_frame, text="準備完了", font=("Segoe UI", 9))
        self.progress_detail_label.pack(anchor=tk.W)

        # 詳細ログエリア (テキストボックス)
        log_frame = ttk.Frame(main_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))

        # スクロールバー付きの読み取り専用テキスト
        self.log_text = tk.Text(
            log_frame,
            height=8,
            bg="#121212",
            fg="#B0B0B0",
            insertbackground="#FFFFFF",
            font=("Consolas", 9),
            relief="solid",
            bd=1,
            state=tk.DISABLED,
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)

        # 操作エリア (ボタン群)
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X)

        self.check_btn = ttk.Button(btn_frame, text="更新チェック", command=self.trigger_check)
        self.check_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.apply_btn = ttk.Button(
            btn_frame, text="更新を適用", style="Primary.TButton", command=self.trigger_apply
        )
        self.apply_btn.pack(side=tk.LEFT, padx=(0, 5))

        # 右側の補助ボタン
        self.log_dir_btn = ttk.Button(btn_frame, text="ログを開く", command=self.open_logs)
        self.log_dir_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.open_hermes_btn = ttk.Button(btn_frame, text="Hermesを開く", command=self.open_hermes)
        self.open_hermes_btn.pack(side=tk.RIGHT, padx=(5, 0))

    def write_log(self, message: str) -> None:
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def clear_log(self) -> None:
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def start_queue_poller(self) -> None:
        def poll() -> None:
            try:
                while True:
                    event_type, data = self.queue.get_nowait()
                    self.handle_queue_event(event_type, data)
                    self.queue.task_done()
            except queue.Empty:
                pass
            self.root.after(100, poll)

        self.root.after(100, poll)

    def handle_queue_event(self, event_type: str, data: any) -> None:
        if event_type == "status_update":
            self.update_status()
        elif event_type == "log":
            self.write_log(data)
        elif event_type == "check_start":
            self.check_btn.config(state=tk.DISABLED)
            self.apply_btn.config(state=tk.DISABLED)
            self.status_label.config(text="更新をチェック中...", foreground=self.accent_color)
            self.write_log("[INFO] 更新チェックを開始しました。")
        elif event_type == "check_complete":
            self.check_btn.config(state=tk.NORMAL)
            self.apply_btn.config(state=tk.NORMAL)
            self.update_status()
            self.write_log("[INFO] 更新チェックが完了しました。")
        elif event_type == "apply_start":
            targets = data
            self.total_steps = 0
            if "webui" in targets:
                # WebUIはAPI経由なら1ステップだが、フォールバックに入ると最大4ステップ。
                # ここでは最大ステップ数の4を見積もる。
                self.total_steps += 4
            if "agent" in targets:
                self.total_steps += 6

            self.current_step = 0
            self.progress_var.set(0)
            self.check_btn.config(state=tk.DISABLED)
            self.apply_btn.config(state=tk.DISABLED)
            self.status_label.config(text="更新を適用中...", foreground="#8E44AD")
            self.progress_detail_label.config(text="更新適用を開始します。")
            self.clear_log()
            self.write_log(f"[INFO] 更新適用を開始しました。対象: {', '.join(targets)}")
        elif event_type == "apply_step":
            target, step = data
            self.current_step += 1
            step_desc = describe_step(step.name)
            status_str = "成功" if step.success else "失敗"

            # 詳細情報を整形してログへ
            self.write_log(f"[{target}] {step_desc} ... {status_str}")
            if step.detail:
                self.write_log(f"  詳細: {step.detail.strip()}")

            self.progress_detail_label.config(text=f"[{target}] {step_desc}...")

            # プログレスバーの更新
            if self.total_steps > 0:
                pct = min(100.0, (self.current_step / self.total_steps) * 100.0)
                self.progress_var.set(pct)
        elif event_type == "apply_complete":
            results = data
            self.check_btn.config(state=tk.NORMAL)
            self.apply_btn.config(state=tk.NORMAL)
            self.progress_var.set(100)

            all_succeeded = all(r.success for r in results.values()) if results else False
            if all_succeeded:
                self.status_label.config(text="更新が正常に完了しました！", foreground="#2ECC71")
                self.progress_detail_label.config(text="すべての更新が完了しました。")
                self.write_log("[INFO] すべての更新が正常に適用されました。")
            else:
                self.status_label.config(text="一部の更新に失敗しました", foreground="#E74C3C")
                self.progress_detail_label.config(text="更新適用が中断または失敗しました。")
                self.write_log("[ERROR] 更新の適用中にエラーが発生しました。")

            # 最新のステータスに更新
            self.update_status()

    def update_status(self) -> None:
        r = self.app.state.last_check_result

        # Agentの表示
        if r.undetermined:
            agent_text = "状態: 判定不能\n(venv破損等の可能性)"
            webui_text = "状態: 判定不能"
            self.status_label.config(text="状態を判定できませんでした", foreground="#E74C3C")
            self.apply_btn.config(state=tk.DISABLED)
        else:
            if r.agent_behind > 0:
                agent_text = f"状態: 更新あり\n({r.agent_behind} コミット遅れ)"
            else:
                agent_text = "状態: 最新です\n(更新はありません)"

            if r.webui_behind > 0:
                webui_text = f"状態: 更新あり\n({r.webui_behind} コミット遅れ)"
            else:
                webui_text = "状態: 最新です\n(更新はありません)"

            if r.has_update:
                self.status_label.config(text="アップデートが利用可能です", foreground="#F39C12")
                self.apply_btn.config(state=tk.NORMAL)
            else:
                self.status_label.config(text="システムは最新状態です", foreground="#2ECC71")
                self.apply_btn.config(state=tk.DISABLED)

        self.agent_desc_label.config(text=agent_text)
        self.webui_desc_label.config(text=webui_text)

    def trigger_check(self) -> None:
        if self.check_thread and self.check_thread.is_alive():
            return

        def _run() -> None:
            self.queue.put(("check_start", None))
            try:
                self.app.check_now()
            except Exception as e:
                self.queue.put(("log", f"[ERROR] チェック中に例外が発生しました: {e}"))
            finally:
                self.queue.put(("check_complete", None))

        self.check_thread = threading.Thread(target=_run, daemon=True)
        self.check_thread.start()

    def trigger_apply(self) -> None:
        if self.apply_thread and self.apply_thread.is_alive():
            return

        r = self.app.state.last_check_result
        targets = []
        if r.webui_behind > 0:
            targets.append("webui")
        if r.agent_behind > 0:
            targets.append("agent")

        if not targets:
            # 念のため両方を対象にする
            targets = ["webui", "agent"]

        def _run() -> None:
            self.queue.put(("apply_start", targets))

            # コールバックの一時的な差し替え（進捗イベントをキューに流すため）
            orig_on_apply_step = self.app.on_apply_step
            self.app.on_apply_step = lambda target, step: self.queue.put(("apply_step", (target, step)))

            try:
                results = self.app.apply_now(targets)
                self.queue.put(("apply_complete", results))
            except Exception as e:
                self.queue.put(("log", f"[ERROR] 適用中に例外が発生しました: {e}"))
                self.queue.put(("apply_complete", {}))
            finally:
                # コールバックを戻す
                self.app.on_apply_step = orig_on_apply_step

        self.apply_thread = threading.Thread(target=_run, daemon=True)
        self.apply_thread.start()

    def open_logs(self) -> None:
        try:
            os.startfile(config_module.get_logs_dir(self.app.base_dir))
        except Exception as e:
            messagebox.showerror("エラー", f"ログディレクトリを開けませんでした: {e}")

    def open_hermes(self) -> None:
        install_path = Path(self.app.config.hermes_install_path)
        desktop_exe = install_path / "hermes-agent" / "apps" / "desktop" / "release" / "win-unpacked" / "Hermes.exe"
        if desktop_exe.exists():
            try:
                os.startfile(desktop_exe)
                return
            except Exception as e:
                log.warning("Failed to start desktop app executable: %s", e)

        app_data_roaming = os.environ.get("APPDATA")
        if app_data_roaming:
            shortcut_path = Path(app_data_roaming) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Hermes.lnk"
            if shortcut_path.exists():
                try:
                    os.startfile(shortcut_path)
                    return
                except Exception as e:
                    log.warning("Failed to start desktop app shortcut: %s", e)

        try:
            import webbrowser

            webbrowser.open(self.app.config.webui_base_url)
        except Exception as e:
            messagebox.showerror("エラー", f"Hermesを開けませんでした: {e}")
