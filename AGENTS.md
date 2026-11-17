# ai-org の開発ルール（Claude Code／Codex 共通）

このリポジトリは AI自律基盤 ai-org のコード。基盤の改修も、基盤の案件として進める。

- 案件：「ai-org：AI自律基盤の git 管理と必須化」（case-548945667cd645a5a2c60cb03a5f7b56）。データフォルダー `Documents\ChatGPT\AI駆動×AI駆動\app-relay\cases\` にある。
- 編集の前に、その案件で work-state を確認し、claim で編集権を取得し、方針の確認（confirm-direction）を記録する。コミット・push・ブランチ操作も編集に含める。作業を終えたら release する。手順の詳細は `docs/WORKSPACE_HUB.md` と案件フォルダーの AGENTS.md。
- 担当予定は案件の ROLES.json（ユーザーが画面で設定）に従う。AI は ROLES.json と `.editing` を編集しない。
- データ（cases、inbox、data、knowledge-vault、work-test）をリポジトリに入れない。テストは一時フォルダーを使う。
- 使う版（タグ）の切り替え、データフォルダーにある旧コードの置き換え、ユーザー設定（Claude Code・Codex・git の共通設定）の変更、GitHub への push は、項目ごとにユーザーの確認を得る。
- 中核（hub/）に開発固有の処理を入れない。開発向けの機能は拡張として分ける。
- Claude と Gemini の実モデルレビューを受け、重大指摘は解消して再確認を受ける。Codex のレビューはその代わりにならない。
- 確認コマンド：`cd hub && python -m unittest discover -p "test_*.py"`。
