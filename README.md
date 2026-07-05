# Hermes Updater

Hermes Agent（[hermes-agent](https://github.com/nesquena/hermes-agent) 相当のネイティブWindowsインストール）とコミュニティ製Web UI（[hermes-webui](https://github.com/nesquena/hermes-webui)）の更新を、定期チェック → トースト通知 → ユーザー承認 → 安全な手順で自動適用する、Windowsシステムトレイ常駐アプリです。

背景・要件の詳細は [`docs/PRD.md`](docs/PRD.md)、アーキテクチャの詳細は [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) を参照してください。

## 特徴

- Hermes Agent / Hermes WebUI 双方の更新有無を定期チェック(既定24時間おき)
- 更新があるときだけWindowsトースト通知(何もなければ静か)
- ユーザーが明示的に承認した場合のみ更新を適用(強制適用なし)
- WebUI自身の`/api/updates/apply`(stash→pull→pop、自己再起動まで内蔵)を優先利用し、応答不能時のみ手動フォールバック
- Agent側は必ず`hermes update --yes` CLI経由(依存関係同期・Windows版Gatewayの一時停止/再開まで含む正規の更新経路)
- 実行環境はHermes Agentのvenvと完全に独立(ベースインタプリタも別。venvが壊れていてもチェック・通知自体は動作し続ける)
- ローテーション付きログファイルに全ステップの成否を記録
- ログオン時に自動起動するタスクスケジューラ登録(インストーラ同梱)

## 動作要件

- Windows 10以降
- Python 3.11以上(インストーラ利用時は、システムにインストール済みのPython 3.13をベースに専用venvを作成する。`hermes-agent`のvenvとはベースインタプリタも含めて独立)
- `hermes` コマンドがPATHに存在すること
- `git` コマンドがPATHに存在すること
- （インストーラ利用時）[`uv`](https://docs.astral.sh/uv/)

## セットアップ

### 開発・動作確認用

```powershell
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\pytest tests/
```

### 常駐アプリとしてインストール

専用venvの作成とログオン時起動タスクの登録を行います(実インストール操作のため、内容を確認の上で実行してください)。

```powershell
# 管理者権限のPowerShellで実行(タスクスケジューラ登録にUAC昇格が必要)
.\install\create-scheduled-task.ps1
```

アンインストールする場合:

```powershell
.\install\uninstall.ps1
# 設定・状態・ログも含めて削除する場合
.\install\uninstall.ps1 -RemoveData
```

## 使い方

トレイアイコンは`hermes-agent`の公式ロゴ(`hermes_install_path`配下から自動検出)にステータスバッジを重ねて表示します: 緑=通常、オレンジ=更新あり、赤=要確認(更新有無が判定不能。venv破損等の異常系の可能性)。ロゴが見つからない場合は色分けした丸アイコンにフォールバックします。

ダブルクリック(既定のメニュー項目)でHermesのデスクトップアプリを開きます。デスクトップアプリの実行ファイルが見つからない場合はスタートメニューのショートカット、それも無ければWebUIをブラウザで開くところまでフォールバックします。

右クリックすると以下のメニューが表示されます:

| メニュー項目 | 内容 |
|---|---|
| Hermesを開く | デスクトップアプリ(→ショートカット→WebUI)を開く。ダブルクリックと同じ動作 |
| 今すぐチェック | 更新有無を即座に再チェック |
| 状態を表示 | 直近のチェック結果をトースト表示 |
| 更新を適用 | WebUIのみ / Agentのみ / 両方 から選んで適用 |
| ログを開く | ログフォルダを開く |
| 設定を開く | `config.json` を開く |
| 設定を再読み込み | エディタで編集した`config.json`をアプリ再起動なしに反映 |
| 終了 | トレイアプリを終了 |

CLIから直接実行することもできます(トレイなしのヘッドレス動作確認用):

```powershell
python -m hermes_updater --check          # 1回だけチェックして結果を表示
python -m hermes_updater --apply webui    # WebUIのみ更新を適用
python -m hermes_updater --apply agent    # Agentのみ更新を適用
python -m hermes_updater --apply webui,agent
python -m hermes_updater --status         # 現在の永続状態を表示
python -m hermes_updater                  # 引数なし: トレイ常駐アプリとして起動
```

## 設定

初回起動時に `%LOCALAPPDATA%\HermesUpdater\config.json` が自動生成されます。主な項目:

```json
{
  "check_interval_hours": 24,
  "check_on_startup": true,
  "enable_notifications": true,
  "hermes_install_path": "C:\\Users\\<username>\\AppData\\Local\\hermes",
  "hermes_webui_path": "C:\\Users\\<username>\\AppData\\Local\\hermes\\hermes-webui",
  "webui_host": "127.0.0.1",
  "webui_port": 8788,
  "webui_task_name": "HermesWebUI-Native-Start",
  "webui_branch": "master"
}
```

状態(`state.json`)とログ(`logs/updater.log`、5MB×5世代ローテーション)も同じディレクトリ配下に保存されます。

## ライセンス

[MIT](LICENSE)
