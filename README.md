# ai-org

Claude・Codex・ChatGPT などのAIが、役割を分けて同じ仕事を進めるための基盤（旧称 app-relay／AI Workspace Hub）。
案件ごとに目的と受け入れ条件を決め、編集権で同時編集を防ぎ、停止・再開、独立レビュー、引き継ぎを記録する。

## 構成

| 場所 | 中身 |
| --- | --- |
| `hub/` | 中核のコード（案件、編集権、停止・再開、レビュー、受信箱、案件画面）と自動テスト。旧 ChatRelay の試作（`app.py`、`core.py`、`native.py`、`uia.ps1`）も当面ここに置く |
| `hub/ai_org.py`、`hub/session.py` | 作業コマンド（中核）：start／status／pause-ack／finish／guard |
| `extensions/dev/` | 開発向けの拡張：git フック、Claude Code の編集前フック、検証コマンドとの連携 |
| `extensions/relay/` | 対話中継の拡張：Claude と Codex に実装とレビューを自動で交互に依頼する（アプリの画面か CLI。人が止められる） |
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
| 作業の前 | `start --case <案件ID> --agent "<担当とセッション名>" [--token-file <パス>]`：停止中・他の会話が保持中なら止まる。claim し、再開済みの案件なら方針確認を記録し、方針と担当予定（今回の実装担当・レビュー担当）を表示する。担当予定でレビュー担当になっている AI が start すると注意を出す（止めはしない） |
| 途中 | `status --case <案件ID> [--token-file <パス>]` |
| 停止要求が出たとき | `pause-ack --case <案件ID> --token-file <パス>` |
| 作業の後 | `finish --case <案件ID> --token-file <パス>`：案件の STATUS.md 冒頭の「更新」行が今日でなければ止まる（`--status-unchanged` で省略可）。release してトークンを消す。担当予定が「交互」なら、実装担当が `--turn-done`（実装とレビューを終えた）を付けて終えたときだけ、実装とレビューを入れ替える。作業の途中で会話を終えるときは付けない |
| 確認だけ | `guard --case <案件ID> --token-file <パス>`：書き込んでよければ 0、だめなら 1 |
| 写しを作る | `report [--out <ファイル>]`：全案件の状態・編集権・担当予定・STATUS の更新日・レビュー記録の数を Markdown の表にする。Notion・Drive への反映は、利用者の指示を受けた担当がこの出力を使って行う（コマンド自体は外部に書き込まない。トークンやログは含めない） |

- Claude Code は、`--token-file` に会話用の一時フォルダー（scratchpad）の `ai-org-<案件ID>.token` を指定する（編集前フックがそこを探す）。
- Codex など：`--token-file` を省くと、一時フォルダーの `ai-org\` に一意の名前で作られ、パスが表示される。それを会話の中だけで保持する。
- 担当名は、会話を区別できるよう識別子を含める（例：`Claude Code ai-org ea39bc9a`）。交互の入れ替えは担当名の先頭の「Codex」「Claude」で実装担当を見分けるので、担当名はこのどちらかで始める。
- 交互（担当予定）：Codex・Claude Code のどちらから操作しても同じになるよう、入れ替えは中核の release（`ai_org.py finish`、`dev.py finish`、`workspace_hub.py release` が共通に通る）で行う。実装担当が `--turn-done` を付けて編集権を返したときだけ入れ替え、付けないとき・レビュー担当・見分けられない担当名・ROLES.json が読めないときは入れ替えない（編集権は必ず返す）。文脈切れや日をまたぐ中断で会話を終えても、番は変わらない。レビューは編集権を返す前に受ける。新しい案件は交互が既定で、既存の案件は案件画面の「交互」にチェックを入れて保存する。recover（異常終了した会話の編集権の復旧）では入れ替えない。交互に対応していない旧版（v0.2.2 まで）は、finish で入れ替えず、画面で担当予定を保存すると交互の設定を消す。版を切り替えるときは、Codex・Claude Code・案件画面の使う版を同時に切り替える。

## 開発向けの拡張（extensions/dev）

開発リポジトリの直下に `.ai-org.json` を置き、案件と結び付ける。

```json
{"case": "case-…", "data": "C:\\…\\app-relay",
 "status_files": ["STATUS.md"], "check": ["powershell", "-NoProfile", "-File", "tools/check.ps1"]}
