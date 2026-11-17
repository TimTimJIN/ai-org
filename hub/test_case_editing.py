import json
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest
from zipfile import ZipFile

from case_editing import CaseEditing
from workspace_hub import CaseStore


class CaseEditingTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = CaseStore(Path(temp.name) / "cases")
        self.case_id = self.store.create("Parallel work", "Review a saved copy")["id"]
        self.editing = CaseEditing(self.store, self.case_id)

    def test_two_sessions_cannot_both_claim_even_with_same_display_name(self):
        start = Barrier(2)

        def claim():
            editing = CaseEditing(self.store, self.case_id)
            start.wait(timeout=5)
            try:
                return editing.acquire("Codex")
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as workers:
            tokens = [token for token in workers.map(lambda _: claim(), range(2)) if token]
        self.assertEqual(len(tokens), 1)
        reopened = CaseEditing(self.store, self.case_id)
        with self.assertRaises(ValueError):
            reopened.release("wrong")
        reopened.release(tokens[0])
        new_token = reopened.acquire("Claude Code")
        with self.assertRaises(ValueError):
            reopened.release(tokens[0])
        reopened.release(new_token)

    def test_review_is_unchanged_by_followup_edit_and_note_targets_old_version(self):
        token = self.editing.acquire("Codex")
        live = self.editing.case / "outputs" / "sample.py"
        live.write_bytes(b"version one")
        snapshot = self.editing.review(token, ["outputs/sample.py"])
        live.write_bytes(b"version two")
        self.assertEqual(self.editing.current()["agent"], "Codex")
        report, changed = self.editing.review_note(snapshot.stem, "Claude Code", "Review of version one")
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["review_id"], snapshot.stem)
        self.assertEqual(changed, 1)
        with ZipFile(snapshot) as archive:
            self.assertEqual(archive.read("outputs/sample.py"), b"version one")
            manifest = json.loads(archive.read("REVIEW-MANIFEST.json"))
            self.assertEqual(manifest["files"]["outputs/sample.py"], sha256(b"version one").hexdigest())
        self.assertEqual(live.read_bytes(), b"version two")

    def test_snapshot_rejects_wrong_token_and_files_outside_case(self):
        token = self.editing.acquire("Codex")
        for proof, file in (("wrong", "TASK.json"), (token, "../outside.txt"),
                            (token, ".editing/owner.json"),
                            (token, "TASK.json:other")):
            with self.subTest(file=file), self.assertRaises(ValueError):
                self.editing.review(proof, [file])
        self.assertFalse((self.editing.case / "reviews").exists())

    def test_recovery_requires_current_claim_and_audits_previous_owner(self):
        old_token = self.editing.acquire("Codex")
        claim_id = self.editing.current()["claim_id"]
        with self.assertRaises(ValueError):
            self.editing.recover("wrong", "Operator", "Old session stopped")
        log = self.editing.recover(claim_id, "Operator", "Old session stopped")
        self.assertEqual(json.loads(log.read_text(encoding="utf-8"))["previous_agent"], "Codex")
        self.editing.acquire("Claude Code")
        with self.assertRaises(ValueError):
            self.editing.release(old_token)
        with self.assertRaises(ValueError):
            self.editing.recover(claim_id, "Operator", "Outdated view")
