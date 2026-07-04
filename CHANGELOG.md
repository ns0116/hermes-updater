# Changelog

このプロジェクトの変更履歴です。[Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) の形式に緩く準拠します。

## [0.1.0] - 2026-07-05

### Added
- Hermes Agent / Hermes WebUIの更新チェック(WebUI API優先＋CLI/gitフォールバック)
- Phase16準拠の更新適用シーケンス(WebUI: API優先＋手動フォールバック、Agent: `hermes update --yes`固定)
- Windowsトースト通知(win11toast)、pystrayトレイUI(今すぐチェック/状態表示/更新を適用/ログを開く/設定を開く・再読み込み/終了)
- ローテーション付きログファイル、`config.json`/`state.json`による人間可読な状態永続化
- ログオン時自動起動インストーラ(`install/create-scheduled-task.ps1`)、アンインストーラ
- 更新有無が判定不能(venv破損等)な場合の専用通知・トレイアイコン表示
- チェック/適用シーケンスの多重実行防止(トレイメニュー連打・スケジューラとの競合対策)

### Fixed
- WebUI/Agentいずれの適用シーケンスも、途中のステップで失敗してもWebUIの再起動を必ず試みるように修正
- UAC昇格を伴うコマンドのタイムアウトを人間の応答時間を考慮して延長し、タイムアウトと拒否を区別
- config.json由来の値(タスク名等)をPowerShellコマンド文字列に埋め込む際のクォート処理を修正
- バックグラウンドスケジューラが1回の例外で永久に停止しないよう保護
- `check_interval_hours`に無効な値(0以下)が設定された場合のフォールバック
