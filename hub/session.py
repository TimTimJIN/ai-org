"""作業の開始・状態確認・停止報告・終了を1つずつのコマンドにまとめる（中核。開発固有の処理は入れない）。

基盤の手順：work-state → claim → confirm-direction → 作業 → STATUS 更新 → release。
本人確認はトークンファイルで行う。トークンファイルは会話（セッション）ごとに別の場所に置き、作業中だけ保持する。
判定はすべて、案件の記録を読めないときや想定外のときに「止める」側に倒す。
"""
from datetime import date
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import tempfile
import uuid

from case_editing import CaseEditing
from workspace_hub import CaseStore

STATUS_UPDATED = re.compile(r"^更新[：:]\s*(\d{4}-\d{2}-\d{2})")


def default_token_dir():
    return Path(os.environ.get("AI_ORG_TOKEN_DIR") or Path(tempfile.gettempdir()) / "ai-org")


def read_token(token_file):
    path = Path(token_file)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def token_matches(owner, token_file):
    if owner is None or not token_file:
        return False
    token = read_token(token_file)
    if token is None:
        return False
    return secrets.compare_digest(owner["proof"], sha256(token.encode()).hexdigest())


class Session:
    def __init__(self, case_id, store=None):
        self.store = store or CaseStore()
        self.case_id = case_id
        self.editing = CaseEditing(self.store, case_id)

    # 状態 ---------------------------------------------------------------
    def view(self, token_file=None):
        control = self.editing.control_view()
        owner = self.editing.current()
        return {
            "case": self.case_id,
            "state": control["state"],
            "phase": control["phase"],
            "request_id": control.get("request_id"),
            "direction": control.get("direction", ""),
            "needs_direction_confirmation": control["needs_direction_confirmation"],
            "owner": owner["agent"] if owner else None,
            "owner_since": owner["since"] if owner else None,
            "mine": token_matches(owner, token_file),
            "token_file": str(token_file) if token_file else None,
        }

    def block_reason(self, token_file):
        """書き込んでよければ None、だめなら理由を返す。記録が壊れていても理由を返す（止める）。"""
        try:
            control = self.editing.control_view()
            owner = self.editing.current()
        except (OSError, ValueError) as error:
            return f"案件の記録を読み取れません：{error}"
        if control["state"] != "active":
            return "案件が停止中です。案件画面で再開されるまで書き込みません。"
        if owner is None:
            return "誰も編集権を持っていません。ai-org start で編集権を取得してください。"
        if not token_file:
            return f"この会話のトークンファイルが指定されていません（現在の保持者：{owner['agent']}）。"
        if not token_matches(owner, token_file):
            return (f"この会話は編集権を持っていません（現在の保持者：{owner['agent']}）。"
                    "異常終了した会話の編集権は、基盤の recover 手順で復旧してください。")
        if control["needs_direction_confirmation"]:
            return "再開後の方針確認（confirm-direction）が未記録です。ai-org start を実行してください。"
        return None

    # 開始 ---------------------------------------------------------------
    def start(self, agent, token_file=None):
        control = self.editing.control_view()
        if control["state"] != "active":
            raise ValueError(f"案件が停止中です（phase={control['phase']}、停止要求ID={control.get('request_id')}）。"
                             "新しい作業を始めず、途中成果物と未完了事項を利用者に示してください。")
        owner = self.editing.current()
        if owner is not None and not token_matches(owner, token_file):
            raise ValueError(f"編集権は {owner['agent']} が持っています。前の担当（異常終了した会話を含む）の"
                             "編集権を勝手に解除せず、基盤の recover 手順に従ってください。")
        claimed = False
        if owner is None:
            if not token_file:
                token_file = default_token_dir() / f"{self.case_id}-{uuid.uuid4().hex}.token"
            token_file = Path(token_file)
            token = self.editing.acquire(agent)
            claimed = True
            try:
                token_file.parent.mkdir(parents=True, exist_ok=True)
                token_file.write_text(token, encoding="utf-8")
                if read_token(token_file) != token:
                    raise OSError("トークンを書き込んだ内容を確認できません。")
            except OSError as error:
                # トークンを保存できないまま編集権が残らないよう、すぐに返す。
                try:
                    self.editing.release(token, complete_turn=False)
                except (OSError, ValueError) as release_error:
                    raise ValueError(f"トークンファイルを保存できず（{error}）、編集権も返せませんでした（{release_error}）。"
                                     "誰もトークンを持たない編集権が残っています。利用者に知らせ、基盤の recover 手順で"
                                     "復旧してください。") from error
                raise ValueError(f"トークンファイルを保存できなかったため、編集権を返しました：{error}") from error
        confirmed = False
        # 再開されたことのある案件では、今の編集権で方針の確認を記録する（記録済みなら何もしない）。
        if "resumed_at" in control:
            self.editing.confirm_direction(read_token(token_file), control["request_id"])
            confirmed = True
        try:
            turn = self.store.turn_note(self.case_id, agent)
        except (OSError, ValueError) as error:
            turn = f"担当予定を読み取れません：{error}"
        return {"claimed": claimed, "confirmed": confirmed, "token_file": str(token_file),
                "direction": control.get("direction", ""), "turn": turn}

    # 停止報告 -----------------------------------------------------------
    def pause_ack(self, token_file):
        control = self.editing.control_view()
        if control["phase"] != "pending":
            raise ValueError(f"報告が必要な停止要求はありません（phase={control['phase']}）。")
        token = read_token(token_file)
        if token is None:
            raise ValueError("トークンファイルを読めません。")
        self.editing.acknowledge_pause(token, control["request_id"])

    # 終了 ---------------------------------------------------------------
    def status_is_current(self, today=None):
        """案件の STATUS.md の冒頭10行にある「更新」行が今日か。"""
        today = (today or date.today()).isoformat()
        path = self.store.folder(self.case_id) / "STATUS.md"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[:10]
        except OSError:
            return False
        return any((m := STATUS_UPDATED.match(line)) and m.group(1) == today for line in lines)

    def finish(self, token_file, status_unchanged=False, today=None, keep_turn=False):
        token = read_token(token_file)
        if token is None or not token_matches(self.editing.current(), token_file):
            raise ValueError("この会話は編集権を持っていません。")
        notes = []
        if not self.status_is_current(today):
            if not status_unchanged:
                raise ValueError("案件の STATUS.md 冒頭の「更新」行が今日ではありません。記録を更新してから終えてください。"
                                 "状態が変わらない作業なら --status-unchanged を付けてください。")
            notes.append("案件の STATUS.md を更新していません（--status-unchanged）。")
        note = self.editing.release(token, complete_turn=not keep_turn)
        if note:
            notes.append(note)
        elif keep_turn:
            notes.append("作業の途中として終えました（--keep-turn）。担当予定は入れ替えていません。")
        try:
            Path(token_file).unlink()
        except OSError as error:
            notes.append(f"トークンファイルを消せませんでした：{error}")
        return notes