```

- git フック：`git config core.hooksPath <使う版>/extensions/dev/githooks`。コミット（prepare-commit-msg）と push（pre-push）の前に、環境変数 `AI_ORG_TOKEN_FILE` のトークンを照合し、停止中・編集権なし・方針確認前・記録が壊れているときは止める。利用者自身の作業は `AI_ORG_SKIP_CLAIM_CHECK=1` で確認を省ける。
  - prepare-commit-msg は、通常のコミット、マージ、cherry-pick、revert のすべてで呼ばれ、`--no-verify` でも飛ばされない。
  - 結び付けの根拠は、git の設定 `ai-org.case`（register が書く。ブランチに左右されない）→ 作業ツリーの `.ai-org.json` → 直前のコミットの `.ai-org.json` の順。結び付ける前からあるブランチや orphan ブランチ、結び付けを消すコミットでも確認を外せない。git の設定と `.ai-org.json` の案件が食い違えば止める。
  - pre-commit（固有の整形ツールが動く前に止める）と pre-applypatch（`git am`）でも確認する。通常のコミットでは pre-commit と prepare-commit-msg の2回確認する（約0.5秒増える）が、片方を飛ばす経路（`--no-verify`、マージ、cherry-pick）があるため、意図して両方に置いている。
  - Claude Code の編集前フックも、`.ai-org.json` のない作業ツリーでは git の設定 `ai-org.case`（または直前のコミットの `.ai-org.json`）で結び付けを確かめる。手で `.ai-org.json` を置いたリポジトリには、git フックが動いたときに git の設定を補う。
  - リポジトリ固有のフックは、クライアント側・サーバー側の主な種類を続けて呼ぶ。呼ぶ先は共通の `.git/hooks`（worktree でも同じ）。以前から `core.hooksPath` で別の置き場を使っていたリポジトリは、その場所を `git config ai-org.chainHooksPath <置き場>` に移す。置き場が見つからないときは注意を表示する。
  - 頻繁に動く reference-transaction と post-index-change は、git の操作が大きく遅くなるため包まない。git の共通設定で ai-org のフックを使うと、これら2種類のリポジトリ固有のフックは動かない。
  - リポジトリで `core.hooksPath` を個別に設定していると、git の共通設定より優先され、ai-org のフックは動かない。
- Claude Code の編集前フック：PreToolUse（Edit／Write／NotebookEdit）で `python <使う版>/extensions/dev/dev.py claude-guard` を呼ぶ。設定では `"command": "python"`、`"args": [<dev.py のパス>, "claude-guard"]`、`"onFailure": "block"` とし、フック自体が動かないときも止める（`onFailure` に対応した Claude Code の版が必要）。
  - 案件と結び付いたリポジトリと案件フォルダーへの書き込みを、その会話が編集権を持つときだけ許す。案件フォルダーは、データフォルダーの設定に頼らず `…\cases\case-<32桁>\` の形で見分ける。`\\?\` や `\\localhost\C$\` の形のパスも通常の形に直してから判定する。
  - サブエージェントの書き込み、ROLES.json と `.editing` への書き込みは常に止める。想定外のエラーでも止める。
- 終了：`python <使う版>/extensions/dev/dev.py finish --project <リポジトリ> --token-file <パス>`。編集権の照合 → 検証コマンド（30分で打ち切り）→ リポジトリの STATUS（`--status-unchanged` で省略）→ 未コミット → 中核の finish（案件の STATUS は `--case-status-unchanged` で省略、番を終えて交互に入れ替えるなら `--turn-done`）。

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
- フックを通らない git の操作（`commit-tree` と `update-ref`、`branch -f`、`reset`、fast-forward のマージなど）は止められない。これらはコミットを新しく作らずにブランチや作業ツリーを動かす。push の時点で確認を受けるが、手元の作業ツリーの変更は止められない。
- `report` の写しには、既定では案件名、保持者名、進行、担当予定、STATUS の更新日、レビュー記録の数だけが載り、STATUS の「状態」欄（自由記述）は載らない。`--include-status` を付けると「状態」欄も載る（200文字まで、認証情報らしい長い文字列は伏せ字）。短いパスワードなどは見分けられないので、付けるのは STATUS に機密がないことを確かめたときだけにする。
- フック設定の変更による回避は止められない（`--no-verify` は prepare-commit-msg を飛ばせないので、コミットは止まる）。

## 対話中継の拡張（extensions/relay）

Claude と Codex に、実装とレビューを自動で交互に依頼する。人が止められることを前提にした仕組みで、中継は AI に1通送る前と、返答を待つ間（数秒ごと）に、次のどれかに当たれば止まる。

- 案件画面の「一時停止を要求」（案件の停止・再開の記録）
- 停止ファイル（`python <使う版>/extensions/relay/relay.py stop --case <案件ID>`。再開は `clear-stop`）
- 1ラウンドのレビューの往復の上限（`--max-reviews`、既定4）・全体の時間の上限（`--max-minutes`、既定180分）・1通の返答を待つ上限（`--turn-minutes`、既定60分）
- AI の「進められない」（`RELAY: BLOCKED`）、終わりの印のない返答、想定外の印

1ラウンドの流れ（担当は案件の担当予定 ROLES.json に従う）：実装担当が `ai_org.py start` で編集権を取り、実装・検証・コミット（push はしない）→ `RELAY: READY_FOR_REVIEW` → レビュー担当が読み取りだけで `git diff <開始時のコミット>..HEAD` を確かめ `RELAY: APPROVED` か `RELAY: CHANGES_REQUESTED` → 指摘があれば実装担当が直す（往復）→ 承認されたら実装担当が STATUS を更新し `finish --turn-done` で編集権を返す → `RELAY: FINISHED`。`--turn-done` により、次のラウンドは実装とレビューが入れ替わる（`--rounds N`、2ラウンド目以降の依頼は案件の STATUS.md の「次の作業」）。

送った文と返答は、すべて案件フォルダーの `relay\<実行ID>\`（`transcript.md`、`events.jsonl`）に残る。同じ案件で中継は同時に1つだけ（`relay\RUNNING`）。

```
python <使う版>/extensions/relay/relay.py run --case <案件ID> --project <作業フォルダー> --task "<依頼>" ^
  --claude-title "<Claude の会話名>" --codex-title "<Codex の会話名>" [--rounds 2]
