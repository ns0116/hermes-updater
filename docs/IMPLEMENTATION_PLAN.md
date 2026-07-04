# Hermes Updater — 実装計画書

- 作成日: 2026-07-05
- 対応PRD: [`PRD.md`](./PRD.md)

## 1. アーキテクチャ概要

Windowsシステムトレイに常駐するPythonアプリケーション。構成要素は以下の4つ：

- **トレイUI**: `pystray`によるアイコン・右クリックメニュー
- **通知**: Windowsネイティブトースト通知ライブラリ（候補: `win11toast` / `windows-toasts`。`win10toast`は保守状況が不安定なため実装時に再評価 — PRD 8節参照）
- **更新ロジック**: `subprocess`経由で`hermes` CLI・`git`・PowerShell（`taskkill`/`Start-ScheduledTask`）を呼び出す
- **バックグラウンドスケジューラ**: 別スレッドでチェック間隔タイマーを回す

外部システム（Hermes Agent本体・hermes-webui）には一切コードレベルで手を入れず、常に**コマンドライン経由**で操作する。

## 2. ランタイム分離の方針（最重要design decision）

**本アプリの実行環境はHermes Agentのvenvと完全に独立させる。**

- 理由: 本アプリの役目は「Hermes Agentのvenvが壊れていても気づいて直す」ことなので、同じvenvに同居すると today起きたのと同じ理由で共倒れするリスクがある
- ソースコード: このリポジトリ自体（バージョン管理下）
- 実行環境: `C:\Users\<username>\AppData\Local\HermesUpdater\venv`（`uv`で作成する専用venv。hermes-agentのvenvには一切パッケージを追加しない）
- 設定・状態・ログ: `C:\Users\<username>\AppData\Local\HermesUpdater\`配下（`config.json`/`state.json`/`logs/`）

## 2.1 hermes-webui既存APIとの関係（2026-07-05調査で追加）

`hermes-webui`自体に、以下の作り込まれた自己更新機能が既に存在することが判明した（`api/updates.py`ほか）:

- `GET/POST /api/updates/check` — WebUI/Agent双方の更新有無を30分キャッシュ付きで返す
- `POST /api/updates/apply` — `git stash`→`git pull --ff-only`→`git stash pop`。アクティブなストリーム/実行中セッションがあればブロックする安全機構あり
- `POST /api/updates/force` — dirty/diverged状態向けの`git checkout .`→`git clean -fd`→`git reset --hard`
- 適用後、バックグラウンドスレッドで自分自身を再起動する（Windowsでは`DETACHED_PROCESS`で新プロセスをspawnし旧プロセスは`os._exit(0)`。タスクスケジューラ側は`--foreground`モードの仕様上どのみち実プロセスを追跡していないため、この自己再起動はタスクスケジューラと独立に機能する）
- Agent側更新成功時は`hermes gateway restart`を呼んでGatewayとの整合も取る

**本アプリでの活用方針**:

| 対象 | チェック | 適用 |
|---|---|---|
| WebUI自身 | `GET http://127.0.0.1:8788/api/updates/check`を優先。応答不能ならフォールバックで`git fetch`＋`rev-list --count`（4節参照） | `POST /api/updates/apply`を優先呼び出し（stash/pop・競合検知・自己再起動まで内蔵、`Start-ScheduledTask`での手動再起動が不要になる）。WebUIが応答不能／API呼び出し自体が失敗した場合のみ、本アプリの手動フォールバック（git pull --ff-only ＋ タスク再起動、5節参照）を使う |
| Agent | 同じく`GET /api/updates/check`の結果（`agent_behind`相当）をチェックには使ってよい（軽量・キャッシュ済みのため） | **必ず`hermes update --yes` CLIを経由する**。WebUIの`/api/updates/apply`をAgent側に使わない — WebUIの適用ロジックは`git stash/pull/pop`レベルの処理に留まり、`hermes update`が行うuv依存関係同期・Node/npmビルド・スキル同期・config移行・Windows版Gatewayの一時停止/再開までは代替しない可能性が高い。ここを省略すると、今回のセッションで修正した「コードだけ新しく依存関係が同期されていない」ドリフトを自ら再現しかねない |

**設計上の帰結**:
- WebUIのプロセスをkillする前に、可能であればWebUIの「アクティブなストリーム/実行中セッション」を尊重する配慮を`shell.py`に組み込む余地を残す（v0.1では必須要件にはしないが、`updater.py`のフックポイントとして設計しておく）
- `shell.py`のプロセス起動パターン（Windowsで子プロセスをdetachして親を終了する）は、hermes-webuiの自己再起動実装を参考にできる

## 3. ディレクトリ構成

