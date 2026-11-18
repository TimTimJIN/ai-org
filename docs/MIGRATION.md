# app-relay からの移行記録

## 段階1：リポジトリ化（2026-11-18）

- 取り込み元：`Documents\ChatGPT\AI駆動×AI駆動\app-relay`。移行前の控え：`AI駆動×AI駆動\app-relay_控え_20261118.zip`（SHA-256 `bf8d320ed6c875d30cdf7e037c2040704903db43077bd06a9fbc3fa79f8091e8`、ファイル107件）。
- 最初のコミット（bd9a991）で、コード（`*.py`、`uia.ps1`、`*.cmd`）を `hub/` に、文書（`*.md`）を `docs/` に、内容を変えずに置いた。データ（cases、inbox、data、knowledge-vault、work-test）とショートカット（`.lnk`）、`__pycache__` は取り込んでいない。
- コードとデータの分離：データの置き場所を `hub/data_root.py` に集め、環境変数 `AI_ORG_DATA` で指定するようにした。変更したのは `workspace_hub.py`（案件フォルダーの既定値）、`app.py`（ChatRelay のデータ）、`seed_knowledge.py`、`verify_work.py`、`knowledge.py`（`--store` の既定値。レビュー対応で追加）。
- 旧コマンドの中継：`legacy/forward.py` を追加。
- 注記：「内容を変えずに」は改行コードを除く。`docs/KNOWLEDGE.md` は CRLF が `.gitattributes` で LF に、`*.cmd`・`uia.ps1` は取り出すと CRLF になる。

### レビューへの対応（Claude 独立レビュー b38299fe…、重大指摘なし）

- 中継スクリプトを import すると止まるようにした（旧テストや unittest から誤って CLI が動かないように）。
- 使う版の場所は `ai-org-home.txt` を優先し、相対パスは中継スクリプトのフォルダー基準で解決し、環境変数を展開する。データの置き場所は常に中継スクリプトのフォルダー（環境変数 AI_ORG_DATA より優先）。
- AI_ORG_DATA は、絶対パスで、中に cases があるフォルダーだけを受け付ける（綴りの誤りなどで新しい案件記録を作らない）。
- `knowledge.py` の `--store` の既定値をデータフォルダー基準にした。使われていない `workspace_hub.ROOT` を削除。

### 再確認への対応（7ec1024e…、重大指摘なし）

- 戻し方をコードだけに限定した（下の手順）。`seed_knowledge.py` に `__main__` の判定を入れた。使う版は開発用のクローンに依存しないよう、worktree ではなく独立した clone にした。

## 本番切り替えの手順

