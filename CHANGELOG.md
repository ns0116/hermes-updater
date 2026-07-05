# Changelog

このプロジェクトの変更履歴です。[Keep a Changelog](https://keepachangelog.com/ja/1.0.0/) の形式に緩く準拠します。

## [Unreleased]

### Added
- トレイアイコンを`hermes-agent`の公式ロゴ(`website/static/img/`配下から自動検出)を使った表示に変更。状態(通常/更新あり/要確認)は右下の色分けバッジ(緑/オレンジ/赤)で表現する。ロゴが見つからない場合は従来の動的生成アイコンにフォールバックする([Issue #2](https://github.com/ns0116/hermes-updater/issues/2))
- トレイアイコンのダブルクリック(既定メニュー項目「Hermesを開く」)でHermesのデスクトップアプリを起動できるように。デスクトップアプリ実行ファイル→スタートメニューショートカット→WebUIブラウザ起動、の順にフォールバックする([Issue #2](https://github.com/ns0116/hermes-updater/issues/2))

### Fixed
- 専用venvのベースインタプリタをPython 3.13(システム既定)に切り替え。従来は`uv venv --python 3.11`が`hermes-agent`のvenvと同じuvキャッシュ済みcpython-3.11ビルドを共有しており、「hermes-agentのvenvとは完全に独立」という設計意図に反していた。実機検証でこのcpython-3.11ビルド固有の不具合(`pythonw.exe`が`python.exe`と同一のコンソールサブシステムで生成され、常駐起動時にウィンドウが表示され続ける。[Issue #1](https://github.com/ns0116/hermes-updater/issues/1))も確認しており、Python 3.13への切り替えでこの不具合自体を回避した。
- `install/create-scheduled-task.ps1`に、`pythonw.exe`がGUIサブシステムでない場合の修復ロジックを(念のためのフォールバックとして)追加。venv自身の`python.exe`(動作確認済みの起動スタブ)を複製し、PEヘッダのSubsystemフィールドのみ書き換える方式。過去に試みた「ベースインストール側の実体を持つ`pythonw.exe`をそのままコピーする」方式は、隣接する`python3xx.dll`への依存により`venv\Scripts`直下では`STATUS_DLL_NOT_FOUND`で起動不能を引き起こすことが判明したため採用していない。

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
