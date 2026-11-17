from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from case_editing import CaseEditing
from workspace_hub import CaseStore


class WorkControlTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = CaseStore(Path(temp.name) / "cases")
        self.case_id = self.store.create("Stop and redirect", "Original scope")["id"]
        self.editing = CaseEditing(self.store, self.case_id)

    def test_pause_is_pending_until_owner_reports_and_resume_publishes_direction(self):
        token = self.editing.acquire("Codex")
        asked = self.editing.request_pause()
        self.assertEqual(asked["phase"], "pending")
        request_id = asked["request_id"]
        with self.assertRaises(ValueError):
            self.editing.resume(request_id, "Revise scope")
        with self.assertRaises(ValueError):
            self.editing.acknowledge_pause("wrong", request_id)
        with self.assertRaises(ValueError):
            self.editing.release(token)
        stopped = self.editing.acknowledge_pause(token, request_id)
        self.assertEqual(stopped["phase"], "acknowledged")
        self.assertEqual(stopped["ack"]["agent"], "Codex")
        self.editing.release(token)
        with self.assertRaises(ValueError):
            self.editing.acquire("Claude Code")
        state = self.editing.resume(request_id, "新方針で再開")
        self.assertEqual(state["phase"], "active")
        reopened = CaseEditing(self.store, self.case_id)
        self.assertEqual(reopened.control_view()["direction"], "新方針で再開")
        new_token = reopened.acquire("Claude Code")
        self.assertTrue(reopened.control_view()["needs_direction_confirmation"])
        with self.assertRaises(ValueError):
            reopened.confirm_direction(new_token, "another request")
        self.assertFalse(reopened.confirm_direction(new_token, request_id)["needs_direction_confirmation"])
        reopened.release(new_token)
        reopened.acquire("Next editor")
        self.assertTrue(reopened.control_view()["needs_direction_confirmation"])

    def test_unassigned_pause_prevents_start_and_stale_resume_is_rejected(self):
        first = self.editing.request_pause()
        self.assertEqual(first["phase"], "unassigned")
        with self.assertRaises(ValueError):
            self.editing.acquire("Claude Code")
        self.editing.resume(first["request_id"], "Scope")
        later = self.editing.request_pause()
        with self.assertRaises(ValueError):
            self.editing.resume(first["request_id"], "Out of date")
        self.assertEqual(self.editing.resume(later["request_id"], "")["direction"], "Scope")

    def test_concurrent_pause_requests_have_one_winner(self):
        def request(_):
            try:
                return self.editing.request_pause()
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [state for state in pool.map(request, range(2)) if state]
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.editing.control_view()["request_id"], requests[0]["request_id"])

    def test_verified_recovery_can_unblock_pending_pause_without_claiming_a_report(self):
        old_token = self.editing.acquire("Stopped editor")
        asked = self.editing.request_pause()
        self.editing.recover(self.editing.current()["claim_id"], "Operator", "Process stopped")
        self.assertEqual(self.editing.control_view()["phase"], "unassigned")
        self.assertIsNone(self.editing.control_view()["ack"])
        with self.assertRaises(ValueError):
            self.editing.acknowledge_pause(old_token, asked["request_id"])
        self.editing.resume(asked["request_id"], "Revised scope")
