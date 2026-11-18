"""案件の写し（人が読むための一覧）を Markdown で作る（中核）。

正本はデータフォルダーの案件記録。この写しは Notion・Google Drive などに貼るためのもので、外部への書き込みはしない
（書き込みは、利用者の指示を受けた担当がコネクターなどで行う）。トークンや照合用の値、ログ、エラーの詳細は含めない。
案件フォルダーの外を指すファイル（リンクなど）は読まない。STATUS の欄は長さを切り詰める。
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from case_editing import CaseEditing
from workspace_hub import CaseStore

STATUS_LINE = re.compile(r"^(状態|担当|更新)[：:]\s*(.+)$")
MAX_CELL = 200
HEADER = "# 案件の一覧"
# report が作ったファイルだけに入る目印。上書きしてよいかは、この行があるかで決める
MARKER = "<!-- ai-org report: generated copy, safe to overwrite -->"
# 認証情報らしい長い文字列（16進・base64 風・よくある鍵の接頭辞）を写しに載せない
SECRET = re.compile(r"(?:sk-|ghp_|gho_|xox[bap]-|AKIA)[A-Za-z0-9_\-]{8,}"
                    r"|(?<![A-Za-z0-9-])(?!case-)[A-Za-z0-9+/=_\-]{32,}")  # 案件ID（case-…）は伏せない


def read_inside(folder, name):
    """案件フォルダーの中の通常のファイルだけを読む（リンクで外を指していれば読まない）。読めなければ None。"""
    path = Path(folder) / name
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(Path(folder).resolve()):
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, ValueError):  # UnicodeDecodeError も ValueError
        return None


def status_summary(folder):
    """STATUS.md の冒頭から「状態」「担当」「更新」を取り出す。"""
    summary = {}
    text = read_inside(folder, "STATUS.md")
    for line in (text or "").splitlines()[:15]:
        match = STATUS_LINE.match(line.strip())
        if match and match.group(1) not in summary:
            summary[match.group(1)] = match.group(2).strip()
    return summary


def cell(text):
    text = str(text).replace("|", "／").replace("\r", " ").replace("\n", " ")
    text = SECRET.sub("［伏せ字］", text)
    return text if len(text) <= MAX_CELL else text[:MAX_CELL] + "…"


def build_report(store=None, now=None):
    store = store or CaseStore()
    cases, warnings = store.list()
    stamp = (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [f"{HEADER}（{stamp} 時点の写し）", MARKER, "",
             "正本はデータフォルダーの案件記録。この一覧は写しで、ここを編集しても案件には反映されない。", "",
             "| 案件 | 状態（STATUS） | 進行 | 編集権 | 担当予定 | STATUS の更新 | レビュー記録 |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for task in cases:
        case_id = task["id"]
        folder = store.folder(case_id)
        summary = status_summary(folder)
        try:
            editing = CaseEditing(store, case_id)
            control = editing.control_view()
            owner = editing.current()
            progress = "停止中" if control["state"] == "paused" else "進行可"
            holder = owner["agent"] if owner else "空き"
        except (OSError, ValueError):
            progress, holder = "記録を読めない", "不明"
        try:
            roles = json.loads(read_inside(folder, "ROLES.json") or "")
            planned = f"実装 {roles.get('implementer', '?')}／レビュー {roles.get('reviewer', '?')}"
        except (ValueError, AttributeError):
            planned = "未設定"
        reviews = len(list((folder / "reviews").glob("*.json"))) if (folder / "reviews").is_dir() else 0
        lines.append(f"| {cell(task['title'])}<br>`{case_id}` | {cell(summary.get('状態', '（STATUS なし）'))} | "  # noqa: E501
                     f"{progress} | {cell(holder)} | {cell(planned)} | {cell(summary.get('更新', '—'))} | {reviews} 件 |")
    if warnings:
        # 詳細（パスやエラー文）は写しに載せない
        lines += ["", f"読み取れなかった案件が {len(warnings)} 件あります（詳細はデータフォルダーで確認）。"]
    return "\n".join(lines) + "\n"


def write_report(text, out, data_root):
    """写しをファイルに書く。データフォルダーの中には書かない。既存のファイルは、この一覧の写しのときだけ上書きする。"""
    path = Path(out).resolve()
    if path.is_relative_to(Path(data_root).resolve()):
        raise ValueError("写しはデータフォルダーの中には書きません（案件記録を壊さないため）。別の場所を指定してください。")
    if path.exists():
        try:
            head = path.read_text(encoding="utf-8").splitlines()[:2]
        except (OSError, ValueError):
            head = []
        if len(head) < 2 or head[1].strip() != MARKER:
            raise ValueError(f"{path} は report が作った写しではないため、上書きしません。")
    path.write_text(text, encoding="utf-8")
