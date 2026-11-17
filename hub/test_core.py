import tempfile
import threading
import unittest
from pathlib import Path
from core import Relay, Snapshot, Journal, RelayError
from native import Demo, Native


class RelayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stop = threading.Event()
        self.a, self.b = Demo("A", "a"), Demo("B", "b")
        self.engine = Relay([self.a, self.b], ["a", "b"],
                            Journal(Path(self.tmp.name) / "log.jsonl"), self.stop,
                            stable=0, poll=0, timeout=0.02)

    def test_two_rounds_exactly(self):
        self.engine.run("test", 2)
        self.assertEqual(len(self.a.turns), 4)
        self.assertEqual(len(self.b.turns), 4)
        self.assertIn("模擬回答", self.b.turns[0][1])

    def test_second_target_invalid_sends_nothing(self):
        self.b.target = "different"
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.a.turns, [])

    def test_existing_draft_preserved(self):
        self.a.snapshot = lambda: Snapshot("a", "draft", False, ())
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.a.turns, [])

    def test_cancel_before_send(self):
        self.stop.set()
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.a.turns, [])

    def test_uncertain_send_never_retried(self):
        calls = []
        def send(*args):
            calls.append(1)
            raise RelayError("uncertain")
        self.a.send = send
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(len(calls), 1)

    def test_changed_target_after_send(self):
        original = self.a.send
        def send(*args):
            original(*args)
            self.a.target = "changed"
        self.a.send = send
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.b.turns, [])

    def test_duplicate_detected(self):
        original = self.a.send
        def send(*args):
            original(*args)
            self.a.turns.append(self.a.turns[0])
        self.a.send = send
        with self.assertRaises(RelayError): self.engine.run("test", 1)

    def test_busy_never_forwarded(self):
        original = self.a.snapshot
        self.a.snapshot = lambda: Snapshot("a", "", bool(self.a.turns), tuple(self.a.turns))
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.b.turns, [])

    def test_foreign_message_stops(self):
        original = self.a.send
        def send(*args):
            original(*args)
            self.a.turns.append(("user", "another message"))
        self.a.send = send
        with self.assertRaises(RelayError): self.engine.run("test", 1)

    def test_round_bound(self):
        with self.assertRaises(RelayError): self.engine.run("test", 6)
        self.assertEqual(self.a.turns, [])

    def test_idle_without_completion_never_forwarded(self):
        self.a.snapshot = lambda: Snapshot("a", "", False, tuple(self.a.turns))
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.b.turns, [])

    def test_long_answer_not_forwarded(self):
        original = self.a.send
        def send(*args):
            original(*args)
            self.a.turns[-1] = ("assistant", "x" * 8001)
        self.a.send = send
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        self.assertEqual(self.b.turns, [])

    def test_unvalidated_native_send_is_blocked(self):
        native = Native("claude", "test", Path(self.tmp.name) / "STOP")
        native.call = lambda *a, **k: self.fail("Must not reach native UI")
        with self.assertRaises(RelayError): native.send("test", None, self.stop)

    def test_changed_whitespace_is_not_the_same_message(self):
        original = self.a.send
        def send(*args):
            original(*args)
            role, text = self.a.turns[0]
            self.a.turns[0] = (role, text.replace("alpha beta", "alphabeta"))
        self.a.send = send
        with self.assertRaises(RelayError): self.engine.run("alpha beta", 1)
        self.assertEqual(self.b.turns, [])

    def test_cancel_on_last_reply_is_not_completed(self):
        def report(line):
            if line.startswith("Claude:"):
                self.stop.set()
        self.engine.report = report
        with self.assertRaises(RelayError): self.engine.run("test", 1)
        content = (Path(self.tmp.name) / "log.jsonl").read_text(encoding="utf-8")
        self.assertNotIn('"event": "completed"', content)


if __name__ == "__main__": unittest.main()