```
hermes-updater\ (このリポジトリ)                [ソース]
├── pyproject.toml
├── src/hermes_updater/
│   ├── __main__.py      # エントリポイント
│   ├── app.py           # ライフサイクル・スケジューラ
│   ├── updater.py       # 更新チェック・適用シーケンス（Phase 16実装）
│   ├── ui.py            # pystrayトレイアイコン・メニュー
│   ├── notifier.py      # トースト通知
│   ├── shell.py         # subprocessラッパー・UAC昇格・PIDトポート特定
│   ├── config.py        # config.json / state.json 読み書き
│   ├── logger.py         # ローテーションログ設定
│   └── models.py         # CheckResult / UpdateConfig 等のデータモデル
├── tests/
└── install/
    ├── create-scheduled-task.ps1   # ログオントリガーのタスク登録
    └── uninstall.ps1

C:\Users\<username>\AppData\Local\HermesUpdater\   [実行時データ]
├── venv/
├── config.json
├── state.json
└── logs/updater.log(.1〜.5)
```

## 4. 更新チェックロジック

- `state.json`に`last_check_ts`を保持し、`config.json`の`check_interval_hours`（既定24）未満ならキャッシュ結果を返す
- **優先経路（WebUI API）**: まず`GET http://127.0.0.1:8788/api/updates/check`を試す（タイムアウト短め、例5秒）。成功すればWebUI/Agent双方の`behind`件数をここから取得する（WebUI自身が30分キャッシュしているため、本アプリ側は軽量に済む）
- **フォールバック経路（WebUIが応答不能な場合。venv破損時など、本来最も検知したいケース）**:
  - **Hermes Agent側**: `hermes update --check`の標準出力をパースする
    - `"Up to date"` → 0件
    - `"Update available: N commit(s) behind"` → N件（正規表現でN抽出）
    - 上記どちらにも一致しない場合は「判定不能」として扱い、venv破損等の異常系として別途通知する（PRD FR系の「venvが壊れていてもチェック自体は動く」ことの担保）
    - ⚠️ 実装着手時に実機で`hermes update --check`の出力を再確認してからパーサーを確定するスパイクタスクを最初に行う（PRD 8節）
  - **Hermes WebUI側**: `git -C <hermes-webui-path> fetch`→`git -C <hermes-webui-path> rev-list --count HEAD..origin/master`（ブランチ名は現状`master`。Phase 16実績値）
- 両者の結果を`CheckResult`としてまとめ、`state.json`に保存。1件以上あればトースト通知（同一のpending状態に対して通知は1回のみ、チェックの度に再通知しない）
- `CheckResult`には取得経路（`source: "webui_api" | "fallback_cli"`）を記録し、ログ・状態表示で「どちらの経路で判定したか」を追えるようにする（フォールバックが発生していること自体がvenv/WebUI異常のシグナルになるため）

## 5. 更新適用シーケンス（確定仕様）

ユーザーがトレイメニューの「更新を適用」を選ぶか、通知から承認した場合に、対象ごとに以下を実行する。各ステップの成否・出力をログに記録する。

### 5.1 WebUI自身の更新（API優先）

1. `POST http://127.0.0.1:8788/api/updates/apply`を呼び出す（タイムアウト目安60秒。内部でstash→pull→stash pop、競合検知、アクティブセッションのブロック判定、成功時の自己再起動まで完結する）
2. レスポンスが「アクティブなストリーム/実行中セッションによりブロック」を示す場合は、シーケンスをここで中断しログに記録する（ユーザーに「使用中のため後で再試行してください」と伝える。強制終了はしない）
3. レスポンスがconflict/dirtyを示す場合は警告としてログに残し、Agent側更新の実行は継続する（部分成功を許容）
4. APIコール自体がタイムアウト・接続拒否等で失敗した場合（WebUIが応答不能＝異常時）のみ、以下の手動フォールバックを行う:
   - `Get-NetTCPConnection -LocalPort 8788`でPIDを特定→UAC昇格`taskkill /F /T /PID <pid>`で停止（PID未検出ならスキップ）
   - `git -C <hermes-webui-path> pull --ff-only`（fast-forward不可なら警告に留める — PRD FR-10）
   - `Start-ScheduledTask -TaskName "HermesWebUI-Native-Start"`で再起動
   - `GET http://127.0.0.1:8788/health`が200になることを確認（数秒のリトライ猶予）

### 5.2 Agentの更新（`hermes update` CLI経由、固定手順）

WebUIのAPIは使わず、Phase 16で実証した手順を確定仕様として実行する。WebUIプロセスは同じvenvのPythonを使っているため、Agent更新の前に必ず一時停止させる（5.1のWebUI更新とは独立して、Agent更新のたびに毎回必要）。