1. テストとレビューを通した版にタグ（例：`v0.1.0`）を付け、`git clone --branch v0.1.0 <リポジトリ> %LOCALAPPDATA%\ai-org\v0.1.0` で使う版を取り出す。開発用のクローンとは独立しているので、開発用を動かしても消しても影響しない。
2. 置き換えと削除の前に、手順3・4の対象ファイルだけを `AI駆動×AI駆動\app-relay_旧コード_<日付>\` に写して残す（データは含めない）。
3. データフォルダー（app-relay）に `ai-org-home.txt` を置き、使う版のフォルダーを絶対パスで書く。次のファイルを `legacy/forward.py` の写しに置き換える：`workspace_hub.py`、`hub_ui.py`、`app.py`、`knowledge.py`、`verify_work.py`、`seed_knowledge.py`。v0.2.0 以降は `ai_org.py` も置く。
4. 次のファイルはデータフォルダーから消す（使う版の hub/ にある）：`case_editing.py`、`case_guide.py`、`core.py`、`native.py`、`uia.ps1`、`test_*.py`、`__pycache__`。
5. 次は残す：`open_hub.cmd`、`start.cmd`（中継経由で動く）、`*.md`（案件向けの AGENTS.md が `app-relay/WORKSPACE_HUB.md` を参照しているため）、ショートカット（`.lnk`）、データ（cases、inbox、data、knowledge-vault、work-test）。
6. 写しで確認済みの項目に加え、本番で旧コマンドと案件画面を確認する。
7. 戻すとき：手順2で残した旧コードを app-relay に写し戻し、`ai-org-home.txt` を消す。**データ（cases、inbox など）は戻さない**（切り替え後の claim、コメント、review-note などを失わないため）。控えの zip は、データまで含めて失ったときだけ使う。
8. 版を上げるとき：新しいタグを別のフォルダーに clone し、`ai-org-home.txt` をそのフォルダーに書き換える。前の版のフォルダーは、戻すために残しておく。

### 確認したこと

- 取り込み前の app-relay で自動テスト63件が成功。リポジトリでは、追加した5件を含む68件が成功し、テスト後に `hub/` にデータのフォルダーが作られないことを確認。
- 本番データの写し（一時フォルダー）に中継スクリプトを置き、次を確認した。本番のデータには触れていない。
  - 案件フォルダーから旧コマンド `python ../../workspace_hub.py work-state` が動く。
  - claim・release が写しの側にだけ記録される。
  - データフォルダーから draft-status、verify_work が動く。
  - 中継経由で案件画面（hub_ui）が起動し、5秒後もエラーなく動いている（画面の操作は未確認）。

### 本番切り替えの実施（2026-11-18、ユーザーの指示「pushと本番の切替含め、残タスクを進めて」）

- GitHub（TimTimJIN/ai-org）に main と タグ v0.1.0（44d58e9）を push。使う版を `%LOCALAPPDATA%\ai-org\v0.1.0` に clone。
- 旧コード19件を `AI駆動×AI駆動\app-relay_旧コード_20261118\` に写し、ハッシュの一致を確かめてから、手順3・4のとおり置き換えと削除をした。`ai-org-home.txt` は使う版の絶対パス。
- 切り替え後に確認したこと：スワイプと ai-org の両案件フォルダーから旧コマンドの work-state、データフォルダーから draft-status と verify_work、引数の誤りで終了コード 2、`open_hub.cmd` から案件画面が起動、データフォルダーに `__pycache__` ができない。
- 未確認：案件画面での操作（案件の表示、claim、保存）。利用者が画面を使ったときに確かめる。

## 段階2：作業コマンドと開発向けの拡張（v0.2.0、2026-11-18）

- 中核の作業コマンド（hub/ai_org.py、session.py）と開発向けの拡張（extensions/dev）を追加。段階3の準備（必須化の方針、register）も含む。
- Claude 独立レビュー：bd771276…（重大1・中6・軽微4）→ d6d72a2f…（重大なし、中2・軽微5）→ 71f23403…（重大なし、中2・軽微2）→ b248d850…（重大・中なし、軽微3）。各指摘に対応した。最後の軽微3件は v0.2.1 で対応する（Claude Code の編集前フックが git の設定 ai-org.case も見る、手で結び付けたリポジトリに git の設定を補う、コミット1回で確認が2回動く）。
- 切り替え：v0.2.0（14effdf）を `%LOCALAPPDATA%\ai-org\v0.2.0` に clone し、その場でテスト101件が成功。データフォルダーの `ai-org-home.txt` を v0.2.0 に向け、中継に `ai_org.py` を加え、ほかの中継も v0.2.0 の forward.py に更新した。前の版 v0.1.0 のフォルダーは戻すために残している。
- 切り替え後の確認：旧コマンド（work-state、draft-status）、中継経由の `ai_org.py status`・`guard`、案件画面の起動、データフォルダーに `__pycache__` ができないこと。

## 段階3・4：必須化とスワイプ案件の切り替え（2026-11-18、利用者が4項目すべてを承認）

- 利用者の設定 `%USERPROFILE%\.ai-org\config.json`：dev_roots＝`Documents\2_programing\git`、exclude なし、data＝app-relay、home＝v0.2.0。既存の4リポジトリは除外せず、使うときに案件登録する。
- git の共通設定：`core.hooksPath` を `%LOCALAPPDATA%\ai-org\v0.2.0\extensions\dev\githooks` に（以前は未設定）。
- Claude Code のユーザー設定 `~/.claude/settings.json`：PreToolUse（Edit／Write／NotebookEdit）に `python <v0.2.0>/extensions/dev/dev.py claude-guard`、`onFailure: block`。既存の `agentPushNotifEnabled` は残した。`~/.claude/CLAUDE.md` に共通指示を新規作成。
- Codex の共通指示 `~/.codex/AGENTS.md` を新規作成。
- 安定したパスとして `%LOCALAPPDATA%\ai-org\current`（ジャンクション）を試したが、この環境ではジャンクションを通したファイルを Python・cmd から開けなかった。そのため使わず、各設定に版のフォルダーを直接書く。
- 動作確認：開発フォルダーに一時的な未登録リポジトリを作り、Claude Code の Write と git commit がどちらも止まることを確かめてから消した。ai-org とスワイプのリポジトリでは、編集権を持つ会話のコミットが通ることを確かめた。
- スワイプ案件（段階4）：`dev.py register` で `.ai-org.json` と git の設定を書き、リポジトリ単位の `core.hooksPath`（.githooks）を外し、手元専用の試作フックを消した。スワイプ案件に置いていたカイゼンの試作・レビューの記録は、ai-org 案件の `history/kaizen-from-swipe-20261118` に移した（ハッシュ一致を確認）。

### 版を上げるとき

1. 新しいタグを `%LOCALAPPDATA%\ai-org\<版>` に clone し、その場で `python tools/check.py` を通す。
2. 次の6か所の版のフォルダーを書き換える：(1) データフォルダーの `ai-org-home.txt`、(2) `%USERPROFILE%\.ai-org\config.json` の home、(3) git の共通設定 `core.hooksPath`、(4) `~/.claude/settings.json` のフックの args、(5) `~/.claude/CLAUDE.md` のパス、(6) `~/.codex/AGENTS.md` のパス。
3. 中継（データフォルダーの `*.py`）を新しい版の `legacy/forward.py` で更新する。
4. 戻すときは、2 の6か所を前の版に戻し、3 の中継も前の版の `legacy/forward.py` で置き直す。前の版のフォルダーは残しておく。

### レビュー（段階1）

- Claude 独立レビュー（Claude Code サブエージェント）：b38299fe…（重大指摘なし）、再確認 7ec1024e…（重大指摘なし）。
- Gemini の実モデルレビュー：2026-11-18、ユーザーの判断で当面なし。
