import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from case_editing import CaseEditing
from report import build_report
from workspace_hub import CaseStore


class ReportTests(unittest.TestCase):
    def test_report_lists_cases_without_secrets(self):
        with TemporaryDirectory() as temp:
            store = CaseStore(Path(temp) / "cases")
            first = store.create("案件A", "目的")["id"]
            second = store.create("案件B|縦線", "目的")["id"]
            (store.folder(first) / "STATUS.md").write_text("# 作業状況\n\n状態: 進行中\n更新: 2026-11-18\n", encoding="utf-8")
            token = CaseEditing(store, first).acquire("Claude Code test")
            CaseEditing(store, second).request_pause()
            text = build_report(store)
            self.assertIn("案件A", text)
            self.assertIn("進行中", text)
            self.assertIn("Claude Code test", text)
            self.assertIn("停止中", text)
            self.assertIn("案件B／縦線", text)  # 表を壊す文字を置き換える
            self.assertNotIn(token, text)
            proof = json.loads((store.folder(first) / ".editing" / "owner.json").read_text(encoding="utf-8"))["proof"]
            self.assertNotIn(proof, text)


if __name__ == "__main__":
    unittest.main()