1. `hermes gateway stop`
   - `hermes update`自体がWindows版Gatewayの停止・再開を内部で自動処理するため本質的には不要だが、明示的に呼んでも副作用がないため保険的に実行する
2. WebUIプロセスの停止
   - `Get-NetTCPConnection -LocalPort 8788`でOwningProcessのPIDを取得
   - PIDが見つからない場合（WebUI未起動）はこのステップをスキップして次へ進む
   - PIDが見つかった場合、UAC昇格した`taskkill /F /T /PID <pid>`で停止する（`Stop-ScheduledTask`だけでは実プロセスは止まらない — Phase 14で実証済み）
   - 可能であれば、事前に`GET /api/updates/check`のレスポンスやWebUIのアクティブセッション有無を確認し、使用中であればユーザーに一声かけてから停止する配慮を将来的に組み込む余地を残す（v0.1では必須要件にはしない）
   - **UACをユーザーが拒否した場合**: シーケンスをここで中断し、`pending_update`フラグを維持したままログに記録して終了（自動リトライしない）
3. `hermes update --yes`を実行（タイムアウト目安300秒）
   - 終了コードが非0、または既知の失敗文言を検出した場合は失敗として記録し、シーケンスを中断する（WebUIは5で必ず再起動するため、失敗時もWebUI停止状態のまま放置しない）
4. `hermes version`の出力に`"Up to date"`が含まれることを確認する
5. `Start-ScheduledTask -TaskName "HermesWebUI-Native-Start"`でWebUIを再起動
6. `GET http://127.0.0.1:8788/health`が200を返すことを確認する（数秒のリトライ猶予を設ける）

**方針**: どのステップで失敗しても、必ずWebUIを起動した状態に戻すことを最優先する（失敗したまま停止状態で放置しない）。自動リトライは行わず、失敗はログ＋トースト通知でユーザーに伝え、次の操作はユーザー起点とする。WebUI・Agentそれぞれの更新は独立して実行可能だが、両方更新する場合は5.1→5.2の順（先にWebUI自身を軽量に更新してから、Agent更新のために止める）を推奨する。

## 6. 設定・状態ファイル

`config.json`（初回起動時にデフォルト生成、ユーザーが直接編集可能）:
```json
{
  "check_interval_hours": 24,
  "check_on_startup": true,
  "enable_notifications": true,
  "hermes_install_path": "C:\\Users\\<username>\\AppData\\Local\\hermes",
  "hermes_webui_path": "C:\\Users\\<username>\\AppData\\Local\\hermes\\hermes-webui"
}
```

`state.json`（アプリが自動管理、ユーザーは編集しない前提）:
```json
{
  "last_check_ts": 0,
  "last_check_result": {"agent_behind": 0, "webui_behind": 0},
  "pending_update": false,
  "last_update_ts": 0,
  "last_update_success": null,
  "last_error": null
}
```

## 7. ログ設計

- `logging.handlers.RotatingFileHandler`で`logs/updater.log`に出力（5MB×5世代）
- フォーマット: `[YYYY-MM-DD HH:MM:SS] [LEVEL] [module] message`
- チェック開始・各ステップの開始/終了/成否・通知送信・エラー詳細をすべて記録する

## 8. 自動起動（タスクスケジューラ登録）

既存のGateway/WebUI起動タスク（`S4U`ログオン＋起動時トリガー、非対話セッション）とは**異なる方式**が必要:

- トリガー: ログオン時（`New-ScheduledTaskTrigger -AtLogOn`）
- 実行ユーザー: 現在の対話的ユーザー（`LogonType Interactive`）— トレイアイコンをデスクトップに表示する必要があるため
- 実行コマンド: `<HermesUpdater venv>\Scripts\pythonw.exe -m hermes_updater`（コンソールウィンドウを出さない`pythonw.exe`を使用）
- `install/create-scheduled-task.ps1`にこの登録処理をまとめる（初回セットアップ時にUAC昇格で1回実行）

## 9. エラーハンドリング一覧

