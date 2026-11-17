# 思考資産の記録機能（試作）

## 追補：2026-11-16 再開時

現在は19件のテストが合格。追加した記録はtrust=unverifiedを強制し、作者名や種別を承認の根拠にしません。supersedesで同一案件・同種別の旧記録を訂正でき、分岐訂正は拒否します。引き継ぎ文には生成時刻・SHA256・旧記録のcurrent=falseを含め、本文をJSONデータとして出力します。

1記録12,000文字、引き継ぎ32,000文字を超えると切り捨てず停止。`handoff autonomous-team --for-sharing`はprivate記録が1件でもあれば停止します。既存記録と新規記録の既定はprivateです。機密性の自動判定・作者認証・承認ワークフローは未実装で、shareableも入力者の申告値です。

保存は一時ファイルへflush/fsync後に確定。Windowsでは既存ファイルを置換しないrenameを使用します。多重ライターの訂正競合対策は未実装のため、単一ライターで使用します。今回のコード変更に対するClaude/Geminiの再レビューは未完了です。

ClaudeアプリのPro反映を確認し、空の`app-relay/work-test`を選択しました。Claude側のフォルダー変更許可画面でユーザー操作待ちです。Claudeによるファイル作成はまだ未実施です。

以下の説明とレビュー記録は初版時点を含みます。上記追補が現在の状態です。

UI/UX・実装担当：Codex。今回はコマンド操作のみ。既存中継GUIへの接続は未実装。

## 使い方

app-relayフォルダーで実行します。

```powershell
python seed_knowledge.py
python knowledge.py handoff autonomous-team
python knowledge.py export new-vault
python -m unittest discover -s . -v
```

`new-vault`は新規フォルダー名にしてください。出力したフォルダーをObsidianで保管庫として開けます。実際のObsidianアプリでの表示検証は未実施です。

新規記録は `python knowledge.py add record.json`。JSON必須項目はid、case、kind、title、body、author、sourceです。kindはdirection/decision/hypothesis/result/proposal。refsは同じ案件の既存記録IDの配列です。proposalにはrefs、expected_effect、effort、acceptanceも必要です。

記録IDは英小文字・数字・ハイフン・アンダースコア、80文字以内。訂正は別IDで新規記録し、refsで旧記録を参照してください。訂正の自動優先判定は未実装なので、引き継ぎ時に日付と出典を確認します。

## 保存先と正本

- 現在の試作：data/knowledge/recordsのJSONが正本。Markdownは閲覧・受け渡し用コピーです。
- 今後の提案：Obsidian＝知識、Notion＝進行、Drive＝成果物。採用・同期・競合解決は未実装。
- 既存Notion：https://app.notion.com/p/3f2f8d3da25e8077a8f4fcb83d86c29d
- 既存Drive：https://drive.google.com/drive/folders/1OuTI85Vchiv-aYpBEiQV79ZVr5ut5s-F

外部の既存データは変更していません。保管庫の場所は未確認です。読み取り結果が最新であるかは連携時に再確認します。

## 受け入れ条件と限界

記録追加→別AI向け引き継ぎ文→Markdown出力を確認します。同一IDや既存フォルダーを上書きせず、存在しない根拠参照を拒否します。目的候補は常にproposedとなり、それ自体で実行を許可しません。

自動知識抽出・目的候補の自動生成・検索ランキング・常駐実行・外部同期・同時書き込みや異常終了からの復旧は未実装です。現在は単一プロセスで利用する試作です。機密情報を自動収集せず、渡す記録を利用者が選びます。

今回追加した知識機能について、Claude（アプリ）とGemini（ブラウザー表示Flash-Lite）から設計要約へのレビューを受けました。コード全文のレビュー・修正後の再確認は未実施です。本番運用の完了条件は未達です。

## 今回のレビュー結果（2026-11-16）

Claude：https://claude.ai/chat/8008d32b-9f79-4aed-87e8-0a6925064c95

- 信頼区分と訂正関係がない。AIがdecision/resultを書くと誤情報を正本と誤認する可能性。人の承認とsupersedes参照が必要。
- 引き継ぎ文の注入・機密流出対策として、本文のデータ区切り、長さ制限、機密確認が必要。

Gemini：https://gemini.google.com/app/5ce6c9acae1bc1e6

- 提案から承認、実行への状態遷移が未実装。
- 訂正・同期・排他制御がない状態では、引き継ぎ時に情報が古い可能性がある。

対応状況：上記は未解消の開発課題として保持。現在のstatus=recordedは保存済みという意味だけで、承認済み・検証済みを意味しません。作者名・出典は入力値であり認証・検証していません。AIの記録を実行権限の根拠に使わないでください。今回の種別分類は認可制御ではありません。自動実行・外部同期は引き続き未実装です。

検証：既存15件、新規2件のテスト計17件合格。4件の初期記録を追加し、Markdown5ファイル（索引を含む）と引き継ぎ文を出力しました。実アプリへの自動往復とObsidian表示は検証対象外です。
`n## Artifact verification checkpoint`nClaude received the file creation request. The second Folder access request is awaiting the user. verify_work.py validates JSON content without executing it; 21 tests pass. The real artifact is not present yet. New verifier code has not yet received Claude/Gemini review.


## Local work verified
Claude created work-test/relay-proof.json through its app. ChatGPT independently verified the exact JSON contract and saved chatgpt-verification.json. Verification result was sent back to the same Claude session for read-back. This is an interactive ChatGPT-mediated workflow, not an unattended relay.
