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


class ReportSafetyTests(unittest.TestCase):
    def test_write_refuses_data_folder_and_foreign_files(self):
        from report import MARKER, write_report
        with TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            (data / "cases").mkdir(parents=True)
            report = f"# 案件の一覧（写し）\n{MARKER}\n"
            owner = data / "cases" / "owner.json"
            owner.write_text("{}", encoding="utf-8")
            with self.assertRaises(ValueError):
                write_report(report, owner, data)
            self.assertEqual(owner.read_text(encoding="utf-8"), "{}")
            for existing in ("大事なメモ", "# 案件の一覧と運用メモ\n手書きの内容\n"):
                other = Path(temp) / "notes.md"
                other.write_text(existing, encoding="utf-8")
                with self.assertRaises(ValueError):
                    write_report(report, other, data)
                self.assertEqual(other.read_text(encoding="utf-8"), existing)
            out = Path(temp) / "report.md"
            write_report(report, out, data)
            write_report(f"# 案件の一覧（更新）\n{MARKER}\n", out, data)  # 写し同士は上書きできる
            self.assertIn("更新", out.read_text(encoding="utf-8"))

    def test_secret_like_strings_are_masked_but_case_ids_kept(self):
        with TemporaryDirectory() as temp:
            store = CaseStore(Path(temp) / "cases")
            case = store.create("鍵", "目的")["id"]
            (store.folder(case) / "STATUS.md").write_text(
                f"状態: 鍵 sk-ABCDEF1234567890 と {'a1' * 20} を貼った。{case} は残す\n", encoding="utf-8")
            text = build_report(store)
            self.assertNotIn("sk-ABCDEF1234567890", text)
            self.assertNotIn("a1" * 20, text)
            self.assertIn("［伏せ字］", text)
            self.assertIn(f"{case} は残す", text)

    def test_one_broken_status_does_not_stop_report(self):
        with TemporaryDirectory() as temp:
            store = CaseStore(Path(temp) / "cases")
            good = store.create("正常", "目的")["id"]
            bad = store.create("文字化け", "目的")["id"]
            (store.folder(good) / "STATUS.md").write_text("状態: 正常\n", encoding="utf-8")
            (store.folder(bad) / "STATUS.md").write_bytes("状態: 壊れ\n".encode("cp932"))
            text = build_report(store)
            self.assertIn("正常", text)
            self.assertIn("文字化け", text)

    def test_long_status_is_truncated(self):
        with TemporaryDirectory() as temp:
            store = CaseStore(Path(temp) / "cases")
            case = store.create("長い", "目的")["id"]
            (store.folder(case) / "STATUS.md").write_text("状態: " + "あ" * 1000 + "\n", encoding="utf-8")
            self.assertNotIn("あ" * 300, build_report(store))


if __name__ == "__main__":
    unittest.main()
