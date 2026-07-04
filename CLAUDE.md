# hermes-updater — Claude Context

> 核のみを保持。詳細は `docs/` を参照。

## 概要

Hermes Agent（`C:\Users\<username>\AppData\Local\hermes`）とコミュニティ製Web UI（`hermes-webui`）の更新を、定期チェック→トースト通知→ユーザー承認→安全な手順で自動適用する、Windowsシステムトレイ常駐アプリ。v0.1実装済み（`src/hermes_updater/`配下、pytest通過、実機での動作確認済み）。

- 要求仕様: [`docs/PRD.md`](docs/PRD.md)
- 実装計画: [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)
- 元になった手動運用の記録（Phase 14・16）: 本リポジトリ外の個人メモに基づく（詳細は`CLAUDE.local.md`参照。非公開のためリポジトリには含まれない）

## スタック

- Python 3.11+（Windows native、`hermes-agent`のvenvとは**完全に独立**した専用venv）
- `pystray`（トレイ）＋ `win11toast`（トースト通知。保守状況調査の結果採用）
- エントリポイント: `src/hermes_updater/__main__.py`（`--check`/`--apply`/`--status`のCLIモードとトレイ常駐モードの両対応）

## ガードレール

このプロジェクトはコード自体は小規模だが、**実プロセスの強制終了・スケジュールタスク登録・稼働中インストールの更新**という実害のある操作を扱うため、ガードレールを明記する。

**AUTO（確認不要）**:
- ローカルファイルの読み書き・生成、テストの実行
- git add / commit / push（このリポジトリ内のみ）
- ドキュメント（`docs/`配下）の更新

**SEMI_AUTO（ユーザーの確認後に実行）**:
- 実際に`hermes update --yes`を実行する（本物のHermes Agentインストールを変更するため）
- `taskkill`によるWebUIプロセスの強制終了、UAC昇格を伴う操作全般
- `Register-ScheduledTask`/`Start-ScheduledTask`等によるタスクスケジューラの登録・変更
- `install/create-scheduled-task.ps1`等インストーラースクリプトの実行（専用venv作成含む）
- `hermes-webui`リポジトリへの`git pull`実行（実ファイルを書き換えるため）

**禁止**:
- `hermes-agent`のvenv（`C:\Users\<username>\AppData\Local\hermes\hermes-agent\venv`）に対する`uv sync`等の直接操作（[[feedback_hermes_uv_sync]]の教訓。遅延インストール済みバックエンドとvenv内`pip`モジュールを消失させた実績あり。必ず正規の`hermes`公式CLI経由で操作する）
- `.env`・APIキー等の秘密情報を含むファイルのcommit
- ユーザー承認なしに`auto_apply_updates`（完全無人更新）を有効化する、または既定でONにする実装をする
- 自動リトライの実装（PRD/実装計画で明示的に「自動リトライしない」方針としている）

## セッション作法

- 実装着手前に、`docs/PRD.md`「8. 未確定・実装時に検証が必要な事項」に挙げたスパイクタスク（`hermes update --check`の実出力確認、トースト通知ライブラリの保守状況確認）を先に行う
- 実装順序は`docs/IMPLEMENTATION_PLAN.md`「10. 段階的な実装順序」（コア基盤→更新ランナー→スケジューラ→トレイUI→インストーラ→結合テスト）に従う
- Agent側の更新は必ず`hermes update` CLI経由（WebUIの`/api/updates/apply`をAgent対象には使わない — 依存関係同期が行われない可能性があるため。詳細は実装計画書2.1節）

## 参照ドキュメント

| ファイル | 内容 |
|---|---|
| [`docs/PRD.md`](docs/PRD.md) | 要求仕様（スコープ・機能要件・非機能要件・成功指標） |
| [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) | 実装計画（アーキテクチャ・更新シーケンス・エラーハンドリング・検証シナリオ） |
| `CLAUDE.local.md`（非公開・gitignore対象） | Phase 14/16: 手動運用時代の詳細記録・本プロジェクトが自動化しようとしている手順の原典（ローカル環境のみ） |
