import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from case_editing import CaseEditing
from case_guide import (DEFAULT_PLAN, load_case_draft, next_step, parse_case_draft,
                        start_instruction, validate_case_fields)
from workspace_hub import CaseStore


def encode(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


class DraftTests(unittest.TestCase):
    def test_valid_draft_with_bom_and_optional_acceptance(self):
        draft = parse_case_draft(b"\xef\xbb\xbf" + encode({"title": " 資料 ", "objective": "作る\n2行目"}))
        self.assertEqual(draft, {"title": "資料", "objective": "作る\n2行目", "acceptance": ""})

    def test_rejects_bad_format_and_limits(self):
        bad = [
            b"\xff\xfe",                                   # not UTF-8
            b"{broken",                                     # not JSON
            b"[]",                                          # not an object
            b'{"title":"a","title":"b","objective":"x"}',   # duplicate key
            b'{"title":"a","objective":NaN}',               # non-standard constant
            encode({"title": "a"}),                         # missing objective
            encode({"title": 1, "objective": "x"}),         # wrong type
            encode({"title": "a", "objective": "x", "role": "Codex"}),  # unknown key
            encode({"title": "a" * 101, "objective": "x"}),
            encode({"title": "a\nb", "objective": "x"}),
            encode({"title": "a", "objective": "x" * 12001}),
            encode({"title": "a", "objective": "x", "acceptance": "y" * 12001}),
            encode({"title": "a", "objective": "x\x00"}),
            b'{"title":"a","objective":"\\ud800"}',         # lone surrogate
            b"[" * 100000 + b"]" * 100000,                  # too deep / too large
            b'{"title":"a","objective":' + b"[" * 50000 + b"]" * 50000 + b"}",
            b" " * 200001,
        ]
        for data in bad:
            with self.subTest(data=data[:40]), self.assertRaises(ValueError):
                parse_case_draft(data)

    def test_load_from_file(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "draft.json"
            path.write_bytes(encode({"title": "t", "objective": "o", "acceptance": "a"}))
            self.assertEqual(load_case_draft(path)["acceptance"], "a")
            with self.assertRaises(ValueError):
                load_case_draft(Path(temp))

    def test_create_rejects_surrogate_without_leaving_case(self):
        with TemporaryDirectory() as temp:
            store = CaseStore(Path(temp) / "cases")
            with self.assertRaises(ValueError):
                store.create("t", "\ud800")
            self.assertEqual(list(store.root.iterdir()), [])
        with self.assertRaises(ValueError):
            validate_case_fields("t", "o", None)


class RoleTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = CaseStore(Path(temp.name) / "cases")

    def test_create_saves_selected_plan_and_change_is_separate_from_claim(self):
        task = self.store.create("t", "o", plan="claude-implements")
        roles = self.store.roles(task["id"])
        self.assertEqual((roles["plan"], roles["saved"]), ("claude-implements", True))
        editing = CaseEditing(self.store, task["id"])
        token = editing.acquire("Codex session")  # plan does not restrict claim
        changed = self.store.set_roles(task["id"], "codex-implements", roles["revision"])
        self.assertEqual(changed["plan"], "codex-implements")
        self.assertEqual(editing.current()["agent"], "Codex session")  # claim untouched
        editing.release(token)
        with self.assertRaises(ValueError):  # stale screen
            self.store.set_roles(task["id"], "claude-implements", roles["revision"])
        for plan in (["codex-implements"], {"x": 1}, None, "other"):
            with self.subTest(plan=plan), self.assertRaises(ValueError):
                self.store.set_roles(task["id"], plan, changed["revision"])
            with self.assertRaises(ValueError):
                self.store.create("t", "o", plan=plan)

    def test_existing_case_without_roles_shows_default_and_can_save(self):
        task = self.store.create("t", "o")
        path = self.store.folder(task["id"]) / "ROLES.json"
        path.unlink()  # case created before this feature
        roles = self.store.roles(task["id"])
        self.assertEqual((roles["plan"], roles["saved"], roles["revision"]), (DEFAULT_PLAN, False, "default"))
        saved = self.store.set_roles(task["id"], "claude-implements", "default")
        self.assertTrue(saved["saved"])

    def test_corrupt_roles_are_reported_not_crashing(self):
        task = self.store.create("t", "o")
        path = self.store.folder(task["id"]) / "ROLES.json"
        for content in (b'{"case_id":"x","plan":["a"]}', b"\xff", b"[" * 100000,
                        encode({"case_id": task["id"], "schema_version": 1, "plan": ["codex-implements"]})):
            path.write_bytes(content)
            with self.subTest(content=content[:30]):
                roles = self.store.roles(task["id"])
                self.assertFalse(roles["saved"])
                self.assertTrue(roles["warning"])
        fixed = self.store.set_roles(task["id"], "codex-implements", roles["revision"])
        self.assertIsNone(fixed["warning"])


class SummaryTests(unittest.TestCase):
    def test_next_step_by_state(self):
        active = {"phase": "active", "needs_direction_confirmation": False}
        who, action = next_step("claude-implements", active, None)
        self.assertEqual(who, "Claude Code")
        self.assertIn("実装担当", action)
        who, action = next_step("codex-implements", active, {"agent": "Codex A"}, 2)
        self.assertEqual(who, "Codex A")
        self.assertIn("編集権を保持", action)
        self.assertNotIn("編集中", action)
        self.assertIn("2 件", action)
        self.assertIn("停止報告", next_step("codex-implements", {"phase": "pending"}, {"agent": "X"})[1])
        self.assertIn("再開", next_step("codex-implements", {"phase": "unassigned"}, None)[1])
        self.assertEqual(next_step("codex-implements", None, None)[0], "要確認")

    def test_instructions_name_role_and_single_review(self):
        text = start_instruction("implementer", "C:\\x", "case-1", "claude-implements")
        self.assertIn("実装担当（Claude Code）", text)
        review_id = "a" * 32
        text = start_instruction("reviewer", "C:\\x", "case-1", "claude-implements", review_id)
        self.assertIn("レビュー担当（Codex）", text)
        self.assertIn(review_id + ".zip だけ", text)
        self.assertIn("--review " + review_id, text)
        for bad in (None, "../x", "b" * 31):
            with self.assertRaises(ValueError):
                start_instruction("reviewer", "C:\\x", "case-1", "codex-implements", bad)


if __name__ == "__main__":
    unittest.main()
