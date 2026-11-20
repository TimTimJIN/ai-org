"""Pure helpers for case drafts, role plans and the "next step" summary.

Nothing here launches an AI, runs commands, or sends data anywhere. The
functions only validate text and build strings shown on the local screen.
"""
import json
from pathlib import Path
import re

TITLE_MAX = 100
TEXT_MAX = 12000
DRAFT_MAX_BYTES = 200000
DRAFT_KEYS = ("title", "objective", "acceptance")
# Tab, LF and CR are allowed in body text; other control characters are not.
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# JSON "\ud800" style escapes can yield lone surrogates that cannot be saved as UTF-8.
SURROGATE = re.compile(r"[\ud800-\udfff]")
RECORD_ID = re.compile(r"[0-9a-f]{32}\Z")

CODEX, CLAUDE = "Codex", "Claude Code"
ROLE_PLANS = {
    # plan key: (implementer, reviewer)
    "codex-implements": (CODEX, CLAUDE),
    "claude-implements": (CLAUDE, CODEX),
}
DEFAULT_PLAN = "codex-implements"
# 交互：実装担当が作業を終える（編集権を返す）たびに、実装とレビューを入れ替える。
DEFAULT_ALTERNATE = True


def plan_label(plan, alternate=False):
    implementer, reviewer = ROLE_PLANS[plan]
    return f"実装 {implementer} → レビュー {reviewer}" + ("（交互）" if alternate else "")


def swapped_plan(plan):
    """The plan with implementer and reviewer exchanged."""
    implementer, reviewer = ROLE_PLANS[require_plan(plan)]
    return next(key for key, pair in ROLE_PLANS.items() if pair == (reviewer, implementer))


def agent_side(agent):
    """Which AI an agent name ("Claude Code ai-org 1234abcd", "Codex 会話名") belongs to, or None.

    Only the start of the name counts: the rest often holds a repository name
    that may itself contain "codex" or "claude".
    """
    name = (agent or "").strip().casefold()
    for side, word in ((CODEX, "codex"), (CLAUDE, "claude")):
        if name.startswith(word):
            return side
    return None


def require_plan(plan):
    if not isinstance(plan, str) or plan not in ROLE_PLANS:
        raise ValueError("役割の組み合わせが不正です。")
    return plan


def validate_case_fields(title, objective, acceptance=""):
    """Return stripped fields or raise ValueError with a user-facing message."""
    if not all(isinstance(value, str) for value in (title, objective, acceptance)):
        raise ValueError("案件名・依頼内容・完成の目安は文字列で指定してください。")
    if any(SURROGATE.search(value) for value in (title, objective, acceptance)):
        raise ValueError("UTF-8で保存できない文字（孤立したサロゲート）が含まれています。")
    title, objective, acceptance = title.strip(), objective.strip(), acceptance.strip()
    if not title or len(title) > TITLE_MAX:
        raise ValueError("案件名を1〜100文字で入力してください。")
    if "\n" in title or "\r" in title or "\t" in title or CONTROL.search(title):
        raise ValueError("案件名に改行や制御文字は使えません。")
    if not objective or len(objective) > TEXT_MAX or len(acceptance) > TEXT_MAX:
        raise ValueError("依頼内容は必須です。依頼内容と完成の目安は各12,000文字以内にしてください。")
    if CONTROL.search(objective) or CONTROL.search(acceptance):
        raise ValueError("依頼内容・完成の目安に制御文字が含まれています。")
    return title, objective, acceptance


def _reject_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"JSONに同じ項目「{key}」が複数あります。")
        seen[key] = value
    return seen


def _reject_constant(name):
    raise ValueError(f"JSONに使えない値 {name} が含まれています。")


