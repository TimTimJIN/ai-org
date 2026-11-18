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
3. データフォルダー（app-relay）に `ai-org-home.txt` を置き、使う版のフォルダーを絶対パスで書く。次のファイルを `legacy/forward.py` の写しに置き換える：`workspace_hub.py`、`hub_ui.py`、`app.py`、`knowledge.py`、`verify_work.py`、`seed_knowledge.py`。
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

### レビュー

- Claude 独立レビュー（Claude Code サブエージェント）：b38299fe…（重大指摘なし）、再確認 7ec1024e…（重大指摘なし）。
- Gemini の実モデルレビュー：2026-11-18、ユーザーの判断で当面なし。
