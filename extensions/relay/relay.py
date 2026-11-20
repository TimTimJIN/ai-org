"""ai-org の対話中継（relay）拡張：Claude と Codex に、実装とレビューを交互に自動で依頼する。

人が止められることが前提。中継は、AI に1通送る前と返答を待つ間に毎回つぎを確かめ、どれかに当たれば止まる：
  - 案件画面の「一時停止を要求」（案件の停止・再開の記録）
  - 停止ファイル（python relay.py stop --case <案件ID>）
  - レビューの往復・時間の上限、AI の「進められない」（RELAY: BLOCKED）
送ったもの・受け取ったものは、案件フォルダーの relay\\<実行ID>\\ に全文を残す。

つなぎ方（--mode）：
  app  既定。Claude と Codex のアプリの画面（Windows の UI Automation）に書き込み、返答を読む。
       利用者が決めた会話（--claude-title / --codex-title）が表示されているときだけ送る。違えば止まる。
  cli  Claude Code（claude.exe -p）と Codex（codex.exe exec）を、それぞれの定額プランで呼ぶ。

コマンド：
  python relay.py run --case <案件ID> --project <作業フォルダー> (--task <依頼> | --task-file <ファイル> | --next)
                      [--mode app|cli] [--claude-title <会話名>] [--codex-title <会話名>]
                      [--rounds N] [--max-reviews N] [--max-minutes N] [--turn-minutes N]
  python relay.py stop --case <案件ID>        次の送信の前（返答の待ち中を含む）で止める（停止ファイルを置く）
  python relay.py clear-stop --case <案件ID>  停止ファイルを消す（利用者が再開を決めたとき）
  python relay.py probe --side claude|codex   アプリの画面に、表示中の会話名と入力欄が見えるかを確かめる（送らない）
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
HOME = HERE.parent.parent
sys.path.insert(0, str(HOME / "hub"))

from case_guide import CLAUDE, CODEX, ROLE_PLANS  # noqa: E402

# 終わりの印：行頭の「RELAY: <印> <relay-id>」。relay-id は、どの依頼への返答かを示す（古い返答と取り違えない）。
MARKER = re.compile(r"^[ \t>*`]*RELAY:[ \t]*([A-Z_]+)(?:[ \t]+`?([0-9A-Za-z-]+))?", re.MULTILINE)
READY, BLOCKED, APPROVED, CHANGES, FINISHED = (
    "READY_FOR_REVIEW", "BLOCKED", "APPROVED", "CHANGES_REQUESTED", "FINISHED")
KNOWN = {READY, BLOCKED, APPROVED, CHANGES, FINISHED}
NEXT_TASK = ("案件の STATUS.md の「次の作業」から、いちばん優先度の高い1件を選んで進めてください。"
             "選んだ作業を返答の冒頭に書いてください。")
PS = ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "uia_relay.ps1")]


class RelayStopped(Exception):
    """人の停止・上限・AI の BLOCKED など、中継を止める理由。"""


def now():
    return datetime.now(timezone.utc).isoformat()


def find_marker(text, nonce=None):
    """最後の印（re.Match）。nonce を渡すと、その relay-id の付いた印だけを数える。"""
    found = [m for m in MARKER.finditer(text or "") if m.group(1) in KNOWN and (nonce is None or m.group(2) == nonce)]
    return found[-1] if found else None


def last_marker(text, nonce=None):
    match = find_marker(text, nonce)
    return match.group(1) if match else None


def slug(side):
    return "claude" if side == CLAUDE else "codex"


# 実行ファイルの場所 ---------------------------------------------------------
def newest(root, pattern):
    root = Path(root)
    found = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True) if root.is_dir() else []
    return found[0] if found else None


def find_exe(side):
    """アプリに同梱された新しい CLI を使う（PATH の古い単体版はモデル一覧を読めないことがある）。"""
    env = os.environ.get("AI_ORG_RELAY_CLAUDE" if side == CLAUDE else "AI_ORG_RELAY_CODEX")
    if env:
        return Path(env)
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    exe = (newest(local / "Claude-Data", "*/claude-code/*/*/claude.exe") if side == CLAUDE
           else newest(local / "OpenAI" / "Codex" / "bin", "*/codex.exe"))
    if exe is None:
        raise RelayStopped(f"{side} の実行ファイルが見つかりません。アプリを入れるか、環境変数で場所を指定してください。")
    return exe


# つなぎ方：CLI ----------------------------------------------------------------
class CliAdapter:
    """1つの AI との会話（2通目以降は同じ会話の続き）。権限は役割ごとに毎回指定する。"""

    def __init__(self, side, project, writable_dirs, timeout=3600, runner=subprocess.run):
        self.side, self.project, self.writable_dirs = side, Path(project), [str(d) for d in writable_dirs]
        self.timeout, self.runner, self.session = timeout, runner, None

    def describe(self):
        return f"{self.side}（CLI）"

    def check(self):
        find_exe(self.side)

    def send(self, prompt, role, should_stop=None):
        exe = str(find_exe(self.side))
        if self.side == CLAUDE:
            cmd = [exe, "-p", "--output-format", "json"]
            if role == "implementer":
                cmd += ["--add-dir", *self.writable_dirs, "--permission-mode", "acceptEdits",
                        "--allowedTools", "Read", "Edit", "Write", "Glob", "Grep", "Bash"]
            else:
                # 読み取りの道具だけ。利用者の設定（settings.json）の許可も合わさるので、完全な強制ではない（README）。
                cmd += ["--allowedTools", "Read", "Glob", "Grep", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
                        "Bash(git status:*)", "--disallowedTools", "Edit", "Write", "NotebookEdit"]
            if self.session:
                cmd += ["--resume", self.session]
            result = self.run(cmd, prompt, should_stop)
            try:
                data = json.loads(result.stdout)
            except ValueError as error:
                raise RelayStopped(f"Claude の出力を読めません：{result.stderr.strip()[:300]}") from error
            self.session = data.get("session_id") or self.session
            if data.get("is_error"):
                raise RelayStopped(f"Claude がエラーを返しました：{str(data.get('result'))[:300]}")
            return str(data.get("result") or "")
        # Codex：sandbox は resume でも効くよう、設定の上書き（-c）で毎回渡す。
        out = Path(tempfile.gettempdir()) / f"ai-org-relay-{secrets.token_hex(8)}.txt"
        mode = "workspace-write" if role == "implementer" else "read-only"
        config = ["-c", f'sandbox_mode="{mode}"']
        if role == "implementer":
            roots = ", ".join(json.dumps(d) for d in self.writable_dirs)
            config += ["-c", f"sandbox_workspace_write.writable_roots=[{roots}]"]
        cmd = [exe, "exec"] + (["resume", self.session] if self.session else []) + config + ["--json", "-o", str(out), "-"]
        try:
            result = self.run(cmd, prompt, should_stop)
            for line in result.stdout.splitlines():
                if '"thread.started"' in line:
                    self.session = json.loads(line).get("thread_id") or self.session
            if not out.is_file():
                errors = [line for line in result.stdout.splitlines() if '"error"' in line]
                raise RelayStopped("Codex が返答しませんでした：" + (errors[-1][:300] if errors else result.stderr.strip()[-300:]))
            return out.read_text(encoding="utf-8")
        finally:
            out.unlink(missing_ok=True)

    def run(self, cmd, prompt, should_stop=None):
        if self.runner is not subprocess.run:  # テスト用の差し替え
            return self.runner(cmd, input=prompt, cwd=self.project, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout)
        # 返答を待つ間も数秒ごとに人の停止を確かめ、止まったら AI のプロセスを終わらせる。
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out, \
                tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=self.project,
                                    text=True, encoding="utf-8", errors="replace")
            try:
                proc.stdin.write(prompt)
                proc.stdin.close()
                started = time.monotonic()
                while proc.poll() is None:
                    time.sleep(3)
                    if should_stop:
                        should_stop(waiting=True)
                    if time.monotonic() - started > self.timeout:
                        raise RelayStopped(f"{self.side} が {self.timeout} 秒で返答しませんでした。")
            except BaseException:
                # AI が起動したコマンド（テスト・ビルドなど）も残さないよう、プロセスの木ごと終わらせる。
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
                proc.kill()
                proc.wait()
                raise
            out.seek(0)
            err.seek(0)
            return subprocess.CompletedProcess(cmd, proc.returncode, out.read(), err.read())


# つなぎ方：アプリの画面 -----------------------------------------------------------
class AppAdapter:
    """アプリの画面に書き込み、返答を読む。決めた会話が表示されていなければ送らない（fail closed）。"""

    def __init__(self, side, title, poll=5, stable=20, idle_timeout=1800, refresh_after=45, call=None,
                 sleep=time.sleep, clock=time.monotonic):
        if not title:
            raise RelayStopped(f"{side} の会話名を指定してください（--{slug(side)}-title）。この会話にだけ送ります。")
        self.side, self.title = side, title
        self.poll, self.stable, self.idle_timeout = poll, stable, idle_timeout
        # 他の窓に隠れた窓は画面の文字が更新されない。印のないまま変わらない時間がこれを超えたら、
        # 一瞬だけ前面に出して読み直す（毎回は出さない：利用者の操作を奪うため）。
        self.refresh_after = refresh_after
        self.call, self.sleep, self.clock = call or self.powershell, sleep, clock

    def describe(self):
        return f"{self.side}（アプリ：{self.title}）"

    def powershell(self, request):
        # アプリが忙しいと、画面の読み取りが一時的に返らないことがある。読むだけなら3回まで試す。
        # 送る操作はやり直さない（二重に送るおそれがある）。
        tries = 3 if request["action"] != "send" else 1
        for attempt in range(tries):
            try:
                proc = subprocess.run(PS, input=json.dumps(request, ensure_ascii=False), capture_output=True,
                                      encoding="utf-8", errors="replace", timeout=90,
                                      creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                break
            except subprocess.TimeoutExpired as error:
                if attempt == tries - 1:
                    what = "送信" if request["action"] == "send" else "画面の読み取り"
                    raise RelayStopped(f"{self.side} の{what}が90秒で終わりませんでした。"
                                       + ("送れたかどうか、画面を確かめてください。" if request["action"] == "send" else "")) from error
        try:
            result = json.loads(proc.stdout.lstrip("﻿"))
        except ValueError as error:
            raise RelayStopped(f"{self.side} の画面を操作できません：{proc.stderr.strip()[:300]}") from error
        if not result.get("ok"):
            raise RelayStopped(f"{self.side} の画面：{result.get('error', '不明なエラー')}")
        return result

    def request(self, action, **values):
        return self.call({"action": action, "app": slug(self.side), "title": self.title, **values})

    def check(self):
        return self.request("read")

    def send(self, prompt, role, should_stop=None):
        found = re.search(r"relay-id: (\S+)\s*$", prompt)
        if not found:
            raise ValueError("送る文の最後に relay-id が必要です。")
        nonce = found.group(1)
        self.request("send", text=prompt, nonce=nonce)
        last, since, refreshed, gap = None, self.clock(), self.clock(), self.refresh_after
        while True:
            self.sleep(self.poll)
            if should_stop:
                should_stop(waiting=True)
            stale = (last is None or not find_marker(last, nonce)) and self.clock() - since >= self.refresh_after \
                and self.clock() - refreshed >= gap
            if stale:
                # 前面に出すたびに利用者の操作を奪うので、間隔を倍々に空ける（最大5分）。
                refreshed, gap = self.clock(), min(gap * 2, 300)
            text = self.request("read", refresh=stale)["text"]
            # アプリは見えている部分しか読ませないことがある（送った文が上に流れて読めなくなる）。
            # そのため、返答の終わりは「この relay-id の付いた印」で見分ける。返答の始まりは、
            # 送った文の relay-id が読めればその後ろ、読めなければ印の前の一定の長さ。
            # 送った文の中（転送した相手の文を含む）の印は数えない：送った文の末尾の relay-id より後ろだけを探す。
            # 送った文が画面の上に流れて読めないときは、画面全体（＝送った文より後ろ）を探す。
            tail = text.rfind(f"relay-id: {nonce}")
            start = tail + len(f"relay-id: {nonce}") if tail >= 0 else 0
            marker = find_marker(text[start:], nonce)
            if marker:
                reply = text[start:start + marker.end()].strip()
                if tail < 0:
                    reply = reply[-8000:]
            else:
                reply = text[-2000:]  # まだ終わっていない。変化の有無だけを見る。
            if reply != last:
                last, since = reply, self.clock()
            elif marker and self.clock() - since >= self.stable:
                return reply
            if self.clock() - since >= self.idle_timeout:
                raise RelayStopped(f"{self.side} の返答が {self.idle_timeout // 60} 分変わらず、終わりの印（RELAY: … {nonce}）もありません。")


# 中継 ---------------------------------------------------------------------
class Relay:
    def __init__(self, store, case_id, project, adapters, *, max_reviews=4, max_minutes=180,
                 clock=time.monotonic, home=HOME, data=None, stamp=None, head=None):
        from case_editing import CaseEditing

        self.store, self.case_id, self.project = store, case_id, Path(project)
        self.editing = CaseEditing(store, case_id)
        self.adapters, self.max_reviews, self.max_minutes = adapters, max_reviews, max_minutes
        self.clock, self.started = clock, clock()
        self.case = store.folder(case_id)
        self.relay_dir = self.case / "relay"
        self.run_id = stamp or datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        self.run_dir = self.relay_dir / self.run_id
        self.home, self.data = Path(home), Path(data or store.root.parent)
        self.head = head or self.git_head
        self.count = 0

    # 記録 ----------------------------------------------------------------
    def log(self, kind, **values):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        entry = {"at": now(), "kind": kind, **values}
        with (self.run_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
        heads = {"send": "→ 送信", "reply": "← 返答", "stop": "■ 停止", "start": "▶ 開始", "done": "✔ 終了"}
        if kind in heads:
            who = values.get("to") or values.get("from") or ""
            body = values.get("text") or values.get("reason") or ""
            with (self.run_dir / "transcript.md").open("a", encoding="utf-8") as stream:
                stream.write(f"\n## {heads[kind]} {who}（{entry['at']}）\n\n{body}\n")

    # 人の停止 -------------------------------------------------------------
    def stop_file(self):
        return self.relay_dir / "STOP"

    def should_stop(self, waiting=False):
        control = self.editing.control_view()
        if control["state"] != "active":
            raise RelayStopped("案件画面で一時停止が要求されました。" + ("相手の返答を待つのをやめました。" if waiting else ""))
        if self.stop_file().exists():
            raise RelayStopped("停止ファイル（relay stop）が置かれました。")
        if self.clock() - self.started > self.max_minutes * 60:
            raise RelayStopped(f"時間の上限（{self.max_minutes} 分）に達しました。")

    # 1通 -------------------------------------------------------------------
    def ask(self, side, role, prompt):
        self.should_stop()
        self.count += 1
        # 乱数を足す：相手に渡る文（実装担当の報告など）に、次の依頼の印を前もって書き込めないようにする。
        nonce = f"{self.run_id}-{self.count}-{secrets.token_hex(3)}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        report_file = self.run_dir / f"{nonce}.md"
        # 印の形は文の途中に書く（行頭に置くと、送った文そのものを返答の印と取り違える）。
        rules = (f"（返答の最後の行は、印のあとに空白と relay-id を付けて `RELAY: <印> {nonce}` の形にしてください。"
                 + (f"返答と同じ全文を \"{report_file}\" にも保存してください。画面では長い返答が途中までしか読めないため、"
                    "中継はこのファイルを相手に渡します。）" if role == "implementer" else "）"))
        # 先頭と末尾に同じ relay-id。読めれば、返答の始まりがここから分かる。
        text = f"relay-id: {nonce}\n" + prompt.rstrip() + f"\n\n{rules}\n\nrelay-id: {nonce}"
        self.log("send", to=side, role=role, text=text)
        reply = self.adapters[side].send(text, role, should_stop=self.should_stop)
        marker = last_marker(reply, nonce) or last_marker(reply)
        if role == "implementer" and report_file.is_file():
            # 画面から読めた部分より、AI が保存した全文を優先する（印は画面・CLI の返答のものを使う）。
            saved = report_file.read_text(encoding="utf-8", errors="replace").strip()
            if saved:
                reply = saved if find_marker(saved) else saved + f"\n\nRELAY: {marker} {nonce}"
        self.log("reply", **{"from": side}, role=role, marker=marker, text=reply)
        if marker is None:
            raise RelayStopped(f"{side} の返答に終わりの印（RELAY: …）がありません。記録を確認してください。")
        if marker == BLOCKED:
            raise RelayStopped(f"{side} が「進められない」（RELAY: BLOCKED）と返しました。記録の返答を確認してください。")
        return reply, marker

    # 依頼文 -----------------------------------------------------------------
    def token_file(self, side):
        """依頼文に書くトークンファイルの場所。Claude Code の編集前フックは、その会話の一時フォルダー
        （scratchpad）の ai-org-<案件ID>.token だけを見るので、Claude にはそこを使わせる。"""
        if side == CLAUDE:
            return f"<あなたの会話用の一時フォルダー（scratchpad）>\\ai-org-{self.case_id}.token"
        return str(Path(tempfile.gettempdir()) / "ai-org" / f"relay-{self.run_id}-{slug(side)}.token")

    def header(self, side, role, other, round_no):
        name = "実装担当" if role == "implementer" else "レビュー担当"
        return (f"【ai-org 自動中継】実行 {self.run_id}／ラウンド {round_no}\n"
                f"あなたは {side} で、この案件の{name}です（相手は {other}）。このメッセージは中継プログラムが送っています。\n"
                f"案件ID: {self.case_id}\n案件フォルダー: {self.case}\n作業フォルダー: {self.project}\n"
                "人が案件画面からいつでも止められます。作業の区切りで "
                f"`python \"{self.data / 'ai_org.py'}\" status --case {self.case_id}` を確認し、"
                "停止中なら新しい作業を始めず、最後の行に RELAY: BLOCKED と書いて止まってください。\n"
                "返答の最後の行には、指定した印（RELAY: で始まる行）を1つだけ書いてください。\n")

    def finish_command(self, side):
        token = self.token_file(side)
        if (self.project / ".ai-org.json").is_file():
            return (f"python \"{self.home / 'extensions' / 'dev' / 'dev.py'}\" finish --project \"{self.project}\" "
                    f"--token-file \"{token}\" --turn-done")
        return f"python \"{self.data / 'ai_org.py'}\" finish --case {self.case_id} --token-file \"{token}\" --turn-done"

    def implement_prompt(self, side, other, round_no, task):
        token = self.token_file(side)
        return (self.header(side, "implementer", other, round_no) +
                f"\n## 依頼\n{task}\n\n## 手順\n"
                f"1. 書き込みの前に `python \"{self.data / 'ai_org.py'}\" start --case {self.case_id} "
                f"--agent \"{side} relay {self.run_id}\" --token-file \"{token}\"` を実行する（この中継の中で一度だけ）。"
                "止められたら書き込まず、BLOCKED で理由を書く。\n"
                "2. 案件の AGENTS.md・STATUS.md と作業フォルダーの AGENTS.md（あれば）に従って実装し、検証する。\n"
                f"3. コミットは、git と同じコマンドの中で環境変数 AI_ORG_TOKEN_FILE を \"{token}\" に設定して行う。push はしない。\n"
                "4. 編集権はまだ返さない（レビューの後で返す）。\n"
                "5. 返答に、変更の要約・コミットID・検証の結果を書く。最後の行は、レビューに回せるなら "
                f"`RELAY: {READY}`、進められないなら `RELAY: {BLOCKED}`。\n")

    def fix_prompt(self, side, other, round_no, review):
        return (self.header(side, "implementer", other, round_no) +
                f"\n## {other} のレビュー（指摘）\n<<<\n{review}\n>>>\n\n"
                "重大な指摘を直し、検証し、コミットしてください（push はしない。編集権はまだ返さない）。"
                "直さない指摘は理由を書く。最後の行は "
                f"`RELAY: {READY}` か `RELAY: {BLOCKED}`。\n")

    def review_prompt(self, side, other, round_no, report, base):
        return (self.header(side, "reviewer", other, round_no) +
                f"\n## {other}（実装担当）の報告\n<<<\n{report}\n>>>\n\n## レビューの方法\n"
                f"作業フォルダーの変更（`git diff {base}..HEAD` と、未コミットの変更）を読み取りだけで確かめる。"
                "ファイルの変更・コミット・ai-org の start はしない。正しさ・テスト・案件の指示（AGENTS.md）に照らし、"
                "重大な問題は場所と理由を具体的に書く。\n最後の行は、重大な問題がなければ "
                f"`RELAY: {APPROVED}`、直してほしい点があれば `RELAY: {CHANGES}`。\n")

    def finish_prompt(self, side, other, round_no):
        return (self.header(side, "implementer", other, round_no) +
                f"\n## レビューで承認されました（{other}）\n"
                "1. 案件の STATUS.md（とリポジトリの記録があればそれも）の冒頭の「更新」行を今日にし、"
                f"今回の変更と「{other} のレビューで承認（中継 {self.run_id}）」を書く。必要ならコミットする（push はしない）。\n"
                f"2. `{self.finish_command(side)}` で編集権を返す（--turn-done で、次は実装とレビューが入れ替わる）。\n"
                f"最後の行は、返せたら `RELAY: {FINISHED}`、失敗したら `RELAY: {BLOCKED}` と理由。\n")

    # ラウンド ----------------------------------------------------------------
    def git_head(self):
        result = subprocess.run(["git", "-C", str(self.project), "rev-parse", "HEAD"], capture_output=True, text=True)
        return result.stdout.strip() or "HEAD"

    def run_round(self, round_no, task):
        roles = self.store.roles(self.case_id)
        if roles["warning"]:
            raise RelayStopped(roles["warning"])
        implementer, reviewer = ROLE_PLANS[roles["plan"]]
        base = self.head()
        self.log("round", round=round_no, implementer=implementer, reviewer=reviewer, base=base)
        prompt = self.implement_prompt(implementer, reviewer, round_no, task)
        for _ in range(self.max_reviews):
            report, marker = self.ask(implementer, "implementer", prompt)
            if marker != READY:
                raise RelayStopped(f"{implementer} の返答の印が想定外です（{marker}）。")
            review, verdict = self.ask(reviewer, "reviewer", self.review_prompt(reviewer, implementer, round_no, report, base))
            if verdict == APPROVED:
                _, done = self.ask(implementer, "implementer", self.finish_prompt(implementer, reviewer, round_no))
                if done != FINISHED:
                    raise RelayStopped(f"{implementer} が編集権を返したと報告しませんでした（{done}）。")
                return implementer, reviewer
            if verdict != CHANGES:
                raise RelayStopped(f"{reviewer} の返答の印が想定外です（{verdict}）。")
            prompt = self.fix_prompt(implementer, reviewer, round_no, review)
        raise RelayStopped(f"レビューの往復が上限（{self.max_reviews} 回）に達しました。人の判断を待ちます。")

    def run(self, task, rounds=1):
        lock = self.relay_dir / "RUNNING"
        self.relay_dir.mkdir(exist_ok=True)
        if self.stop_file().exists():
            raise RelayStopped("停止ファイルがあります。再開してよければ relay.py clear-stop を実行してください。")
        try:
            with lock.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps({"run": self.run_id, "pid": os.getpid(), "at": now()}))
        except FileExistsError as error:
            raise RelayStopped(f"この案件では別の中継が動いています（{lock}）。止まっていることを確かめてから消してください。") from error
        try:
            self.log("start", text=f"依頼：{task}\n回数：{rounds}\nつなぎ方：" +
                     "、".join(adapter.describe() for adapter in self.adapters.values()))
            for round_no in range(1, rounds + 1):
                implementer, reviewer = self.run_round(round_no, task if round_no == 1 else NEXT_TASK)
                self.log("done", text=f"ラウンド {round_no}：{implementer} が実装、{reviewer} が承認。")
            return self.run_dir
        except RelayStopped as error:
            self.log("stop", reason=str(error))
            raise
        finally:
            lock.unlink(missing_ok=True)


# コマンド -------------------------------------------------------------------
def build_adapters(args, store, case_id):
    if args.mode == "cli":
        tokens = Path(tempfile.gettempdir()) / "ai-org"
        tokens.mkdir(exist_ok=True)
        writable = [Path(args.project), store.folder(case_id), tokens]
        return {side: CliAdapter(side, args.project, writable, timeout=args.turn_minutes * 60) for side in (CLAUDE, CODEX)}
    return {CLAUDE: AppAdapter(CLAUDE, args.claude_title, idle_timeout=args.turn_minutes * 60),
            CODEX: AppAdapter(CODEX, args.codex_title, idle_timeout=args.turn_minutes * 60)}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Claude と Codex の実装・レビューを自動で中継する（人が止められる）")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--case", required=True)
    run.add_argument("--project", required=True, help="AI が作業するフォルダー（git リポジトリ）")
    group = run.add_mutually_exclusive_group(required=True)
    group.add_argument("--task")
    group.add_argument("--task-file")
    group.add_argument("--next", action="store_true", help="案件の STATUS.md の「次の作業」から進める")
    run.add_argument("--mode", choices=("app", "cli"), default="app")
    run.add_argument("--claude-title", help="app：Claude の画面で、中継に使う会話の名前")
    run.add_argument("--codex-title", help="app：Codex の画面で、中継に使う会話の名前")
    run.add_argument("--rounds", type=int, default=1, help="実装とレビューの組を何回続けるか（毎回、担当が入れ替わる）")
    run.add_argument("--max-reviews", type=int, default=4, help="1ラウンドのレビューの往復の上限")
    run.add_argument("--max-minutes", type=int, default=180)
    run.add_argument("--turn-minutes", type=int, default=60, help="1通の返答を待つ上限")
    for name in ("stop", "clear-stop"):
        sub.add_parser(name).add_argument("--case", required=True)
    probe = sub.add_parser("probe")
    probe.add_argument("--side", choices=("claude", "codex"), required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "probe":
            side = CLAUDE if args.side == "claude" else CODEX
            result = AppAdapter(side, "（確認のみ）").request("probe")
            print(json.dumps({k: v for k, v in result.items() if k != "ok"}, ensure_ascii=False, indent=2))
            return 0
        from workspace_hub import CaseStore
        store = CaseStore()
        store.read(args.case)
        stop = store.folder(args.case) / "relay" / "STOP"
        if args.command == "stop":
            stop.parent.mkdir(exist_ok=True)
            stop.write_text(now(), encoding="utf-8")
            print("[ai-org relay] 停止ファイルを置きました。中継は次の確認（数秒以内）で止まります。")
            return 0
        if args.command == "clear-stop":
            stop.unlink(missing_ok=True)
            print("[ai-org relay] 停止ファイルを消しました。")
            return 0
        if not 1 <= args.rounds <= 20 or not 1 <= args.max_reviews <= 10:
            raise RelayStopped("--rounds は1〜20、--max-reviews は1〜10 で指定してください。")
        task = (NEXT_TASK if args.next else
                Path(args.task_file).read_text(encoding="utf-8-sig") if args.task_file else args.task).strip()
        if not task:
            raise RelayStopped("依頼が空です。")
        adapters = build_adapters(args, store, args.case)
        for adapter in adapters.values():
            adapter.check()
        relay = Relay(store, args.case, args.project, adapters, max_reviews=args.max_reviews, max_minutes=args.max_minutes)
        print(f"[ai-org relay] 開始：{relay.run_id}　記録：{relay.run_dir}")
        print("[ai-org relay] 止めるとき：案件画面の「一時停止を要求」、または relay.py stop --case …")
        relay.run(task, args.rounds)
        print(f"[ai-org relay] 終了しました。記録：{relay.run_dir}")
        return 0
    except (RelayStopped, OSError, ValueError) as error:
        print(f"[ai-org relay] 止まりました：{error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("[ai-org relay] 利用者の操作で止めました。", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