def parse_case_draft(data):
    """Validate the bytes of a chat-made draft. The result is only a draft."""
    if len(data) > DRAFT_MAX_BYTES:
        raise ValueError("JSONファイルが200KBを超えています。")
    if data.startswith(b"\xef\xbb\xbf"):  # Notepad may save UTF-8 with a BOM.
        data = data[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("JSONファイルをUTF-8として読めません。UTF-8で保存し直してください。") from error
    try:
        value = json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except json.JSONDecodeError as error:
        raise ValueError(f"JSONの形式が不正です（{error.lineno}行 {error.colno}列）。") from error
    except RecursionError as error:
        raise ValueError("JSONの入れ子が深すぎます。title, objective, acceptance だけの平らな形にしてください。") from error
    if not isinstance(value, dict):
        raise ValueError("JSONの最上位は { } のオブジェクトにしてください。")
    unknown = sorted(set(value) - set(DRAFT_KEYS))
    if unknown:
        raise ValueError("JSONに未対応の項目があります: " + ", ".join(unknown[:5])
                         + "。使える項目は title, objective, acceptance だけです。")
    for key in ("title", "objective"):
        if key not in value:
            raise ValueError(f"JSONに必須項目「{key}」がありません。")
    for key in DRAFT_KEYS:
        if key in value and not isinstance(value[key], str):
            raise ValueError(f"JSONの「{key}」は文字列にしてください。")
    title, objective, acceptance = validate_case_fields(
        value["title"], value["objective"], value.get("acceptance", ""))
    return {"title": title, "objective": objective, "acceptance": acceptance}


def load_case_draft(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError("通常のファイルを選んでください。")
    with path.open("rb") as stream:
        data = stream.read(DRAFT_MAX_BYTES + 1)
    return parse_case_draft(data)


def draft_from_text(text):
    """Use a copied chat reply as an editable draft, without parsing its prose."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Claudeで依頼にしたい回答をコピーしてから押してください。")
    if len(text) > TEXT_MAX:
        raise ValueError("コピーした回答が12,000文字を超えています。依頼に使う部分を選んでコピーしてください。")
    title = text.strip().splitlines()[0]
    title = re.sub(r"^[#>*\s]+", "", title).strip("* `")[:TITLE_MAX]
    title, objective, acceptance = validate_case_fields(title or "Claudeからの依頼", text)
    return {"title": title, "objective": objective, "acceptance": acceptance}


def next_step(plan, control, owner, unreported=0):
    """Summarise who should act now and what the user should do next.

    `plan` is the planned role split; `owner` is the actual edit claim. They
    are deliberately independent: a plan never grants or blocks editing.
    """
    implementer, reviewer = ROLE_PLANS[plan]
    phase = (control or {}).get("phase")
    holder = owner["agent"] if owner else None
    if control is None:
        who, action = "要確認", "停止・再開の状態を確認できません。案件フォルダーの記録を確認してください。"
    elif phase == "pending":
        who = holder or implementer
        action = f"停止要求中です。{who} の停止報告を待ってください。"
    elif phase in {"acknowledged", "unassigned"}:
        who = "あなた（利用者）"
        action = "停止中です。内容を確認し「方針を確認して再開」を押してください。"
    elif control.get("needs_direction_confirmation") and holder:
        who = holder
        action = f"再開済みです。{holder} が再開時の方針を確認するのを待ってください。"
    elif holder:
        who = holder
        action = (f"{holder} が編集権を保持しています。区切りでレビュー用コピー（snapshot）が作成されたら、"
                  f"レビューIDを選んで {reviewer} に「レビュー担当への開始指示」を渡してください。")
    else:
        who = implementer
        action = f"{implementer} に「実装担当への開始指示」をコピーして渡してください。"
    if unreported:
        action += f"（反映報告のないコメント {unreported} 件）"
    return who, action


def start_instruction(kind, folder, case_id, plan, review_id=None):
    """Short text for the user to paste into Codex / Claude Code by hand.

    The reviewer text names exactly one snapshot chosen by the user, so a
    reviewer never picks an older or newer ZIP by guesswork.
    """
    implementer, reviewer = ROLE_PLANS[require_plan(plan)]
    if kind == "implementer":
        return (f"あなたはこの案件の実装担当（{implementer}）です。\n"
                f"案件フォルダー: {folder}\n案件ID: {case_id}\n"
                "AGENTS.md（Claude Code は CLAUDE.md）と TASK.json・STATUS.md・feedback を読み、"
                "claim で編集権を取得してから作業してください。work-state で停止要求を確認し、"
                f"区切りで snapshot を作成して {reviewer} のレビューに回してください。"
                "成果物は outputs、進捗は STATUS.md へ。")
    if kind == "reviewer":
        if not isinstance(review_id, str) or not RECORD_ID.fullmatch(review_id):
            raise ValueError("レビューIDを選んでください。")
        return (f"あなたはこの案件のレビュー担当（{reviewer}）です。\n"
                f"案件フォルダー: {folder}\n案件ID: {case_id}\nレビューID: {review_id}\n"
                f"AGENTS.md と TASK.json を読み、reviews\\{review_id}.zip だけを案件外へ展開して確認してください。"
                "他のZIPや元の案件ファイルは対象外で、編集しません。"
                f"結果は review-note --case {case_id} --review {review_id} で記録してください。")
    raise ValueError("指示の種類が不正です。")
