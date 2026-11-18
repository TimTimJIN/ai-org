"""ai-org の作業コマンド（中核）。

  python ai_org.py start     --case <案件ID> --agent <担当とセッション名> [--token-file <パス>]
  python ai_org.py status    --case <案件ID> [--token-file <パス>]
  python ai_org.py pause-ack --case <案件ID> --token-file <パス>
  python ai_org.py finish    --case <案件ID> --token-file <パス> [--status-unchanged]
  python ai_org.py guard     --case <案件ID> --token-file <パス>   （書き込んでよければ終了コード 0、だめなら 1）

--token-file を省くと、環境変数 AI_ORG_TOKEN_FILE を使う。start で省くと、一時フォルダーの ai-org\\ に一意の名前で作る。
トークンファイルの中身は表示・転記しない。データの置き場所は AI_ORG_DATA（data_root.py を参照）。
"""
import argparse
import json
import os
import sys

from session import Session


def main(argv=None):
    parser = argparse.ArgumentParser(description="ai-org の作業コマンド")
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report", help="全案件の一覧（人が読む写し）を Markdown で出す")
    rep.add_argument("--out", default=None, help="書き出すファイル。省くと画面に出す")
    rep.add_argument("--include-status", action="store_true",
                     help="STATUS の「状態」欄（自由記述）も載せる。機密を書いていないことを確かめてから使う")
    for name in ("start", "status", "pause-ack", "finish", "guard"):
        p = sub.add_parser(name)
        p.add_argument("--case", required=True)
        p.add_argument("--token-file", default=os.environ.get("AI_ORG_TOKEN_FILE") or None)
        if name == "start":
            p.add_argument("--agent", required=True)
        if name == "finish":
            p.add_argument("--status-unchanged", action="store_true")
        if name == "status":
            p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "report":
        try:
            from data_root import data_root
            from report import build_report, write_report
            text = build_report(include_status=args.include_status)
            if args.out:
                write_report(text, args.out, data_root())
                print(f"[ai-org] 案件の一覧を書き出しました：{args.out}")
            else:
                sys.stdout.reconfigure(encoding="utf-8")
                print(text, end="")
            return 0
        except (OSError, ValueError) as error:
            print(f"[ai-org] 中止：{error}", file=sys.stderr)
            return 1
    try:
        session = Session(args.case)
        if args.command == "guard":
            reason = session.block_reason(args.token_file)
            if reason:
                print(f"[ai-org] 書き込みを止めます：{reason}", file=sys.stderr)
                return 1
            print("[ai-org] 編集権を確認しました。")
            return 0
        if args.command == "status":
            view = session.view(args.token_file)
            if args.json:
                print(json.dumps(view, ensure_ascii=False))
            else:
                print(f"案件：{view['case']}　状態：{view['state']}（phase={view['phase']}）")
                if view["state"] == "paused":
                    print(f"停止要求ID：{view['request_id']}")
                print(f"方針（direction）：{view['direction']}")
                print(f"方針確認が必要：{view['needs_direction_confirmation']}")
                print("編集権の保持者：" + (f"{view['owner']}（{view['owner_since']}）" if view["owner"] else "なし"))
                print("この会話のトークン：" + ("有効" if view["mine"] else ("無効" if args.token_file else "未指定")))
            return 0
        if args.command == "start":
            result = session.start(args.agent, args.token_file)
            print("[ai-org] 編集権を取得しました。" if result["claimed"] else "[ai-org] この会話はすでに編集権を持っています。")
            if result["confirmed"]:
                print("[ai-org] 方針の確認を記録しました。")
            print(f"方針（direction）：{result['direction']}")
            print("  → この方針と、その後の利用者の指示（チャット・feedback）を照合してから書き込んでください。")
            print(f"トークンファイル：{result['token_file']}")
            print("  → 中身は表示・転記しないこと。以後のコマンドと git には、このパスを --token-file か"
                  " AI_ORG_TOKEN_FILE で渡してください。")
            return 0
        if not args.token_file:
            print("[ai-org] --token-file か AI_ORG_TOKEN_FILE を指定してください。", file=sys.stderr)
            return 1
        if args.command == "pause-ack":
            session.pause_ack(args.token_file)
            print("[ai-org] 停止を報告しました。待機のために会話を終えるなら、finish で編集権を返してください。")
            return 0
        if args.command == "finish":
            for note in session.finish(args.token_file, args.status_unchanged):
                print(f"[ai-org] 注意：{note}")
            print("[ai-org] 編集権を返し、トークンファイルを消しました。")
            return 0
    except (OSError, ValueError) as error:
        print(f"[ai-org] 中止：{error}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
