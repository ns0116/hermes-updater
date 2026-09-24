# AUDIT.md — hermes-updater

作成日: 2026-09-24
更新日: 2026-09-24（対応状況追記）

## 対応状況（2026-09-24）

- ✅ **対応済み**（高1）: `pyproject.toml`の`pystray`・`win11toast`に`sys_platform == "win32"`の環境マーカーを付与（別コミット`be44968`）。あわせてLinux上での`pip install -e ".[dev]"`可否を検証する軽量CIジョブ（`install-linux`）を追加（本コミット）。
- 未対応: 高2（`shell.py`の`creationflags`プラットフォーム分岐）、高3（CLAUDE.mdへのクラウドセッション作業範囲の明記）、中4-6、低7-8は今回のスコープ外（実装は未着手）。

調査範囲: `D:\Naoyuki\Projects\hermes-updater` 配下全体（読み取り専用調査。このファイル以外は一切変更していない）

---

## プロンプト監査結果

### 対象ファイルの棚卸し

| パス | 状態 |
|---|---|
| `CLAUDE.md` | 存在する（91行、レポジトリにコミット済み） |
| `CLAUDE.local.md` | 存在するが `.gitignore:8` で除外、リポジトリには含まれない（ローカル専用） |
| `.claude/agents/*` | 存在しない |
| `.claude/skills/*` | 存在しない |
| `.claude/commands/*` | 存在しない |
| `.claude/rules/*` | 存在しない |
| `.claude/settings.local.json` | 存在するが `.gitignore:9`（`.claude/`丸ごと）で除外、リポジトリには含まれない |

`git ls-files | grep -i claude` で確認した結果、このリポジトリでコミットされている `.claude` 関連ファイルは実質ゼロで、`CLAUDE.md`のみが追跡対象。つまり **`.claude/agents`・`.claude/skills`・`.claude/commands`・`.claude/rules` は「対象ファイルなし」**であり、クラウドセッション（毎回まっさらなgit clone）では `.claude/` ディレクトリ自体が存在しない状態で起動する。

### CLAUDE.md の内容監査

全体として「核のみを保持。詳細はdocs/を参照」という冒頭方針どおり簡潔にまとまっており、`docs/PRD.md`・`docs/IMPLEMENTATION_PLAN.md`へのリンクも実在し、記載内容とコード（`src/hermes_updater/`の実装）に矛盾は見当たらなかった。指摘事項は以下の通り。

1. **クラウドセッション向けの言及が一切ない（抜けているコンテキスト・最重要）**
   `CLAUDE.md`のガードレール（`AUTO`/`SEMI_AUTO`/`禁止`）は「実際に動いているHermes Agentインストール」「実プロセス」「タスクスケジューラ」の存在を前提にした記述しかない（`CLAUDE.md:19-39`）。クラウドサンドボックスには`C:\Users\<username>\AppData\Local\hermes`も`hermes`コマンドも実プロセスも存在しないため、これらのガードレールはそもそも実行不可能な操作について書かれている。「クラウドセッションでは`SEMI_AUTO`/`禁止`項目は原理的に実行できない（対象システムが存在しない）。コード変更・テスト実行・ドキュメント更新に限定して作業する」といった一文がないため、クラウドセッションのClaudeが「`hermes update --yes`を試すべきか」を毎回自分で判断する必要がある。

2. **`CLAUDE.local.md`への依存を示す記述はあるが、クラウドでは読めないことへの言及がない**
   `CLAUDE.md:53`で「`CLAUDE.local.md`（非公開・gitignore対象）...ローカル環境のみ」と明記されているのは良い設計だが、「クラウドセッションではこのファイルは存在しないため、Phase 14/16の手動運用の原典を参照できない」旨までは書かれていない。実害は小さいが、クラウド側のClaudeが一度は`CLAUDE.local.md`を読もうとして存在しないことに気づく、という無駄な1ターンが発生しうる。

3. **テストコマンド・Lintコマンドの重複回避は妥当だが、CI構成への言及がない**
   `CLAUDE.md`自体にはpytestコマンドの記載がなく（README.mdに委譲、これは適切な設計）、一方で`.github/workflows/tests.yml`がWindows専用ランナー（`windows-latest`、後述）で動いていることには`CLAUDE.md`・`README.md`のどちらにも言及がない。「このプロジェクトはWindows専用CIでのみ検証されている」という一文があれば、クラウド側でテストが通らなかった場合の切り分けが早くなる。

4. **矛盾・重複・古い情報**: 見つからなかった。`docs/PRD.md`・`docs/IMPLEMENTATION_PLAN.md`とも整合しており、存在しないファイル/コマンドへの言及もない。

5. **曖昧な指示**: 見つからなかった。`AUTO`/`SEMI_AUTO`/`禁止`の境界線は具体的なコマンド名まで書かれており明確。

### settings.local.json について（参考情報）

