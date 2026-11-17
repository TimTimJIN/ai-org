"""Seed this conversation's explicit direction, observed state and proposals once."""
from knowledge import add, export, records
from data_root import data_root

root = data_root() / 'data' / 'knowledge'
base = dict(case='autonomous-team', source='2026-11-16 本チャット', author='Codex')
items = [
 dict(id='user-direction', kind='direction', author='user (要約)', title='自律型AIチームの目的', body='ChatGPT・Claudeの双方が司令塔とPC作業を担当できるようにする。AI同士で方針・成果物を改善する。追加のモデルAPI課金を避け、既存会話の資産を活用する。将来はdots・muse等を追加し、AI自身から目的も提案する。Obsidian・Notion・Google Driveに知識を蓄積したい。'),
 dict(id='observed-state', kind='result', title='今回確認した基盤と未検証事項', body='NotionのAI業務基盤を読み取り、指示受付・経営報告・補助処理・正式方針ページへのリンクを確認した。Google DriveでAI業務基盤フォルダーを確認した。Obsidianの標準設定ファイルは見つからず保存先は未確認。既存中継プログラムは実送信を無効化した模擬版。今回の知識機能は中継GUI未接続で、外部サービスへの自動同期・常駐実行・実モデルからの自動抽出は未実装。', refs=['user-direction']),
 dict(id='storage-proposal', kind='proposal', title='知識・進行・成果物の正本を分ける', body='提案：Obsidianは判断理由と知識、Notionは案件とタスク、Driveは成果物を正本とし、共通案件IDとURLで結ぶ。現段階のJSON記録は試作内の正本、Markdownは出力コピー。Markdown編集からの取り込みは未実装。正式移行時に二重正本を解消する。', refs=['user-direction','observed-state'], expected_effect='AI交代時の説明のやり直しと情報の食い違いを減らす', effort='まず1案件。保存先・権限の確認と同期処理が必要。所要時間は未見積もり。', acceptance='別AIが同じ案件の目的・根拠・未解決事項と成果物を取得できる'),
 dict(id='next-objective', kind='proposal', title='最初の目的候補：AI同士で1つの成果物を引き継ぐ', body='Claudeがテスト用ファイルを作り、ChatGPTが検証し、Claudeが修正する。判断・検証結果・成果物の場所を記録し、司令塔を交代しても再開できるか確認する。この候補は今回Codexが作成したもので、自律提案エンジンの出力ではない。', refs=['user-direction','observed-state'], expected_effect='会話中継から実作業・知識蓄積までの最小経路を検証できる', effort='テスト用1ファイル・1案件。Claude側のPC作業機能確認が前提。', acceptance='両AIの実作業の証跡、別AIの検証結果、引き継ぎ後の再開を確認できる'),
]
known = {r['id'] for r in records(root)}
for item in items:
    if item['id'] not in known:
        add(root, dict(base, **item))
print('Recorded', len(records(root)), 'items')