| シナリオ | 検知方法 | 対応 |
|---|---|---|
| `hermes update`失敗 | 終了コード非0 | ログにERROR記録、WebUIは必ず再起動（手順4の前で中断していてもWebUI再起動だけは試みる）、`pending_update`維持 |
| WebUI `POST /api/updates/apply`がアクティブセッションでブロック | レスポンスの`restart_blocked`相当のフィールド | シーケンス中断、ログにINFO記録、ユーザーに「使用中のため後で」と通知。強制終了はしない |
| WebUI `POST /api/updates/apply`がconflict/dirtyを報告 | レスポンスのconflict系フィールド | WARNINGとして記録、Agent更新の実行は継続する |
| WebUI API自体が応答不能（接続拒否・タイムアウト） | HTTPリクエスト例外 | 手動フォールバック（git pull＋タスク再起動）に切り替え、フォールバックを使ったこと自体をWARNINGとしてログ記録（venv/WebUI異常の兆候として扱う） |
| WebUIの手動`git pull`が非fast-forward（フォールバック経路） | git出力にconflict/divergeの兆候 | WARNINGとして記録、Agent更新の成功扱いは変えない |
| WebUIプロセスをkillできない（Agent更新の準備段階） | `taskkill`終了コード非0 | ERROR記録、シーケンス中断、ユーザーに手動対応を促すログメッセージ |
| UACをユーザーが拒否 | 昇格プロセス起動が拒否コードを返す | シーケンスを該当ステップで中断、`pending_update`維持、自動リトライなし |
| hermes-agentのvenv自体が壊れている | `hermes update --check`/`hermes version`が異常終了・想定外出力（WebUI API自体も応答不能なことが多い） | 「チェック失敗、venvが壊れている可能性」を通知・ログに記録し、そのまま`hermes update --yes`を試す選択肢をユーザーに提示（venv再構築自体は`hermes update`の役割に委ねる） |
| ポート8788が未使用（WebUI未起動） | PID取得結果が空 | killステップをスキップして続行 |
| WebUI再起動タスクが失敗 | `Start-ScheduledTask`終了コード非0、または直後の`/health`が非200 | ERROR記録、通知で明示 |

**共通方針**: 自動リトライは行わない。失敗は必ずログ＋（設定でONの場合）トースト通知に残し、次の実行はユーザー操作を起点とする。

## 10. 段階的な実装順序

1. **コア基盤**: `models.py`/`config.py`/`logger.py`/`shell.py`（subprocessラッパー、UAC昇格、ポート→PID特定、HTTPヘルスチェック）。CLIから単体で動作確認できる状態にする
2. **更新ランナー**: `updater.py`（チェックロジック＋Phase 16適用シーケンス）。まずCLI経由（`python -m hermes_updater --check` / `--apply`）で動作確認
3. **バックグラウンドスケジューラ**: `app.py`にチェック間隔タイマーと状態永続化を実装。ヘッドレス（トレイなし）でも動作確認できる状態にする
4. **トレイUI・通知**: `ui.py`/`notifier.py`を実装し、`__main__.py`から起動する完全版トレイアプリにする
5. **インストーラ**: `install/create-scheduled-task.ps1`（venv作成＋タスク登録）と`uninstall.ps1`
6. **結合テスト・手動検証**: 下記11節のシナリオを実施

## 11. 検証シナリオ（受け入れテスト）

実装完了後、以下を手動またはモックで検証する:

1. **通常更新フロー（Agent）**: 更新ありの状態を用意し、チェック→通知→承認→全ステップ成功→`hermes version`が"Up to date"、WebUI `/health`が200になることを確認
2. **WebUIロック状態からの復旧（Agent更新時）**: WebUI起動中に更新を適用し、`taskkill`→`hermes update`が今回のセッションで実証した通り成功することを確認
3. **WebUI自身の更新（API経路）**: `hermes-webui`に新規コミットがある状態で「更新を適用」を実行し、`POST /api/updates/apply`が呼ばれて自己再起動まで完了し、手動フォールバック（git pull/taskkill）が使われないことを確認
4. **WebUI API応答不能時のフォールバック**: WebUIプロセスを事前に落とした状態でWebUI更新を試み、フォールバック経路（手動git pull＋タスク再起動）に切り替わることを確認
5. **UAC拒否時の挙動**: 昇格プロンプトで「いいえ」を選び、シーケンスが安全に中断し`pending_update`が維持されることを確認
6. **hermes-agent venv破損時の検知**: 意図的にvenvを壊した状態でチェックを実行し、異常検知・通知が機能することを確認（WebUI API経路もフォールバックに落ちることを合わせて確認）
7. **WebUI git diverge時の部分成功**: `hermes-webui`をdivergeさせた状態で更新し、Agentは更新されWebUI側は警告に留まることを確認
8. **タスクスケジューラ登録確認**: インストーラ実行後、`Get-ScheduledTask`でログオントリガー・対話的ログオンとして登録されていること、実際にログオン後トレイアイコンが表示されることを確認

## 12. 将来拡張（v0.1スコープ外、設計上は考慮のみ）

- 完全自動適用オプション（`auto_apply_updates`設定フラグ、UI追加は不要でconfig.jsonのみで有効化できる設計に留める）
- 更新前バックアップ（`hermes update`のpre-update backup機能を活用）からのロールバックUI
- 複数プロファイル・複数ユーザー対応
- 外部通知連携（Discord/Slack等）
