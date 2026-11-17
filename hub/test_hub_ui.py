import json
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import patch

from case_editing import CaseEditing
from case_guide import plan_label
from hub_ui import Hub, NewCaseDialog
from workspace_hub import CaseStore


class HubUiTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.temp = Path(temp.name)
        self.store = CaseStore(self.temp / "cases")
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tk unavailable: {error}")
        self.addCleanup(self.root.destroy)
        patcher = patch("hub_ui.messagebox")
        self.messagebox = patcher.start()
        self.addCleanup(patcher.stop)
        self.messagebox.askyesno.return_value = True

    def visible(self, window, widget):
        bottom = widget.winfo_rooty() + widget.winfo_height()
        right = widget.winfo_rootx() + widget.winfo_width()
        return (widget.winfo_ismapped() and widget.winfo_height() > 1
                and bottom <= window.winfo_rooty() + window.winfo_height()
                and right <= window.winfo_rootx() + window.winfo_width())

    def test_buttons_stay_visible_at_minimum_size(self):
        self.store.create("案件", "目的")
        hub = Hub(self.root, self.store)
        self.root.geometry("920x620")
        self.root.update()
        for widget in (hub.save, hub.copy_impl, hub.copy_review, hub.open_outputs_button, hub.paste_claude_button,
                       hub.pause_button, hub.resume_button, hub.role_save, *hub.actions):
            self.assertTrue(self.visible(self.root, widget), widget.cget("text"))
        dialog = NewCaseDialog(hub)
        dialog.dialog.geometry("520x440")
        self.root.update()
        self.assertTrue(self.visible(dialog.dialog, dialog.create_button))

    def test_json_draft_is_editable_and_only_created_on_button(self):
        hub = Hub(self.root, self.store)
        draft = self.temp / "draft.json"
        draft.write_text(json.dumps({"title": "チャット案件", "objective": "下書き", "acceptance": "条件"},
                                    ensure_ascii=False), encoding="utf-8")
        dialog = hub.new_case()
        self.assertTrue(dialog.load_draft(draft))
        self.assertEqual(self.store.list()[0], [])  # draft only
        self.assertEqual(dialog.values(), ("チャット案件", "下書き", "条件"))
        dialog.title.insert("end", "（編集）")
        dialog.plan.set("claude-implements")
        task = dialog.create()
        self.assertEqual(task["title"], "チャット案件（編集）")
        self.assertEqual(self.store.roles(task["id"])["plan"], "claude-implements")
        self.assertEqual(hub.role_choice.get(), plan_label("claude-implements"))
        self.assertIn("Claude Code", hub.next_label.get())

    def test_invalid_json_keeps_typed_input(self):
        hub = Hub(self.root, self.store)
        bad = self.temp / "bad.json"
        bad.write_text('{"title": "x", "objective": "y", "role": "Codex"}', encoding="utf-8")
        dialog = hub.new_case()
        dialog.title.insert(0, "手入力")
        self.assertFalse(dialog.load_draft(bad))
        self.messagebox.showerror.assert_called()
        self.assertEqual(dialog.values()[0], "手入力")

    def test_inbox_draft_becomes_one_case_and_copies_start_instruction(self):
        draft_id = self.store.queue_draft(b'{"title":"Inbox test","objective":"Build"}')
        hub = Hub(self.root, self.store)
        self.assertEqual(self.store.list()[0], [])
        dialog = NewCaseDialog(hub)
        dialog.open_inbox_draft(draft_id, self.store.inbox_draft(draft_id))
        dialog.plan.set("claude-implements")
        copied = []
        hub.copy = copied.append
        self.assertEqual(self.store.draft_status(draft_id)["status"], "pending")
        task = dialog.create()
        self.assertEqual(copied, [])
        resolved = self.store.draft_status(draft_id)
        self.assertEqual(resolved["case_id"], task["id"])
        self.assertEqual(resolved["implementer"], "Claude Code")
        self.assertEqual(resolved["work_phase"], "active")
        self.assertEqual(self.store.pending_drafts(), ([], 0))
        with self.assertRaises(ValueError):
            self.store.create("Again", "Build", draft_id=draft_id)

    def test_inbox_can_still_create_and_copy_for_another_conversation(self):
        draft_id = self.store.queue_draft(b'{"title":"Inbox test","objective":"Build"}')
        hub = Hub(self.root, self.store)
        dialog = NewCaseDialog(hub)
        dialog.open_inbox_draft(draft_id, self.store.inbox_draft(draft_id))
        copied = []
        hub.copy = copied.append
        task = dialog.create(copy_instruction=True)
        self.assertIn(task["id"], copied[0])

    def test_plain_claude_reply_fills_editable_draft_without_saving(self):
        hub = Hub(self.root, self.store)
        reply = "## 営業資料の作成\n\n顧客向けに日本語で作成する。"
        with patch.object(self.root, "clipboard_get", return_value=reply):
            dialog = hub.import_claude_reply()
        self.assertEqual(dialog.values(), ("営業資料の作成", reply, ""))
        self.assertEqual(dialog.plan.get(), "claude-implements")
        self.assertEqual(self.store.list()[0], [])
        copied = []
        hub.copy = copied.append
        task = dialog.create(copy_instruction=True)
        self.assertEqual(self.store.read(task["id"])["objective"], reply)
        self.assertIn("Claude Code", copied[0])

    def test_empty_claude_clipboard_does_not_open_or_save_a_draft(self):
        hub = Hub(self.root, self.store)
        with patch.object(self.root, "clipboard_get", side_effect=tk.TclError):
            self.assertIsNone(hub.import_claude_reply())
        self.messagebox.showerror.assert_called_once()
        self.assertEqual(self.store.list()[0], [])

    def test_unsaved_role_change_is_not_carried_to_new_case(self):
        first = self.store.create("A", "目的")
        hub = Hub(self.root, self.store)
        self.assertEqual(hub.selected, first["id"])
        hub.role_choice.set(plan_label("claude-implements"))
        self.assertTrue(hub.role_dirty())
        dialog = hub.new_case()
        dialog.title.insert(0, "B")
        dialog.objective.insert("1.0", "目的")
        self.assertIsNone(dialog.create())  # blocked until resolved
        self.assertEqual(len(self.store.list()[0]), 1)
        hub.role_choice.set(plan_label("codex-implements"))
        task = dialog.create()
        self.assertEqual(hub.selected, task["id"])
        self.assertFalse(hub.role_dirty())
        self.assertEqual(hub.roles["plan"], "codex-implements")
        self.assertEqual(self.store.roles(first["id"])["plan"], "codex-implements")

    def test_role_save_existing_case_and_stale_rejection(self):
        task = self.store.create("A", "目的")
        (self.store.folder(task["id"]) / "ROLES.json").unlink()
        hub = Hub(self.root, self.store)
        self.assertEqual(hub.role_state.get(), "既定値（未保存）")
        token = CaseEditing(self.store, task["id"]).acquire("Codex")
        hub.role_choice.set(plan_label("claude-implements"))
        hub.save_roles()
        self.assertEqual(self.store.roles(task["id"])["plan"], "claude-implements")
        self.assertEqual(CaseEditing(self.store, task["id"]).current()["agent"], "Codex")
        self.assertIn("Codex が保持", hub.owner_label.get())
        self.assertIn("編集権を保持", hub.next_label.get())
        # Another window changes the plan; this screen must not overwrite it.
        self.store.set_roles(task["id"], "codex-implements", self.store.roles(task["id"])["revision"])
        hub.role_choice.set(plan_label("claude-implements"))
        hub.save_roles()
        self.messagebox.showerror.assert_called()
        self.assertEqual(self.store.roles(task["id"])["plan"], "codex-implements")
        CaseEditing(self.store, task["id"]).release(token)

    def test_reviewer_instruction_requires_chosen_review_id(self):
        task = self.store.create("A", "目的")
        hub = Hub(self.root, self.store)
        self.assertIsNone(hub.choose_review())
        self.messagebox.showinfo.assert_called()
        editing = CaseEditing(self.store, task["id"])
        token = editing.acquire("Codex")
        (editing.case / "outputs" / "a.txt").write_text("x", encoding="utf-8")
        first = editing.review(token, ["outputs/a.txt"]).stem
        second = editing.review(token, ["outputs/a.txt"]).stem
        dialog = hub.choose_review()
        dialog.copy_selected()  # nothing chosen -> no copy
        self.assertTrue(dialog.winfo_exists())
        label = next(text for text, rid in dialog.labels.items() if rid == first)
        dialog.choice.set(label)
        dialog.copy_selected()
        copied = self.root.clipboard_get()
        self.assertIn(first, copied)
        self.assertNotIn(second, copied)
        hub.copy_start("implementer")
        self.assertIn("実装担当（Codex）", self.root.clipboard_get())

    def test_start_instruction_refreshes_before_copying_a_changed_plan(self):
        task = self.store.create("A", "目的")
        hub = Hub(self.root, self.store)
        copied = []
        hub.copy = copied.append
        self.store.set_roles(task["id"], "claude-implements", hub.roles["revision"])
        hub.copy_start("implementer")
        self.assertEqual(copied, [])
        self.assertEqual(hub.role_choice.get(), plan_label("claude-implements"))
        hub.copy_start("implementer")
        self.assertIn("実装担当（Claude Code）", copied[0])

    def test_pause_resume_and_comment_still_work(self):
        task = self.store.create("A", "目的")
        hub = Hub(self.root, self.store)
        hub.pause_work()
        self.assertEqual(hub.work_state["phase"], "unassigned")
        self.assertIn("再開", hub.next_label.get())
        hub.comment.insert("1.0", "修正")
        hub.add_comment()
        self.assertEqual(len(self.store.details(task["id"])[2]), 1)
        self.assertIn("1 件", hub.next_label.get())
        self.assertTrue(hub.outputs_folder().samefile(self.store.folder(task["id"]) / "outputs"))


if __name__ == "__main__":
    unittest.main()
