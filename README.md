# ai-org

Claude・Codex・ChatGPT などのAIが、役割を分けて同じ仕事を進めるための基盤（旧称 app-relay／AI Workspace Hub）。
案件ごとに目的と受け入れ条件を決め、編集権で同時編集を防ぎ、停止・再開、独立レビュー、引き継ぎを記録する。

## 構成

| 場所 | 中身 |
| --- | --- |
| `hub/` | 中核のコード（案件、編集権、停止・再開、レビュー、受信箱、案件画面）と自動テスト。旧 ChatRelay の試作（`app.py`、`core.py`、`native.py`、`uia.ps1`）も当面ここに置く |
| `hub/ai_org.py`、`hub/session.py` | 作業コマンド（中核）：start／status／pause-ack／finish／guard |
| `extensions/dev/` | 開発向けの拡張：git フック、Claude Code の編集前フック、検証コマンドとの連携 |
| `legacy/forward.py` | 旧来の配置から使う版へ中継するスクリプト（下記） |
| `docs/` | 利用ガイド（`WORKSPACE_HUB.md`）、引き継ぎ形式、移行記録など |

中核は開発以外の仕事（資料作成・調査など）にも使えるよう、汎用に保つ。開発向けの機能（git フック、編集前フック、開発フォルダーでの必須化）は拡張として別に作る（予定）。

## データの置き場所

コードとデータを分ける。データの正本はローカルのデータフォルダーで、git には入れない。

- 環境変数 `AI_ORG_DATA` でデータフォルダーを指定する。中身は `cases`、`inbox`、`data`、`knowledge-vault`、`work-test`。
- 未設定のときは、コードと同じフォルダーに `cases` がある旧来の配置だけを受け付ける。どちらでもなければ止まる（リポジトリの中に案件記録を作らない）。
- このPCのデータフォルダーは `Documents\ChatGPT\AI駆動×AI駆動\app-relay`。Notion・Google Drive には、利用者が指示したときに人向けの写しを出す（予定）。

## 旧コマンドとの互換

データフォルダーに `legacy/forward.py` を `workspace_hub.py`・`hub_ui.py` などの名前で置くと（一覧は `docs/MIGRATION.md`）、
`python ../../workspace_hub.py claim ...` などの旧コマンドと案件画面の起動用 `.cmd` が、そのまま使う版で動く。
使う版の場所は、データフォルダーの `ai-org-home.txt` に書く（ないときだけ環境変数 `AI_ORG_HOME`）。データの置き場所は、常に中継スクリプトのあるフォルダー。

## 開発する版と使う版

- このリポジトリのクローンで開発し、テストとレビューを通した版にタグ（例：`v0.1.0`）を付ける。
- 使う版は、タグを独立に clone した別のフォルダー（例：`%LOCALAPPDATA%\ai-org\v0.1.0`）。データフォルダーの `ai-org-home.txt` がそこを指す。開発用のクローンには依存しない。
- 開発中の変更が、使っている案件にすぐ効かないようにするため。戻すときは `ai-org-home.txt` を前の版に向ける。手順は `docs/MIGRATION.md`。

## 作業コマンド（中核）

基盤の手順（work-state → claim → confirm-direction → 作業 → STATUS 更新 → release）を1つずつのコマンドにした。
本人確認はトークンファイルで行う。トークンファイルは会話ごとに別の場所に置き、作業中だけ保持し、中身を表示・転記しない。

データフォルダーは `AI_ORG_DATA`、なければ利用者の設定（`%USERPROFILE%\.ai-org\config.json` の `data`）で決まる。どちらもなければ、データフォルダーの中継（`python <データフォルダー>\ai_org.py …`、案件フォルダーからは `python ../../ai_org.py …`）を使う。

| いつ | コマンド（`python ai_org.py …`） |
| --- | --- |
| 作業の前 | `start --case <案件ID> --agent "<担当とセッション名>" [--token-file <パス>]`：停止中・他の会話が保持中なら止まる。claim し、再開済みの案件なら方針確認を記録し、方針を表示する |
| 途中 | `status --case <案件ID> [--token-file <パス>]` |
| 停止要求が出たとき | `pause-ack --case <案件ID> --token-file <パス>` |
| 作業の後 | `finish --case <案件ID> --token-file <パス>`：案件の STATUS.md 冒頭の「更新」行が今日でなければ止まる（`--status-unchanged` で省略可）。release してトークンを消す |
| 確認だけ | `guard --case <案件ID> --token-file <パス>`：書き込んでよければ 0、だめなら 1 |

- Claude Code は、`--token-file` に会話用の一時フォルダー（scratchpad）の `ai-org-<案件ID>.token` を指定する（編集前フックがそこを探す）。
- Codex など：`--token-file` を省くと、一時フォルダーの `ai-org\` に一意の名前で作られ、パスが表示される。それを会話の中だけで保持する。
- 担当名は、会話を区別できるよう識別子を含める（例：`Claude Code ai-org ea39bc9a`）。

## 開発向けの拡張（extensions/dev）

開発リポジトリの直下に `.ai-org.json` を置き、案件と結び付ける。

```json
{"case": "case-…", "data": "C:\\…\\app-relay",
 "status_files": ["STATUS.md"], "check": ["powershell", "-NoProfile", "-File", "tools/check.ps1"]}
