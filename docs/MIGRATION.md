# app-relay からの移行記録

## 段階1：リポジトリ化（2026-11-18）

- 取り込み元：`Documents\ChatGPT\AI駆動×AI駆動\app-relay`。移行前の控え：`AI駆動×AI駆動\app-relay_控え_20261118.zip`（SHA-256 `bf8d320ed6c875d30cdf7e037c2040704903db43077bd06a9fbc3fa79f8091e8`、ファイル107件）。
- 最初のコミット（bd9a991）で、コード（`*.py`、`uia.ps1`、`*.cmd`）を `hub/` に、文書（`*.md`）を `docs/` に、内容を変えずに置いた。データ（cases、inbox、data、knowledge-vault、work-test）とショートカット（`.lnk`）、`__pycache__` は取り込んでいない。
- コードとデータの分離：データの置き場所を `hub/data_root.py` に集め、環境変数 `AI_ORG_DATA` で指定するようにした。変更したのは `workspace_hub.py`（案件フォルダーの既定値）、`app.py`（ChatRelay のデータ）、`seed_knowledge.py`、`verify_work.py` の4ファイル。
- 旧コマンドの中継：`legacy/forward.py` を追加。

### 確認したこと

- 取り込み前の app-relay で自動テスト63件が成功。リポジトリでは、追加した5件を含む68件が成功し、テスト後に `hub/` にデータのフォルダーが作られないことを確認。
- 本番データの写し（一時フォルダー）に中継スクリプトを置き、次を確認した。本番のデータには触れていない。
  - 案件フォルダーから旧コマンド `python ../../workspace_hub.py work-state` が動く。
  - claim・release が写しの側にだけ記録される。
  - データフォルダーから draft-status、verify_work が動く。
  - 中継経由で案件画面（hub_ui）が起動し、5秒後もエラーなく動いている（画面の操作は未確認）。

### 未実施

- 本番のデータフォルダー（app-relay）のコードを中継スクリプトに置き換えること。使う版（タグ）を作ってから、ユーザーの確認を得て行う。
- GitHub への push。
- Claude・Gemini の実モデルレビュー。
