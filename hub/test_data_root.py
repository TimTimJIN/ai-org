import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import data_root
from workspace_hub import CaseStore

HUB = Path(__file__).resolve().parent


class DataRootTest(unittest.TestCase):
    def test_env_points_to_data_folder(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"AI_ORG_DATA": temp}):
            (Path(temp) / "cases").mkdir()
            self.assertEqual(data_root.data_root(), Path(temp).resolve())
            store = CaseStore()
            self.assertEqual(store.root, Path(temp).resolve() / "cases")
            self.assertEqual(store.inbox, Path(temp).resolve() / "inbox")

    def test_env_without_cases_or_relative_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = str(Path(temp) / "typo")
            for value in (missing, temp, "relative\\data", "."):
                with mock.patch.dict(os.environ, {"AI_ORG_DATA": value}):
                    with self.assertRaises(ValueError, msg=value):
                        data_root.data_root()
            self.assertFalse((Path(temp) / "typo").exists())
            self.assertFalse((Path(temp) / "cases").exists())

    def test_forward_shim_refuses_import(self):
        legacy = HUB.parent / "legacy"
        with mock.patch.object(sys, "path", [str(legacy)] + sys.path):
            with self.assertRaises(ImportError):
                __import__("forward")

    def test_unset_and_no_legacy_cases_is_refused(self):
        env = {k: v for k, v in os.environ.items() if k != "AI_ORG_DATA"}
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(data_root, "CODE_DIR", Path(temp)):
            with self.assertRaises(ValueError):
                data_root.data_root()

    def test_legacy_layout_uses_code_folder(self):
        env = {k: v for k, v in os.environ.items() if k != "AI_ORG_DATA"}
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(data_root, "CODE_DIR", Path(temp)):
            (Path(temp) / "cases").mkdir()
            self.assertEqual(data_root.data_root(), Path(temp))

    def test_repository_never_gets_case_folders(self):
        # リポジトリの hub/ に cases などのデータフォルダーがないこと（データはリポジトリの外）。
        for name in ("cases", "inbox", "data", "knowledge-vault", "work-test"):
            self.assertFalse((HUB / name).exists(), name)

    def test_cli_without_data_root_fails_cleanly(self):
        env = {k: v for k, v in os.environ.items() if k != "AI_ORG_DATA"}
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run([sys.executable, str(HUB / "workspace_hub.py"), "draft-status", "--draft", "0" * 32],
                                capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("AI_ORG_DATA", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