```

- git フック：`git config core.hooksPath <使う版>/extensions/dev/githooks`。コミット（prepare-commit-msg）と push（pre-push）の前に、環境変数 `AI_ORG_TOKEN_FILE` のトークンを照合し、停止中・編集権なし・方針確認前・記録が壊れているときは止める。利用者自身の作業は `AI_ORG_SKIP_CLAIM_CHECK=1` で確認を省ける。
  - prepare-commit-msg は、通常のコミット、マージ、cherry-pick、revert のすべてで呼ばれ、`--no-verify` でも飛ばされない。
  - 作業ツリーに `.ai-org.json` がなくても、直前のコミットにあれば結び付いたリポジトリとして扱う（結び付けを消すコミットで確認を外せない）。
  - リポジトリ固有のフックは、クライアント側・サーバー側の主な種類を続けて呼ぶ。呼ぶ先は共通の `.git/hooks`（worktree でも同じ）。以前から `core.hooksPath` で別の置き場を使っていたリポジトリは、その場所を `git config ai-org.chainHooksPath <置き場>` に移す。置き場が見つからないときは注意を表示する。
  - 頻繁に動く reference-transaction と post-index-change は、git の操作が大きく遅くなるため包まない。git の共通設定で ai-org のフックを使うと、これら2種類のリポジトリ固有のフックは動かない。
  - リポジトリで `core.hooksPath` を個別に設定していると、git の共通設定より優先され、ai-org のフックは動かない。
- Claude Code の編集前フック：PreToolUse（Edit／Write／NotebookEdit）で `python <使う版>/extensions/dev/dev.py claude-guard` を呼ぶ。設定では `"command": "python"`、`"args": [<dev.py のパス>, "claude-guard"]`、`"onFailure": "block"` とし、フック自体が動かないときも止める（`onFailure` に対応した Claude Code の版が必要）。
  - 案件と結び付いたリポジトリと案件フォルダーへの書き込みを、その会話が編集権を持つときだけ許す。案件フォルダーは、データフォルダーの設定に頼らず `…\cases\case-<32桁>\` の形で見分ける。`\\?\` や `\\localhost\C$\` の形のパスも通常の形に直してから判定する。
  - サブエージェントの書き込み、ROLES.json と `.editing` への書き込みは常に止める。想定外のエラーでも止める。
- 終了：`python <使う版>/extensions/dev/dev.py finish --project <リポジトリ> --token-file <パス>`。編集権の照合 → 検証コマンド（30分で打ち切り）→ リポジトリの STATUS（`--status-unchanged` で省略）→ 未コミット → 中核の finish（案件の STATUS は `--case-status-unchanged` で省略）。

### 必須化（利用者の設定）

`%USERPROFILE%\.ai-org\config.json`（環境変数 `AI_ORG_CONFIG` で場所を変えられる）がある場合だけ働く。

```json
{"dev_roots": ["C:\\Users\\…\\2_programing\\git"], "exclude": [], "data": "C:\\…\\app-relay"}
```

- `dev_roots` の下で、案件と結び付いていない（`.ai-org.json` がない）リポジトリへの書き込み（Claude Code）とコミット・push（git フック）を止める。`exclude` の下と、`dev_roots` の外には効かない。
- 新しい開発の始め方：下書きを受信箱に置く → 利用者が案件画面で確定 → `ai_org.py start` → `python <使う版>/extensions/dev/dev.py register --project <リポジトリ> --case <案件ID> --token-file <パス> [--status-file STATUS.md] [--check-json "[…]"]`。register は、その案件の編集権を持つ会話だけが行え、既存の `.ai-org.json` は上書きしない。
- 全リポジトリに効かせるには、git の共通設定 `core.hooksPath` を `<使う版>/extensions/dev/githooks` に、Claude Code のユーザー設定に編集前フックを入れる。いずれも利用者の設定の変更なので、項目ごとに利用者の確認を得る（`docs/MIGRATION.md` の段階3）。

### 防げない範囲

- 同じ Windows ユーザーで動く会話どうしは、互いのトークンファイルを読める。防げるのは、取り忘れ・返却後の書き込み・別の会話が保持中の書き込み・異常終了した会話からの自動引き継ぎといった事故で、故意のなりすましは防げない。
- Claude Code の編集前フックは Edit／Write／NotebookEdit だけが対象。シェルからの書き込みは、開発リポジトリなら git フックが最後の確認になるが、案件フォルダー（ROLES.json、`.editing` を含む）は git で管理していないので、シェルからの書き込みは確認を受けない。サブエージェントは親と同じ一時フォルダーを使うので、シェルからの作業コマンドや git をサブエージェントに任せない。
- Codex・ChatGPT には編集前フックがない。ファイルの書き込みは止められず、コミット・push の時点で止まる。
- `--no-verify` やフック設定の変更による回避は止められない。

## テスト

```bash
python tools/check.py
```