python <使う版>/extensions/relay/relay.py probe --side claude   （表示中の会話名と入力欄を見るだけ。送らない）
```

つなぎ方（`--mode`）：

- `app`（既定）：Claude デスクトップアプリ（Claude Code の会話）と Codex アプリ（OpenAI.Codex の `ChatGPT.exe`）の画面に、Windows の UI Automation で書き込み、返答を読む。会話はアプリの履歴に残る。
  - 送るのは、`--claude-title`・`--codex-title` で決めた会話が表示されているときだけ。違う会話、入力欄が1つに決まらない、入力欄に書きかけの文がある、貼り付けた文を確かめられない、のどれでも送らずに止まる（書きかけの文は消さない）。
  - 送るときは、アプリの窓を一瞬前面にしてクリップボード経由で貼り付け、Enter を押し、元の窓とクリップボードを戻す。中継の間はその窓で別の会話に切り替えない（切り替えると止まる）。
  - アプリの画面の作りが変わると読めなくなる。そのときは止まるので、`probe` で確かめる。
  - 中継を動かしている会話（例：この Claude Code の会話）を相手に指定しない。
  - Claude の分割表示（split view）は使えない。分割すると2つの会話が1つの画面（題名はフォーカスのある方）にまとまり、入力欄がどちらの会話のものか決められないので、中継は送らずに止まる。相手の会話は別の窓（ポップアウト）で開く。
- `cli`：Claude Code（デスクトップアプリに同梱の `claude.exe -p`）と Codex（Codex アプリに同梱の `codex.exe exec`）を呼ぶ。それぞれの定額プラン（Claude のサブスクリプション、ChatGPT のプラン）の利用枠を使い、API 料金は使わない。レビュー担当は読み取りだけ（Claude は編集の道具を外し、Codex は read-only の sandbox）。
  - Claude の CLI は、デスクトップアプリのサインインを引き継がない。初めに利用者が `claude.exe` を一度起動して `/login` でサインインする。
  - PATH にある古い単体版の `codex.exe`（0.135.0）は、今のモデル一覧を読めずに失敗する。中継はアプリに同梱の新しい方を使う（環境変数 `AI_ORG_RELAY_CODEX`・`AI_ORG_RELAY_CLAUDE` で指定もできる）。

トークンファイル：Codex は `%TEMP%\ai-org\relay-<実行ID>-codex.token`。Claude は、Claude Code の編集前フックがその会話の一時フォルダー（scratchpad）の `ai-org-<案件ID>.token` だけを見るので、そこに置くよう依頼文で指示する。

限界：

- `app` では、中継は AI の作業の途中で割り込めない（停止の要求は、AI 自身が作業の区切りで `status` を見て止まるのと、中継が次を送らないことで効く）。今すぐ止めるときは、アプリの停止ボタンを押す。`cli` では、待ちの間も数秒ごとに停止を確かめ、止まったら AI のプロセスを終わらせる。
- 「レビュー担当は読み取りだけ」は、`app` では依頼文での指示にすぎない（アプリの会話の権限のまま動く）。`cli` の Claude は編集の道具を外すが、利用者の設定（settings.json）の許可も合わさるので完全な強制ではない。Codex の read-only の sandbox は強制される。push の禁止も依頼文での指示。
- 一方の AI の返答は、もう一方への依頼文に入る（プロンプト注入の経路になる）。返答の終わりの印は、中継が毎回作る予測できない relay-id 付きで、送った文より後ろだけを探すので、転送した文の中の偽の印では進まない。
- 送るとき、クリップボードを一時的に使う（すべての形式を写して戻す。Windows のクリップボード履歴を使っていれば、依頼文が履歴に残る）。中継が前面に出した窓の2秒の間の打鍵は、その窓に入る。隠れた窓を読み直すために前面に出す間隔は、45秒から倍々に空ける（最大5分）。
- 途中で止まると、実装担当が取った編集権は残る。続けるなら同じ担当で中継を始め直す（AI が start し直す）。やめるなら、その AI に finish を頼むか、基盤の recover で戻す（利用者の確認のうえ）。
- 利用枠の上限に達すると返答が止まり、待ちの上限で中継も止まる。

## テスト

```bash
python tools/check.py
```
