# ai-org

Claude・Codex・ChatGPT などのAIが、役割を分けて同じ仕事を進めるための基盤（旧称 app-relay／AI Workspace Hub）。
案件ごとに目的と受け入れ条件を決め、編集権で同時編集を防ぎ、停止・再開、独立レビュー、引き継ぎを記録する。

## 構成

| 場所 | 中身 |
| --- | --- |
| `hub/` | 中核のコード（案件、編集権、停止・再開、レビュー、受信箱、案件画面）と自動テスト。旧 ChatRelay の試作（`app.py`、`core.py`、`native.py`、`uia.ps1`）も当面ここに置く |
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
- 使う版は、タグを取り出した別のフォルダー（例：`git worktree add %LOCALAPPDATA%\ai-org\v0.1.0 v0.1.0`）。データフォルダーの `ai-org-home.txt` がそこを指す。
- 開発中の変更が、使っている案件にすぐ効かないようにするため。戻すときは `ai-org-home.txt` を前の版に向ける。

## テスト

```bash
cd hub && python -m unittest discover -p "test_*.py"
```
