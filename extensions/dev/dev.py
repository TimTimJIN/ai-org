"""ai-org の開発向け拡張。中核（hub/）の作業コマンドを、git・Claude Code・検証コマンドとつなぐ。

プロジェクト（開発リポジトリ）の直下に `.ai-org.json` を置いて案件と結び付ける：
  {"case": "case-…", "data": "<データフォルダーの絶対パス>",
   "status_files": ["STATUS.md"], "check": ["powershell", "-NoProfile", "-File", "tools/check.ps1"]}

コマンド：
  python dev.py finish --project <パス> --token-file <パス> [--status-unchanged] [--skip-check] [--allow-dirty]
      検証コマンド → リポジトリの STATUS の更新確認 → 未コミットの確認 → 中核の finish（案件の STATUS 確認・release）
  python dev.py git-guard <commit|push>      git フックから呼ぶ。AI_ORG_TOKEN_FILE のトークンを照合する
  python dev.py claude-guard [--data <パス>]  Claude Code の PreToolUse フックから呼ぶ（標準入力にフックの JSON）

利用者自身の手作業で確認を省くときは、環境変数 AI_ORG_SKIP_CLAIM_CHECK=1 を設定する（AI は利用者の指示なしに使わない）。
"""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
HUB = HERE.parent.parent / "hub"
sys.path.insert(0, str(HUB))

CONFIG = ".ai-org.json"
CASE_DIR = re.compile(r"case-[0-9a-f]{32}\Z")
STATUS_UPDATED = re.compile(r"^更新[：:]\s*(\d{4}-\d{2}-\d{2})")


# プロジェクト設定 ---------------------------------------------------------
def find_project(start):
    path = Path(start).resolve()
    for folder in [path] + list(path.parents):
        if (folder / CONFIG).is_file():
            return folder
    return None


def load_project(folder):
    config = json.loads((Path(folder) / CONFIG).read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not CASE_DIR.fullmatch(str(config.get("case", ""))):
        raise ValueError(f"{CONFIG} の case が不正です。")
    return config


def use_data(config_data=None):
    """データフォルダーを決める。環境変数 AI_ORG_DATA があればそれ、なければプロジェクト設定の data。"""
    if not os.environ.get("AI_ORG_DATA") and config_data:
        os.environ["AI_ORG_DATA"] = str(config_data)


def session_for(case_id):
    from session import Session
    return Session(case_id)


# finish -----------------------------------------------------------------
def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, encoding="utf-8")


