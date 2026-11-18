from datetime import date
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "hub"))

import dev  # noqa: E402
from session import Session  # noqa: E402
from workspace_hub import CaseStore  # noqa: E402


def run(*args, cwd, env=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env)


class DevExtensionTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / "data"
        self.store = CaseStore(self.data / "cases")
        self.case_id = self.store.create("Dev", "Scope")["id"]
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run("git", "init", "-q", cwd=self.repo)
        run("git", "config", "user.email", "t@example.invalid", cwd=self.repo)
        run("git", "config", "user.name", "t", cwd=self.repo)
        run("git", "config", "core.hooksPath", str(HERE / "githooks"), cwd=self.repo)
        (self.repo / ".ai-org.json").write_text(json.dumps({
            "case": self.case_id, "data": str(self.data), "status_files": ["STATUS.md"],
            "check": [sys.executable, "-c", "print('check ok')"]}), encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AI_ORG_")}
        self.env["PYTHONIOENCODING"] = "utf-8"
        patcher = mock.patch.dict(os.environ, {"AI_ORG_DATA": str(self.data)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def commit(self, env):
        (self.repo / "f.txt").write_text(str(len(list(self.repo.iterdir()))), encoding="utf-8")
        run("git", "add", "-A", cwd=self.repo)
        return run("git", "commit", "-q", "-m", "x", cwd=self.repo, env=env)

    def start(self, name="t.token"):
        token_file = self.root / name
        Session(self.case_id, self.store).start("Tester", token_file)
        return token_file

    # git フック -----------------------------------------------------------
    def test_commit_blocked_without_claim_and_allowed_for_holder(self):
        self.assertNotEqual(self.commit(self.env).returncode, 0)
        token_file = self.start()
        other = dict(self.env, AI_ORG_TOKEN_FILE=str(self.root / "other.token"))
        self.assertNotEqual(self.commit(other).returncode, 0)
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        result = self.commit(holder)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_skip_variable_lets_user_commit(self):
        result = self.commit(dict(self.env, AI_ORG_SKIP_CLAIM_CHECK="1"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unregistered_repository_is_not_blocked_yet(self):
        (self.repo / ".ai-org.json").unlink()
        self.assertEqual(self.commit(self.env).returncode, 0)

    def test_local_hook_is_chained(self):
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        hook.write_text("#!/bin/sh\necho local >&2\nexit 1\n", encoding="utf-8")
        os.chmod(hook, 0o755)
        token_file = self.start()
        result = self.commit(dict(self.env, AI_ORG_TOKEN_FILE=str(token_file)))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local", result.stderr)

    # finish -------------------------------------------------------------
    def test_finish_checks_status_and_dirty_tree(self):
        token_file = self.start()
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        args = ["finish", "--project", str(self.repo), "--token-file", str(token_file)]
        self.assertEqual(dev.main(args), 1)  # リポジトリの STATUS.md がない
        today = date.today().isoformat()
        (self.repo / "STATUS.md").write_text(f"# 状況\n\n更新：{today}\n", encoding="utf-8")
        self.assertEqual(dev.main(args), 1)  # 未コミット
        self.assertEqual(self.commit(holder).returncode, 0)
        self.assertEqual(dev.main(args), 1)  # 案件の STATUS.md が今日でない
        (self.store.folder(self.case_id) / "STATUS.md").write_text(f"更新: {today}\n", encoding="utf-8")
        self.assertEqual(dev.main(args), 0)
        self.assertFalse(token_file.exists())

    def test_finish_stops_when_check_fails(self):
        config = json.loads((self.repo / ".ai-org.json").read_text(encoding="utf-8"))
        config["check"] = [sys.executable, "-c", "import sys; sys.exit(3)"]
        (self.repo / ".ai-org.json").write_text(json.dumps(config), encoding="utf-8")
        token_file = self.start()
        self.assertEqual(dev.main(["finish", "--project", str(self.repo), "--token-file", str(token_file),
                                   "--status-unchanged", "--allow-dirty"]), 1)
        self.assertTrue(token_file.exists())  # 編集権は保持したまま

    # Claude Code の編集前フック -------------------------------------------
    def claude(self, payload):
        return dev.claude_decision(payload)

    def scratch_token(self, session_id):
        temp = self.root / "tmp"
        folder = temp / "claude" / "abc" / session_id / "scratchpad"
        folder.mkdir(parents=True, exist_ok=True)
        return temp, folder / f"ai-org-{self.case_id}.token"

    def test_claude_guard_uses_session_scratchpad_token(self):
        temp, token_file = self.scratch_token("sess-1")
        Session(self.case_id, self.store).start("Claude", token_file)
        target = str(self.repo / "a.txt")
        with mock.patch("tempfile.gettempdir", return_value=str(temp)):
            self.assertIsNone(self.claude({"session_id": "sess-1", "tool_input": {"file_path": target}}))
            self.assertIsNotNone(self.claude({"session_id": "sess-2", "tool_input": {"file_path": target}}))
            self.assertIn("サブエージェント", self.claude(
                {"session_id": "sess-1", "agent_id": "x", "tool_input": {"file_path": target}}))
            case = self.store.folder(self.case_id)
            self.assertIsNone(self.claude({"session_id": "sess-1", "tool_input": {"file_path": str(case / "STATUS.md")}}))
            self.assertIn("ROLES.json", self.claude({"session_id": "sess-1", "tool_input": {"file_path": str(case / "ROLES.json")}}))
            self.assertIn("ROLES.json", self.claude({"session_id": "sess-1", "tool_input": {"file_path": str(case / ".editing" / "owner.json")}}))

    def test_claude_guard_ignores_unrelated_paths(self):
        self.assertIsNone(self.claude({"session_id": "s", "tool_input": {"file_path": str(self.root / "elsewhere.txt")}}))

    def test_claude_guard_cli_fails_closed_on_bad_input(self):
        result = subprocess.run([sys.executable, str(HERE / "dev.py"), "claude-guard"], input="not json",
                                capture_output=True, text=True, encoding="utf-8", env=self.env)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