`.claude/settings.local.json`はタスク1の直接対象ではないが、`Bash(...)`許可リストに`C:\Users\nsait\...`・`D:\Naoyuki\Projects\hermes-updater\...`という個人環境のフルパスが多数ハードコードされている（例: 37〜45行目のPowerShellコマンド群）。このファイルは`.gitignore:9`で除外されておりリポジトリには含まれないため、**クラウドセッションからは見えず実害はない**。ただし将来このファイルの一部をチームで共有する方針に変えるなら、パスの一般化が必要になる点は留意事項として記録しておく。

---

## ローカル依存リスト

このプロジェクトは設計上「Windowsネイティブのシステムトレイ常駐アプリ」であり、本体機能（トースト通知・タスクスケジューラ登録・実プロセスのkill等）がWindows専用であること自体は仕様であり問題ではない。以下は「クラウドサンドボックス（Linuxコンテナ、git cloneのみ）からこのリポジトリを**開発・テストする**際に支障になる依存」に絞って列挙する。

### 高影響（テスト・インストール自体が失敗しうる）

- **`pyproject.toml:8-13`** — `dependencies`に`pystray`・`win11toast`がプラットフォームマーカーなしで列挙されている。`win11toast`はWindows Runtime（winrt/winsdk）バインディングに依存するパッケージで、Linux向けの配布物が無い可能性が高い。`pip install -e ".[dev]"`（README.mdの開発セットアップ手順、README.md:31-34）をクラウドのLinuxサンドボックスでそのまま実行すると、この段階で失敗する可能性が高い。
- **`.github/workflows/tests.yml:10`** — `runs-on: windows-latest`固定。Linux/macOSでのインストール可否を検証するCIジョブが存在しないため、「Linuxでpipインストールが通るか」は誰も検証したことがない状態。

### 中影響（インストールが仮に通っても、実行すると壊れる）

- **`src/hermes_updater/shell.py:20`, `shell.py:47`** — `CREATE_NO_WINDOW = 0x08000000`を`subprocess.run(..., creationflags=CREATE_NO_WINDOW)`に無条件で渡している。`creationflags`はWindows専用引数で、Linux上で`shell.run()`を実際に呼び出すと`ValueError`になる（現状のテストスイートは`shell.run`を常にmonkeypatchしているため`pytest`実行時には顕在化しないが、`python -m hermes_updater --check`等をクラウド上のシェルで素朴に試すと即座に失敗する）。
- **`src/hermes_updater/shell.py:70-75`（`run_powershell`）** — `powershell`コマンドを前提にしている。`find_pid_by_port`・`taskkill_pid`・`run_elevated`・`start_scheduled_task`は全てこれ経由（`shell.py:70-149`）。一般的なクラウドLinuxサンドボックスに`powershell`は存在しない。
- **`src/hermes_updater/ui.py:9-10`** — `import pystray` / `from PIL import Image, ImageDraw`をモジュールトップレベルで実行。`pystray`はLinuxではGTK/AppIndicator等のシステムトレイ実装に依存し、ヘッドレスなコンテナでは動作しない（importレベルでは通っても、`pystray.Icon(...).run()`実行時に失敗する可能性が高い）。
- **`src/hermes_updater/ui.py:198, 204, 214, 225`** — `os.startfile(...)`を使用。これはWindows専用API（Linuxでは`AttributeError: module 'os' has no attribute 'startfile'`）。

### 低影響（意図的な設計、または既に適切にガードされている）

- **`src/hermes_updater/models.py:13-20`** — `_default_hermes_install_path()`/`_default_hermes_webui_path()`が`%LOCALAPPDATA%\hermes`をデフォルト値にしている。`config.py:19-27`の`get_app_data_dir()`も同様に`LOCALAPPDATA`環境変数に依存し、未定義時は`Path.home() / "AppData" / "Local"`にフォールバックする実装（Linux上では単に存在しないパスになるだけで、クラッシュはしない）。
- **`src/hermes_updater/__main__.py:28-34`** — `ctypes.windll`の呼び出しは`if sys.platform == "win32":`で正しくガードされている。良い実装で、修正不要。
- **`src/hermes_updater/notifier.py:52-56`** — `win11toast`のimportは関数内で`try/except ImportError`によりガードされている。良い実装で、修正不要（ただしパッケージ自体のインストールが上記「高影響」の理由で失敗する場合はここに到達する前に問題になる）。
- **`install/create-scheduled-task.ps1`（全体）、`install/uninstall.ps1`（全体）** — PowerShell + `Register-ScheduledTask`/`Get-ScheduledTask`等のWindowsタスクスケジューラAPIそのもの。インストーラーという性質上Windows専用であることは仕様であり問題ではない（クラウドで実行する対象ではない）。
- **`README.md:92-97`** — `config.json`のサンプルに`C:\\Users\\<username>\\AppData\\Local\\hermes`等のパス例があるが、これはドキュメント上の設定例であり`<username>`のプレースホルダ化もされている。問題なし。
- **`.claude/settings.local.json`** — 前述の通り`.gitignore`で除外済みのためクラウドセッションには到達しない。

### 該当なし（要調査観点として確認したが見つからなかったもの）

