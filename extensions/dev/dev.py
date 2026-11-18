"""ai-org の開発向け拡張。中核（hub/）の作業コマンドを、git・Claude Code・検証コマンドとつなぐ。

プロジェクト（開発リポジトリ）の直下に `.ai-org.json` を置いて案件と結び付ける：
  {"case": "case-…", "data": "<データフォルダーの絶対パス>",
   "status_files": ["STATUS.md"], "check": ["powershell", "-NoProfile", "-File", "tools/check.ps1"]}

コマンド：
  python dev.py finish --project <パス> --token-file <パス> [--status-unchanged] [--case-status-unchanged]
                       [--skip-check] [--allow-dirty]
      編集権の照合 → 検証コマンド → リポジトリの STATUS → 未コミット → 中核の finish（案件の STATUS・release）
  python dev.py register --project <パス> --case <案件ID> --token-file <パス> [--status-file …] [--check-json …]
  python dev.py git-guard <commit|push>      git フックから呼ぶ。AI_ORG_TOKEN_FILE のトークンを照合する
  python dev.py claude-guard                 Claude Code の PreToolUse フックから呼ぶ（標準入力にフックの JSON）

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
CASE_DIR = re.compile(r"case-[0-9a-f]{32}\Z", re.IGNORECASE)
STATUS_UPDATED = re.compile(r"^更新[：:]\s*(\d{4}-\d{2}-\d{2})")
CHECK_TIMEOUT = 1800


# プロジェクト設定 ---------------------------------------------------------
def find_project(start):
    path = Path(start)
    for folder in [path] + list(path.parents):
        if (folder / CONFIG).is_file():
            return folder
    return None


def load_project(folder):
    config = json.loads((Path(folder) / CONFIG).read_text(encoding="utf-8-sig"))
    if not isinstance(config, dict) or not CASE_DIR.fullmatch(str(config.get("case", ""))):
        raise ValueError(f"{CONFIG} の case が不正です。")
    return config


def set_data(folder):
    """中核にデータフォルダーを渡す（中核は AI_ORG_DATA を読む）。"""
    if folder:
        os.environ["AI_ORG_DATA"] = str(folder)


def session_for(case_id):
    from session import Session
    return Session(case_id)


# 必須化の方針（利用者の設定 %USERPROFILE%\.ai-org\config.json） ------------------
#   {"dev_roots": ["C:\\…\\2_programing\\git"], "exclude": ["C:\\…\\dotfiles"], "data": "C:\\…\\app-relay"}
# dev_roots の下にあって、案件と結び付いていない（.ai-org.json がない）リポジトリへの書き込み・コミット・push を止める。
# exclude に書いたフォルダーの下は対象外。設定ファイルがなければ、必須化は働かない。
def load_policy():
    path = Path(os.environ.get("AI_ORG_CONFIG") or Path.home() / ".ai-org" / "config.json")
    if not path.is_file():
        return None
    policy = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(policy, dict):
        raise ValueError(f"{path} の形式が不正です。")
    return policy


def is_under(path, root):
    try:
        normalize(path).relative_to(normalize(root))
        return True
    except ValueError:
        return False


def unregistered_reason(path, policy):
    if not policy:
        return None
    if any(is_under(path, folder) for folder in policy.get("exclude", [])):
        return None
    if any(is_under(path, root) for root in policy.get("dev_roots", [])):
        return ("案件と結び付いていない開発リポジトリです。新しい開発は案件から始めます："
                "下書きを受信箱に置いて利用者が案件画面で確定し、ai-org start で編集権を取ってから、"
                "dev.py register でリポジトリを案件に結び付けてください。開発ではないフォルダーなら、"
                "利用者が設定の exclude に加えます。")
    return None


# パスの正規化と案件フォルダーの判定 -----------------------------------------
LOCAL_UNC = re.compile(r"^\\\\(?:localhost|127\.0\.0\.1|\.|\?)\\(?:UNC\\(?:localhost|127\.0\.0\.1)\\)?([A-Za-z])\$(\\.*)?$",
                       re.IGNORECASE)


def normalize(raw):
    """\\\\?\\C:\\…、\\\\localhost\\C$\\… などを通常の形に直してから解決する。"""
    text = str(raw).replace("/", "\\")
    if text.startswith("\\\\?\\") and len(text) > 6 and text[5] == ":":
        text = text[4:]
    match = LOCAL_UNC.match(text)
    if match:
        text = match.group(1) + ":" + (match.group(2) or "\\")
    return Path(os.path.realpath(text))


def locate_case(target):
    """書き込み先が案件フォルダー（…\\cases\\case-<32桁>\\…）の中なら、(案件ID, 案件フォルダー) を返す。
    データフォルダーの設定に頼らず、フォルダーの形で判定する（設定がなくても見逃さないため）。"""
    for folder in [target] + list(target.parents):
        if CASE_DIR.fullmatch(folder.name) and folder.parent.name.lower() == "cases":
            return folder.name.lower(), folder
    return None, None


# finish -----------------------------------------------------------------
def git(project, *args):
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, encoding="utf-8")


def cmd_finish(args):
    project = Path(args.project).resolve()
    config = load_project(project)
    set_data(os.environ.get("AI_ORG_DATA") or config.get("data"))
    session = session_for(config["case"])
    # 編集権の照合を最初に行う（編集権のない会話に検証コマンドを動かさせない）
    from session import token_matches
    if not token_matches(session.editing.current(), args.token_file):
        raise ValueError("この会話は編集権を持っていません。")
    notes = []
    if args.skip_check:
        notes.append("検証コマンドを省きました（--skip-check）。")
    elif config.get("check"):
        try:
            result = subprocess.run(config["check"], cwd=project, timeout=CHECK_TIMEOUT)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f"検証コマンドが {CHECK_TIMEOUT} 秒で終わりませんでした。編集権は保持したままです。") from error
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
        notes.append(f"リポジトリの記録を更新していません（--status-unchanged）：{'、'.join(stale)}")
    status = git(project, "status", "--porcelain")
    if status.returncode != 0:
        raise ValueError(f"git の状態を確認できません：{status.stderr.strip()}")
    dirty = [line for line in status.stdout.splitlines() if line.strip()]
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
    notes += session.finish(args.token_file, args.case_status_unchanged)
    for note in notes:
        print(f"[ai-org] 注意：{note}")
    print("[ai-org] 編集権を返し、トークンファイルを消しました。")
    return 0


# register ---------------------------------------------------------------
def cmd_register(args):
    """開発リポジトリを案件に結び付ける（.ai-org.json を書く）。その案件の編集権を持つ会話だけが行える。"""
    project = Path(args.project).resolve()
    if (project / CONFIG).exists():
        raise ValueError(f"{project / CONFIG} はすでにあります。結び付けを変えるときは利用者に確認してください。")
    policy = load_policy() or {}
    data = os.environ.get("AI_ORG_DATA") or policy.get("data")
    if not data:
        raise ValueError("データフォルダーが分かりません。AI_ORG_DATA か設定の data を指定してください。")
    set_data(data)
    reason = session_for(args.case).block_reason(args.token_file)
    if reason:
        raise ValueError(reason)
    check = json.loads(args.check_json) if args.check_json else []
    if not isinstance(check, list) or not all(isinstance(part, str) for part in check):
        raise ValueError("--check-json は文字列の配列で指定してください。")
    config = {"case": args.case, "data": str(Path(data).resolve()), "status_files": args.status_file or [],
              "check": check}
    (project / CONFIG).write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ai-org] {project} を案件 {args.case} に結び付けました（{CONFIG}）。コミットに含めてください。")
    return 0


# git フック ---------------------------------------------------------------
def cmd_git_guard(args):
    if os.environ.get("AI_ORG_SKIP_CLAIM_CHECK") == "1":
        print("[ai-org] AI_ORG_SKIP_CLAIM_CHECK=1 のため、編集権の確認を省きました。")
        return 0
    top = git(Path.cwd(), "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        print(f"[ai-org] {args.hook} を中止しました。リポジトリの場所を確認できません。", file=sys.stderr)
        return 1
    toplevel = Path(top.stdout.strip())
    if not (toplevel / CONFIG).is_file():
        reason = unregistered_reason(toplevel, load_policy())
        if reason:
            print(f"[ai-org] {args.hook} を中止しました。{reason}", file=sys.stderr)
            return 1
        return 0  # 開発フォルダーの外、または除外したフォルダー
    config = load_project(toplevel)
    set_data(os.environ.get("AI_ORG_DATA") or config.get("data"))
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


def claude_decision(payload):
    """止めるなら理由、許すなら None。"""
    tool_input = payload.get("tool_input") or {}
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not raw:
        return None
    target = normalize(raw)
    case_id, case_folder = locate_case(target)
    if case_id:
        relative = target.relative_to(case_folder)
        if relative.parts and (relative.parts[0].lower() == ".editing" or
                               (len(relative.parts) == 1 and relative.parts[0].lower() == "roles.json")):
            return "ROLES.json と .editing は AI が編集しません（担当予定は利用者が案件画面で、編集権は基盤のコマンドで管理します）。"
        data_root = case_folder.parent.parent  # 案件フォルダーの形から決める（設定や環境変数に頼らない）
    else:
        project = find_project(target.parent)
        if project is None:
            if target.name == CONFIG:
                return None  # 結び付け（.ai-org.json）を書くのは許す。中身の案件の編集権は register と各フックで確かめる
            return unregistered_reason(target, load_policy())
        config = load_project(project)
        case_id = config["case"]
        data_root = config.get("data") or os.environ.get("AI_ORG_DATA")
        if not data_root:
            return f"{project / CONFIG} に data（データフォルダー）がないため、編集権を確認できません。"
    if payload.get("agent_id"):
        return "サブエージェントは、案件と結び付いたリポジトリと案件フォルダーに書き込みません（レビュー担当は review-note で返します）。"
    set_data(data_root)
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
        reason = claude_decision(payload)
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
    f.add_argument("--status-unchanged", action="store_true", help="リポジトリの STATUS の確認を省く")
    f.add_argument("--case-status-unchanged", action="store_true", help="案件の STATUS の確認を省く")
    f.add_argument("--skip-check", action="store_true")
    f.add_argument("--allow-dirty", action="store_true")
    g = sub.add_parser("git-guard")
    g.add_argument("hook", choices=["commit", "push"])
    sub.add_parser("claude-guard")
    r = sub.add_parser("register")
    r.add_argument("--project", default=".")
    r.add_argument("--case", required=True)
    r.add_argument("--token-file", default=os.environ.get("AI_ORG_TOKEN_FILE") or None)
    r.add_argument("--status-file", action="append")
    r.add_argument("--check-json", default=None)
    args = parser.parse_args(argv)
    if args.command == "claude-guard":
        return cmd_claude_guard(args)
    try:
        if args.command in ("finish", "register") and not args.token_file:
            raise ValueError("--token-file か AI_ORG_TOKEN_FILE を指定してください。")
        if args.command == "finish":
            return cmd_finish(args)
        if args.command == "register":
            return cmd_register(args)
        return cmd_git_guard(args)
    except (OSError, ValueError) as error:
        print(f"[ai-org] 中止：{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
