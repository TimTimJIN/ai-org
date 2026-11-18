from datetime import date
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from case_editing import CaseEditing
from session import Session
from workspace_hub import CaseStore


class SessionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = CaseStore(self.root / "cases")
        self.case_id = self.store.create("Session", "Scope")["id"]
        self.tokens = self.root / "tokens"
        patcher = mock.patch.dict(os.environ, {"AI_ORG_TOKEN_DIR": str(self.tokens)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def session(self):
        return Session(self.case_id, self.store)

    def write_status(self, day):
        (self.store.folder(self.case_id) / "STATUS.md").write_text(f"# 作業状況\n\n更新: {day}（日本時間）\n", encoding="utf-8")

    def test_start_guard_finish_round_trip(self):
        token_file = self.root / "a" / "ai-org.token"
        result = self.session().start("Claude Code test", token_file)
        self.assertTrue(result["claimed"])
        self.assertTrue(token_file.is_file())
        self.assertIsNone(self.session().block_reason(token_file))
        # 別の会話（トークンなし・別のファイル）は止まる
        self.assertIn("トークンファイル", self.session().block_reason(None))
        self.assertIn("編集権を持っていません", self.session().block_reason(self.root / "other.token"))
        # STATUS が今日でなければ終われない
        self.write_status("2000-01-01")
        with self.assertRaises(ValueError):
            self.session().finish(token_file)
        self.write_status(date.today().isoformat())
        self.session().finish(token_file)
        self.assertFalse(token_file.exists())
        self.assertIsNone(CaseEditing(self.store, self.case_id).current())

    def test_status_unchanged_allows_finish_with_note(self):
        token_file = self.root / "t.token"
        self.session().start("A", token_file)
        notes = self.session().finish(token_file, status_unchanged=True)
        self.assertTrue(notes)

    def test_start_refuses_when_another_conversation_holds(self):
        self.session().start("First", self.root / "first.token")
        with self.assertRaises(ValueError):
            self.session().start("Second", self.root / "second.token")
        # 同じ担当名でも、トークンファイルが違えば引き継がない
        with self.assertRaises(ValueError):
            self.session().start("First", self.root / "first-again.token")
        # 同じトークンファイルなら再実行できる
        self.assertFalse(self.session().start("First", self.root / "first.token")["claimed"])

    def test_default_token_file_is_unique_and_outside_case(self):
        result = self.session().start("A")
        path = Path(result["token_file"])
        self.assertEqual(path.parent, self.tokens)
        self.assertNotIn(str(self.store.root), str(path))

    def test_paused_case_blocks_start_and_guard(self):
        token_file = self.root / "t.token"
        self.session().start("A", token_file)
        CaseEditing(self.store, self.case_id).request_pause()
        self.assertIn("停止中", self.session().block_reason(token_file))
        self.session().pause_ack(token_file)
        with self.assertRaises(ValueError):
            self.session().start("B", self.root / "b.token")

    def test_resumed_case_requires_direction_confirmation(self):
        editing = CaseEditing(self.store, self.case_id)
        asked = editing.request_pause()
        editing.resume(asked["request_id"], "新しい方針")
        token_file = self.root / "t.token"
        # start を使わずに claim した担当は、方針確認までは書き込めない
        token = editing.acquire("Manual")
        token_file.write_text(token, encoding="utf-8")
        self.assertIn("方針確認", self.session().block_reason(token_file))
        result = self.session().start("Manual", token_file)
        self.assertTrue(result["confirmed"])
        self.assertEqual(result["direction"], "新しい方針")
        self.assertIsNone(self.session().block_reason(token_file))

    def test_corrupt_records_block(self):
        token_file = self.root / "t.token"
        self.session().start("A", token_file)
        control = self.store.folder(self.case_id) / ".editing" / "work-control.json"
        control.write_text("{broken", encoding="utf-8")
        self.assertIn("読み取れません", self.session().block_reason(token_file))
        control.write_text(json.dumps({"state": "weird"}), encoding="utf-8")
        self.assertIn("読み取れません", self.session().block_reason(token_file))

    def test_token_write_failure_releases_claim(self):
        bad = self.root / "missing-dir-as-file"
        bad.write_text("x", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.session().start("A", bad / "t.token")
        self.assertIsNone(CaseEditing(self.store, self.case_id).current())


if __name__ == "__main__":
    unittest.main()
