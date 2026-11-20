"""交互の担当予定：実装担当が番を終えた（--turn-done）ときだけ、実装とレビューを入れ替える。

Codex と Claude Code のどちらが終えても、同じ中核の処理（CaseEditing.release）を通る。
"""
from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from case_editing import CaseEditing
from case_guide import CLAUDE, CODEX, agent_side, plan_label, swapped_plan
from session import Session
from workspace_hub import CaseStore

HUB = Path(__file__).resolve().parent


class AlternateTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = CaseStore(self.root / "cases")
        self.case_id = self.store.create("交互", "Scope", plan="claude-implements")["id"]
        patcher = mock.patch.dict(os.environ, {"AI_ORG_TOKEN_DIR": str(self.root / "tokens")})
        patcher.start()
        self.addCleanup(patcher.stop)
        (self.store.folder(self.case_id) / "STATUS.md").write_text(
            f"# 作業状況\n\n更新: {date.today().isoformat()}\n", encoding="utf-8")

    def plan(self):
        return self.store.roles(self.case_id)["plan"]

    def finish(self, agent, **options):
        token_file = self.root / f"{uuid_like(agent)}.token"
        session = Session(self.case_id, self.store)
        session.start(agent, token_file)
        return session.finish(token_file, **options)

    def test_helpers(self):
        self.assertEqual(swapped_plan("claude-implements"), "codex-implements")
        self.assertEqual(swapped_plan("codex-implements"), "claude-implements")
        self.assertEqual(agent_side("Claude Code ai-org 1234abcd"), CLAUDE)
        self.assertEqual(agent_side("codex 会話"), CODEX)
        self.assertIsNone(agent_side("ChatGPT"))
        self.assertEqual(agent_side("Claude Code codex-bridge 1234"), CLAUDE)  # 先頭だけで判定
        self.assertEqual(agent_side("Codex claude-tools 1"), CODEX)
        self.assertIsNone(agent_side("Tester（Claude）"))
        self.assertEqual(plan_label("codex-implements", True), "実装 Codex → レビュー Claude Code（交互）")

    def test_new_case_alternates_by_default_and_old_files_do_not(self):
        roles = self.store.roles(self.case_id)
        self.assertTrue(roles["alternate"])
        data = json.loads((self.store.folder(self.case_id) / "ROLES.json").read_text(encoding="utf-8"))
        self.assertIs(data["alternate"], True)
        # 交互の項目がない旧い ROLES.json は、交互にしない
        del data["alternate"]
        (self.store.folder(self.case_id) / "ROLES.json").write_text(json.dumps(data), encoding="utf-8")
        roles = self.store.roles(self.case_id)
        self.assertIsNone(roles["warning"])
        self.assertFalse(roles["alternate"])
        self.finish("Claude Code a", turn_done=True)
        self.assertEqual(self.plan(), "claude-implements")

    def test_finish_by_implementer_swaps_each_time_from_either_side(self):
        notes = self.finish("Claude Code ai-org 1", turn_done=True)
        self.assertEqual(self.plan(), "codex-implements")
        self.assertIn("次の実装担当は Codex", " ".join(notes))
        notes = self.finish("Codex ai-org 2", turn_done=True)
        self.assertEqual(self.plan(), "claude-implements")
        self.assertIn("次の実装担当は Claude Code", " ".join(notes))
        data = json.loads((self.store.folder(self.case_id) / "ROLES.json").read_text(encoding="utf-8"))
        self.assertEqual((data["implementer"], data["reviewer"]), (CLAUDE, CODEX))
        self.assertIn("Codex ai-org 2", data["changed_by"])
        self.assertTrue(data["alternate"])

    def test_mid_work_reviewer_and_unknown_do_not_swap(self):
        # 既定（--turn-done なし）は作業の途中として扱い、番を保つ
        notes = self.finish("Claude Code 途中")
        self.assertEqual(self.plan(), "claude-implements")
        self.assertIn("--turn-done", " ".join(notes))
        notes = self.finish("Codex review", turn_done=True)
        self.assertEqual(self.plan(), "claude-implements")
        self.assertIn("入れ替えていません", " ".join(notes))
        self.finish("ChatGPT", turn_done=True)
        self.assertEqual(self.plan(), "claude-implements")

    def test_start_reports_turn_and_warns_reviewer(self):
        session = Session(self.case_id, self.store)
        result = session.start("Codex x", self.root / "c.token")
        self.assertIn("実装 Claude Code → レビュー Codex（交互）", result["turn"])
        self.assertIn("レビュー担当です", result["turn"])
        session.finish(self.root / "c.token")
        result = session.start("Claude Code y", self.root / "d.token")
        self.assertNotIn("レビュー担当です", result["turn"])
        self.assertIn("--turn-done", result["turn"])

    def test_failed_token_save_does_not_swap(self):
        session = Session(self.case_id, self.store)
        with mock.patch("session.Path.write_text", side_effect=OSError("disk")):
            with self.assertRaises(ValueError):
                session.start("Claude Code z", self.root / "e.token")
        self.assertIsNone(CaseEditing(self.store, self.case_id).current())
        self.assertEqual(self.plan(), "claude-implements")

    def test_corrupt_roles_never_blocks_release(self):
        (self.store.folder(self.case_id) / "ROLES.json").write_text("{", encoding="utf-8")
        notes = self.finish("Claude Code a", turn_done=True)
        self.assertIn("入れ替えていません", " ".join(notes))
        self.assertIsNone(CaseEditing(self.store, self.case_id).current())
        self.assertEqual((self.store.folder(self.case_id) / "ROLES.json").read_text(encoding="utf-8"), "{")

    def test_set_roles_keeps_or_changes_alternate(self):
        revision = self.store.roles(self.case_id)["revision"]
        roles = self.store.set_roles(self.case_id, "codex-implements", revision)
        self.assertTrue(roles["alternate"])
        roles = self.store.set_roles(self.case_id, "codex-implements", roles["revision"], False)
        self.assertFalse(roles["alternate"])
        notes = self.finish("Codex a", turn_done=True)
        self.assertEqual(self.plan(), "codex-implements")
        self.assertEqual(notes, [])  # 交互でなければ何も言わない
        with self.assertRaises(ValueError):
            self.store.set_roles(self.case_id, "codex-implements", self.store.roles(self.case_id)["revision"], "yes")

    def test_legacy_release_command_swaps_only_with_turn_done(self):
        env = {**os.environ, "AI_ORG_DATA": str(self.root)}
        def run(*args):
            return subprocess.run([sys.executable, str(HUB / "workspace_hub.py"), *args, "--case", self.case_id],
                                  capture_output=True, text=True, encoding="utf-8", env=env, cwd=HUB)
        claim = run("claim", "--agent", "Claude Code legacy")
        self.assertEqual(claim.returncode, 0, claim.stderr)
        released = run("release", "--token", claim.stdout.strip())
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertEqual(self.plan(), "claude-implements")
        claim = run("claim", "--agent", "Claude Code legacy")
        released = run("release", "--token", claim.stdout.strip(), "--turn-done")
        self.assertEqual(released.returncode, 0, released.stderr)
        self.assertIn("次の実装担当は Codex", released.stdout)
        self.assertEqual(self.plan(), "codex-implements")


def uuid_like(agent):
    return "".join(ch if ch.isalnum() else "-" for ch in agent) + str(abs(hash(agent)) % 10**6)


if __name__ == "__main__":
    unittest.main()
