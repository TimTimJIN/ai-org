"""案件の写し（人が読むための一覧）を Markdown で作る（中核）。

正本はデータフォルダーの案件記録。この写しは Notion・Google Drive などに貼るためのもので、外部への書き込みはしない
（書き込みは、利用者の指示を受けた担当がコネクターなどで行う）。トークンやログは含めない。
"""
from datetime import datetime, timezone
from pathlib import Path
import re

from case_editing import CaseEditing
from workspace_hub import CaseStore

STATUS_LINE = re.compile(r"^(状態|担当|更新)[：:]\s*(.+)$")


def status_summary(folder):
    """STATUS.md の冒頭から「状態」「担当」「更新」を取り出す。"""
    summary = {}
    try:
        lines = (Path(folder) / "STATUS.md").read_text(encoding="utf-8").splitlines()[:15]
    except OSError:
        return summary
    for line in lines:
        match = STATUS_LINE.match(line.strip())
        if match and match.group(1) not in summary:
            summary[match.group(1)] = match.group(2).strip()
    return summary


def build_report(store=None, now=None):
    store = store or CaseStore()
    cases, warnings = store.list()
    stamp = (now or datetime.now(timezone.utc)).astimezone().strftime("%Y-%m-%d %H:%M")
    lines = [f"# 案件の一覧（{stamp} 時点の写し）", "",
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
        except (OSError, ValueError) as error:
            progress, holder = "記録を読めない", str(error)
        try:
            import json
            roles = json.loads((folder / "ROLES.json").read_text(encoding="utf-8"))
            planned = f"実装 {roles.get('implementer', '?')}／レビュー {roles.get('reviewer', '?')}"
        except (OSError, ValueError, AttributeError):
            planned = "未設定"
        reviews = len(list((folder / "reviews").glob("*.json"))) if (folder / "reviews").is_dir() else 0
        cell = lambda text: str(text).replace("|", "／").replace("\n", " ")
        lines.append(f"| {cell(task['title'])}<br>`{case_id}` | {cell(summary.get('状態', '（STATUS なし）'))} | "
                     f"{progress} | {cell(holder)} | {cell(planned)} | {cell(summary.get('更新', '—'))} | {reviews} 件 |")
    if warnings:
        lines += ["", "## 読み取れなかった案件", ""] + [f"- {warning}" for warning in warnings]
    return "\n".join(lines) + "\n"