- `garryu-studio`、Discord bot、n8n、Ollama、自宅サーバー/NASへの参照は、ソースコード・ドキュメント・設定ファイルのいずれにも見つからなかった（`grep -ri "garryu\|discord\|n8n\|ollama"`で0件）。このプロジェクトは`garryu-studio`とは無関係の独立したリポジトリと判断できる。
- WSL2の`/mnt/`パスやNASのUNCパス（`\\...`）のハードコードも見つからなかった。

---

## 改善提案（優先度付き）

### 優先度: 高

1. **`pyproject.toml`の依存に環境マーカーを付与する**
   `pystray`・`win11toast`に`; sys_platform == "win32"`を付け、Linux/macOS環境では両パッケージをインストール対象から外す。これにより、クラウドサンドボックスでの`pip install -e ".[dev]"`がそもそも失敗しなくなる可能性が高い（`pyproject.toml:8-13`）。あわせて、コアロジック（`config`/`models`/`updater`/`shell`/`app`/`logger`）だけをテストする場合に`pystray`/`win11toast`不要でインストールできるようになり、クラウド側のテスト実行が現実的になる。

2. **`shell.py`の`creationflags`をプラットフォーム分岐させる**
   `creationflags=CREATE_NO_WINDOW`は`if sys.platform == "win32" else {}`のような形でガードし、非Windows環境で`shell.run()`を直接叩いても`ValueError`にならないようにする（`shell.py:20, 36-49`）。実運用上の影響はないが、クラウド側でCLIの動作確認を素朴に試したときの無駄な失敗を防げる。

3. **CLAUDE.mdに「クラウドセッションでの作業範囲」の一文を追加する**
   「このアプリはWindowsネイティブのシステムトレイ常駐アプリであり、実際のHermes Agentインストール・実プロセス・タスクスケジューラを前提にした`SEMI_AUTO`/`禁止`操作はクラウドセッションでは実行不可能（対象システムが存在しない）。クラウドセッションではコード変更・`pytest`実行・ドキュメント更新に限定する」旨を明記する。ガードレール自体を変える必要はなく、適用範囲の前提を一言添えるだけで十分（`CLAUDE.md`19-39行目付近に追記）。

### 優先度: 中

4. **`README.md`または`CLAUDE.md`にCI構成（Windows専用）を明記する**
   `.github/workflows/tests.yml:10`が`windows-latest`固定であることをどこかに一文残しておくと、クラウド側でテストが失敗した際に「そもそもLinuxでの動作は検証されたことがない」という前提をすぐに把握できる。

5. **`ui.py`のpystray/PIL importを遅延importにする**
   現状`__main__.py`側は「引数なし（トレイモード）のときだけ`from hermes_updater import ui`」と遅延importしており設計は正しい（`__main__.py:101-103`）。一方`ui.py`自身のモジュール冒頭（`ui.py:9-10`）で`pystray`/`PIL`を即時importしているため、`ui`モジュールを一切使わないコード（`app.py`・`updater.py`等）からたまたま`ui`がimportされるような変更が将来入ると、非Windows環境で連鎖的にimportエラーになるリスクが残る。実害は現状ないが、境界を明確にする意味で軽い改善として記録。

6. **`CLAUDE.md`に「`CLAUDE.local.md`はクラウドセッションには存在しない」旨を一言追加**
   `CLAUDE.md:53`の該当行に「(クラウドセッションでは参照不可)」を添えるだけで十分。

### 優先度: 低

7. **`.claude/`をgitignoreしている現状の是非を一度検討する**
   現状`.claude/`丸ごと`.gitignore:9`で除外されており、`.claude/agents`・`.claude/skills`・`.claude/commands`・`.claude/rules`をチームで共有する予定がないなら現状維持で問題ない。将来的に「クラウドセッション向けの短いガードレールだけを`.claude/rules/cloud.md`として共有したい」といったニーズが出た場合は、`.gitignore`の除外対象を`.claude/settings.local.json`のみに絞る変更を検討する。

8. **`install/*.ps1`にクラウド実行不可である旨のコメントを追加（任意）**
   現状でも冒頭コメントで前提（UAC昇格・ローカルタスクスケジューラ）は明確なため必須ではないが、「クラウドセッションでは実行対象外」と一言添えると誤って実行を試みるリスクをさらに下げられる。

---

## 総括

このプロジェクトは元々「Windowsローカルでのみ動く」ことを前提に設計されたシステムトレイ常駐アプリであり、Windows専用API・コマンド依存自体は仕様であって欠陥ではない。クラウドセッション対応の観点で本当に問題になるのは、**コア開発ループ（`pip install -e ".[dev]"` → `pytest tests/`）がクラウドのLinuxサンドボックスで成立するかどうか**であり、その唯一のボトルネックは`pyproject.toml`の依存宣言（`pystray`/`win11toast`にプラットフォームマーカーがない点）に集約される。テストスイート自体はモックで`shell.run`を差し替えており、コアロジック（`config`/`models`/`updater`/`app`）はクロスプラットフォームな実装になっている点は評価できる。