def cmd_finish(args):
    project = Path(args.project).resolve()
    config = load_project(project)
    use_data(config.get("data"))
    notes = []
    if args.skip_check:
        notes.append("検証コマンドを省きました（--skip-check）。")
    elif config.get("check"):
        result = subprocess.run(config["check"], cwd=project)
        if result.returncode != 0:
            raise ValueError("検証コマンドが失敗しました。直してから終えてください。編集権は保持したままです。")
    today = date.today().isoformat()
    stale = []
    for name in config.get("status_files", []):
        try:
            lines = (project / name).read_text(encoding="utf-8").splitlines()[:10]
        except OSError:
            lines = []
        if not any((m := STATUS_UPDATED.match(line)) and m.group(1) == today for line in lines):
            stale.append(name)
    if stale:
        if not args.status_unchanged:
            raise ValueError(f"冒頭の「更新」行が今日でないファイルがあります：{'、'.join(stale)}。"
                             "状態が変わらない作業なら --status-unchanged を付けてください。")
        notes.append(f"更新していません（--status-unchanged）：{'、'.join(stale)}")
    dirty = [line for line in git(project, "status", "--porcelain").stdout.splitlines() if line.strip()]
    if dirty:
        if not args.allow_dirty:
            raise ValueError(f"未コミットの変更が {len(dirty)} 件あります。編集権を持ったままコミットするか、--allow-dirty を付けてください。")
        notes.append(f"未コミットの変更が {len(dirty)} 件あります（--allow-dirty）。")
    upstream = git(project, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if upstream.returncode != 0:
        notes.append("追跡先のブランチがないため、未 push のコミット数を確認できません。")
    else:
        ahead = [l for l in git(project, "log", "--oneline", "@{u}..HEAD").stdout.splitlines() if l.strip()]
        if ahead:
            notes.append(f"未 push のコミットが {len(ahead)} 件あります。push は利用者の承認を得てから行います。")
    notes += session_for(config["case"]).finish(args.token_file, args.status_unchanged)
    for note in notes:
        print(f"[ai-org] 注意：{note}")
    print("[ai-org] 編集権を返し、トークンファイルを消しました。")
    return 0


# git フック ---------------------------------------------------------------
def cmd_git_guard(args):
    if os.environ.get("AI_ORG_SKIP_CLAIM_CHECK") == "1":
        print("[ai-org] AI_ORG_SKIP_CLAIM_CHECK=1 のため、編集権の確認を省きました。")
        return 0
    top = git(Path.cwd(), "rev-parse", "--show-toplevel")
    project = find_project(top.stdout.strip()) if top.returncode == 0 else None
    if project is None or not (project / CONFIG).is_file():
        # 案件と結び付いていないリポジトリ。必須化（段階3）までは止めない。
        return 0
    config = load_project(project)
    use_data(config.get("data"))
    reason = session_for(config["case"]).block_reason(os.environ.get("AI_ORG_TOKEN_FILE"))
    if reason:
        print(f"[ai-org] {args.hook} を中止しました。{reason}", file=sys.stderr)
        print("  AI_ORG_TOKEN_FILE に、ai-org start で表示されたトークンファイルを、git と同じコマンドの中で設定してください。"
              " 利用者自身の作業なら AI_ORG_SKIP_CLAIM_CHECK=1 で確認を省けます。", file=sys.stderr)
        return 1
    print("[ai-org] 編集権を確認しました。")
    return 0


# Claude Code の編集前フック ------------------------------------------------
def claude_token_file(session_id, case_id):
    """この会話の一時フォルダー（%TEMP%\\claude\\*\\<session_id>\\scratchpad）にあるトークンファイル。"""
    if not session_id or not re.fullmatch(r"[A-Za-z0-9-]+", session_id):
        return None
    base = Path(tempfile.gettempdir()) / "claude"
    for folder in sorted(base.glob("*")) if base.is_dir() else []:
        candidate = folder / session_id / "scratchpad" / f"ai-org-{case_id}.token"
        if candidate.is_file():
            return candidate
    return None


def locate_case(target, data_root):
    """書き込み先がデータフォルダーの案件の中なら、(案件ID, 案件フォルダー) を返す。"""
    if data_root is None:
        return None, None
    cases = (Path(data_root) / "cases").resolve()
    try:
        relative = target.relative_to(cases)
    except ValueError:
        return None, None
    if relative.parts and CASE_DIR.fullmatch(relative.parts[0]):
        return relative.parts[0], cases / relative.parts[0]
    return None, None


def claude_decision(payload, data_arg=None):
    """止めるなら理由、許すなら None。"""
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return None
    target = Path(raw).resolve()
    project = find_project(target.parent if not target.is_dir() else target)
    config = load_project(project) if project else None
    data_root = os.environ.get("AI_ORG_DATA") or (config or {}).get("data") or data_arg
    case_id, case_folder = locate_case(target, data_root)
    if case_id:
        relative = target.relative_to(case_folder)
        if relative.parts and (relative.parts[0] == ".editing" or relative.parts == ("ROLES.json",)):
            return "ROLES.json と .editing は AI が編集しません（担当予定は利用者が案件画面で、編集権は基盤のコマンドで管理します）。"
    elif config:
        case_id = config["case"]
    else:
        return None  # 案件にも、案件と結び付いたリポジトリにも属さない（必須化は段階3）
    if payload.get("agent_id"):
        return "サブエージェントは、案件と結び付いたリポジトリと案件フォルダーに書き込みません（レビュー担当は review-note で返します）。"
    if data_root:
        use_data(data_root)
    token_file = claude_token_file(payload.get("session_id"), case_id)
    reason = session_for(case_id).block_reason(token_file)
    if reason:
        return (f"編集を止めました：{reason} 先に ai-org start を、--token-file に会話用の一時フォルダーの "
                f"ai-org-{case_id}.token を指定して実行してください。")
    return None


def cmd_claude_guard(args):
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        payload = json.loads(sys.stdin.read())
        reason = claude_decision(payload, args.data)
    except Exception as error:  # 想定外のエラーでも止める側に倒す
        reason = f"編集前の確認でエラーが起きたため止めました：{error}"
    if reason:
        print(reason, file=sys.stderr)
        return 2
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="ai-org の開発向け拡張")
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("finish")
    f.add_argument("--project", default=".")
    f.add_argument("--token-file", default=os.environ.get("AI_ORG_TOKEN_FILE") or None)
    f.add_argument("--status-unchanged", action="store_true")
    f.add_argument("--skip-check", action="store_true")
    f.add_argument("--allow-dirty", action="store_true")
    g = sub.add_parser("git-guard")
    g.add_argument("hook", choices=["commit", "push"])
    c = sub.add_parser("claude-guard")
    c.add_argument("--data", default=None)
    args = parser.parse_args(argv)
    if args.command == "claude-guard":
        return cmd_claude_guard(args)
    try:
        if args.command == "finish":
            if not args.token_file:
                raise ValueError("--token-file か AI_ORG_TOKEN_FILE を指定してください。")
            return cmd_finish(args)
        return cmd_git_guard(args)
    except (OSError, ValueError) as error:
        print(f"[ai-org] 中止：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
