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
        # 利用者の実際の設定（%USERPROFILE%\.ai-org\config.json）を読まないようにする
        no_config = str(self.root / "no-config.json")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("AI_ORG_")}
        self.env["PYTHONIOENCODING"] = "utf-8"
        self.env["AI_ORG_CONFIG"] = no_config
        patcher = mock.patch.dict(os.environ, {"AI_ORG_DATA": str(self.data), "AI_ORG_CONFIG": no_config})
        patcher.start()
        self.addCleanup(patcher.stop)

    def commit(self, env):
        self.counter = getattr(self, "counter", 0) + 1
        (self.repo / "f.txt").write_text(str(self.counter), encoding="utf-8")
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

    def test_unregistered_repository_is_not_blocked_without_policy(self):
        (self.repo / ".ai-org.json").unlink()
        env = dict(self.env, AI_ORG_CONFIG=str(self.root / "no-config.json"))
        self.assertEqual(self.commit(env).returncode, 0)

    def write_policy(self, **extra):
        path = self.root / "config.json"
        policy = {"dev_roots": [str(self.root)], "data": str(self.data)}
        policy.update(extra)
        path.write_text(json.dumps(policy), encoding="utf-8")
        return path

    def test_policy_blocks_unregistered_repository_under_dev_root(self):
        (self.repo / ".ai-org.json").unlink()
        env = dict(self.env, AI_ORG_CONFIG=str(self.write_policy()))
        result = self.commit(env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("案件と結び付いていない", result.stderr)
        excluded = dict(self.env, AI_ORG_CONFIG=str(self.write_policy(exclude=[str(self.repo)])))
        self.assertEqual(self.commit(excluded).returncode, 0)
        outside = dict(self.env, AI_ORG_CONFIG=str(self.write_policy(dev_roots=[str(self.root / "elsewhere")])))
        self.assertEqual(self.commit(outside).returncode, 0)

    def test_policy_blocks_claude_writes_in_unregistered_repo_but_allows_registration_file(self):
        (self.repo / ".ai-org.json").unlink()
        with mock.patch.dict(os.environ, {"AI_ORG_CONFIG": str(self.write_policy())}):
            self.assertIn("案件と結び付いていない", self.claude({"session_id": "s", "tool_input": {"file_path": str(self.repo / "a.py")}}))
            # .ai-org.json を新しく書くときは、中身の案件の編集権を確かめる
            content = json.dumps({"case": self.case_id, "data": str(self.data)})
            target = str(self.repo / ".ai-org.json")
            self.assertIsNotNone(self.claude({"session_id": "s", "tool_input": {"file_path": target, "content": content}}))
            self.assertIsNotNone(self.claude({"session_id": "s", "tool_input": {"file_path": target, "content": "{}"}}))
            temp, token_file = self.scratch_token("sess-reg")
            Session(self.case_id, self.store).start("Claude", token_file)
            with mock.patch("tempfile.gettempdir", return_value=str(temp)):
                self.assertIsNone(self.claude({"session_id": "sess-reg", "tool_input": {"file_path": target, "content": content}}))
            self.assertIsNone(self.claude({"session_id": "s", "tool_input": {"file_path": str(self.root.parent / "x.txt")}}))

    def test_merge_cherry_pick_revert_and_no_verify_are_guarded(self):
        token_file = self.start()
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        self.assertEqual(self.commit(holder).returncode, 0)
        run("git", "checkout", "-q", "-b", "side", cwd=self.repo)
        self.assertEqual(self.commit(holder).returncode, 0)
        run("git", "checkout", "-q", "-", cwd=self.repo)
        # 編集権を返した後は、どの経路でもコミットを作れない
        Session(self.case_id, self.store).finish(token_file, status_unchanged=True)
        before = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout
        for args in (["cherry-pick", "side"], ["merge", "--no-ff", "--no-edit", "side"], ["revert", "--no-edit", "HEAD"]):
            run("git", *args, cwd=self.repo, env=self.env)
            # どの操作でもコミットが増えないこと（終了コードは git の操作ごとに違うため、HEAD で確かめる）
            self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout, before, args)
            run("git", args[0], "--abort", cwd=self.repo, env=self.env)
            run("git", "reset", "-q", "--hard", "HEAD", cwd=self.repo, env=self.env)
        (self.repo / "f.txt").write_text("nv", encoding="utf-8")
        run("git", "add", "-A", cwd=self.repo)
        self.assertNotEqual(run("git", "commit", "-q", "--no-verify", "-m", "nv", cwd=self.repo, env=self.env).returncode, 0)
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout, before)

    def test_register_requires_claim(self):
        (self.repo / ".ai-org.json").unlink()
        with mock.patch.dict(os.environ, {"AI_ORG_CONFIG": str(self.write_policy())}):
            args = ["register", "--project", str(self.repo), "--case", self.case_id, "--status-file", "STATUS.md",
                    "--check-json", '["python", "-V"]', "--token-file", str(self.root / "none.token")]
            self.assertEqual(dev.main(args), 1)
            self.assertFalse((self.repo / ".ai-org.json").exists())
            token_file = self.start()
            args[-1] = str(token_file)
            self.assertEqual(dev.main(args), 0)
            config = json.loads((self.repo / ".ai-org.json").read_text(encoding="utf-8"))
            self.assertEqual(config["case"], self.case_id)
            self.assertEqual(config["check"], ["python", "-V"])
            self.assertEqual(dev.main(args), 1)  # 既にある結び付けは上書きしない

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
        self.assertEqual(dev.main(args), 1)  # 案件の STATUS.md が今日でない（--status-unchanged はリポジトリ側だけ）
        self.assertEqual(dev.main(args + ["--status-unchanged"]), 1)
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

    def test_claude_guard_protects_case_folder_without_any_data_setting(self):
        # レビュー指摘（重大）：データフォルダーの設定がなくても、案件フォルダーの形で判定して守る
        case = self.store.folder(self.case_id)
        temp, token_file = self.scratch_token("sess-1")
        env = {k: v for k, v in os.environ.items() if k != "AI_ORG_DATA"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("tempfile.gettempdir", return_value=str(temp)):
            self.assertIn("ROLES.json", self.claude({"session_id": "x", "tool_input": {"file_path": str(case / "ROLES.json")}}))
            self.assertIn("止めました", self.claude({"session_id": "x", "tool_input": {"file_path": str(case / "STATUS.md")}}))
            Session(self.case_id, self.store).start("Claude", token_file)
            os.environ.pop("AI_ORG_DATA", None)
            self.assertIsNone(self.claude({"session_id": "sess-1", "tool_input": {"file_path": str(case / "STATUS.md")}}))
        # 環境変数が別のデータフォルダーを指していても、本番の案件フォルダーは守る
        other = self.root / "other-data"
        CaseStore(other / "cases")
        with mock.patch.dict(os.environ, {"AI_ORG_DATA": str(other)}):
            self.assertIn("止めました", self.claude({"session_id": "x", "tool_input": {"file_path": str(case / "STATUS.md")}}))

    def test_claude_guard_normalizes_special_path_forms(self):
        case = self.store.folder(self.case_id)
        drive, rest = str(case / "ROLES.json").split(":", 1)
        import socket
        for form in ("\\\\?\\" + str(case / "ROLES.json"), f"\\\\localhost\\{drive}$" + rest,
                     f"\\\\{socket.gethostname()}\\{drive}$" + rest,
                     f"\\\\127.0.0.1\\{drive}$" + rest, str(case / "ROLES.json").replace("\\", "/")):
            self.assertIn("ROLES.json", self.claude({"session_id": "x", "tool_input": {"file_path": form}}), form)

    def test_worktree_and_other_local_hooks_are_chained(self):
        token_file = self.start()
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        self.assertEqual(self.commit(holder).returncode, 0)
        hook = self.repo / ".git" / "hooks" / "commit-msg"
        hook.write_text("#!/bin/sh\necho local-msg >&2\nexit 1\n", encoding="utf-8")
        os.chmod(hook, 0o755)
        result = self.commit(holder)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local-msg", result.stderr)
        hook.unlink()
        pre = self.repo / ".git" / "hooks" / "pre-commit"
        pre.write_text("#!/bin/sh\necho local-wt >&2\nexit 1\n", encoding="utf-8")
        os.chmod(pre, 0o755)
        worktree = self.root / "wt"
        run("git", "worktree", "add", "-q", "-b", "wt", str(worktree), cwd=self.repo)
        (worktree / "g.txt").write_text("x", encoding="utf-8")
        run("git", "add", "-A", cwd=worktree)
        result = run("git", "commit", "-q", "-m", "wt", cwd=worktree, env=holder)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("local-wt", result.stderr)

    def test_git_config_binding_covers_old_and_orphan_branches(self):
        token_file = self.start()
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        run("git", "config", "--local", "ai-org.case", self.case_id, cwd=self.repo)
        run("git", "config", "--local", "ai-org.data", str(self.data), cwd=self.repo)
        run("git", "checkout", "-q", "--orphan", "lonely", cwd=self.repo)
        run("git", "rm", "-q", "-rf", "--cached", ".", cwd=self.repo)
        (self.repo / ".ai-org.json").unlink()
        (self.repo / "o.txt").write_text("o", encoding="utf-8")
        run("git", "add", "o.txt", cwd=self.repo)
        self.assertNotEqual(run("git", "commit", "-q", "-m", "o", cwd=self.repo, env=self.env).returncode, 0)
        self.assertEqual(run("git", "commit", "-q", "-m", "o", cwd=self.repo, env=holder).returncode, 0)

    def test_claude_guard_uses_git_config_binding_without_file(self):
        # v0.2.1：.ai-org.json のない作業ツリー（結び付ける前からのブランチ）でも、git の設定で編集権を確かめる
        run("git", "config", "--local", "ai-org.case", self.case_id, cwd=self.repo)
        run("git", "config", "--local", "ai-org.data", str(self.data), cwd=self.repo)
        (self.repo / ".ai-org.json").unlink()
        target = str(self.repo / "a.txt")
        self.assertIn("止めました", self.claude({"session_id": "x", "tool_input": {"file_path": target}}))
        temp, token_file = self.scratch_token("sess-g")
        Session(self.case_id, self.store).start("Claude", token_file)
        with mock.patch("tempfile.gettempdir", return_value=str(temp)):
            self.assertIsNone(self.claude({"session_id": "sess-g", "tool_input": {"file_path": target}}))

    def test_git_guard_fills_git_config_for_hand_written_binding(self):
        # v0.2.1：手で置いた .ai-org.json にも git の設定を補う
        self.assertEqual(run("git", "config", "--get", "ai-org.case", cwd=self.repo).stdout.strip(), "")
        token_file = self.start()
        self.assertEqual(self.commit(dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))).returncode, 0)
        self.assertEqual(run("git", "config", "--get", "ai-org.case", cwd=self.repo).stdout.strip(), self.case_id)

    def test_wrong_case_in_worktree_is_not_persisted(self):
        # Codex 指摘1：編集権の確認前に、作業ツリーの誤った案件を git の設定へ書かない
        token_file = self.start()
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        self.assertEqual(run("git", "config", "--unset", "ai-org.case", cwd=self.repo).returncode in (0, 5), True)
        self.assertEqual(self.commit(holder).returncode, 0)  # HEAD に案件 A の .ai-org.json
        run("git", "config", "--unset", "ai-org.case", cwd=self.repo)
        run("git", "config", "--unset", "ai-org.data", cwd=self.repo)
        config = json.loads((self.repo / ".ai-org.json").read_text(encoding="utf-8"))
        config["case"] = "case-" + "1" * 32
        (self.repo / ".ai-org.json").write_text(json.dumps(config), encoding="utf-8")
        self.assertNotEqual(self.commit(self.env).returncode, 0)
        self.assertEqual(run("git", "config", "--get", "ai-org.case", cwd=self.repo).stdout.strip(), "")

    def test_claude_and_git_agree_on_mismatch_and_policy_data(self):
        # Codex 指摘2：git の設定と .ai-org.json が食い違えば、Claude Code 側も止める
        run("git", "config", "--local", "ai-org.case", "case-" + "2" * 32, cwd=self.repo)
        temp, token_file = self.scratch_token("sess-m")
        Session(self.case_id, self.store).start("Claude", token_file)
        with mock.patch("tempfile.gettempdir", return_value=str(temp)):
            reason = self.claude({"session_id": "sess-m", "tool_input": {"file_path": str(self.repo / "a.txt")}})
        self.assertIn("食い違", reason)
        # git の設定だけで data がなく、利用者の設定の data で決まる場合も、保持者は書ける
        run("git", "config", "--local", "ai-org.case", self.case_id, cwd=self.repo)
        (self.repo / ".ai-org.json").unlink()
        run("git", "rm", "-q", "--cached", ".ai-org.json", cwd=self.repo)
        env = {k: v for k, v in os.environ.items() if k != "AI_ORG_DATA"}
        env["AI_ORG_CONFIG"] = str(self.write_policy(dev_roots=[str(self.root / "elsewhere")]))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("tempfile.gettempdir", return_value=str(temp)):
            self.assertIsNone(self.claude({"session_id": "sess-m", "tool_input": {"file_path": str(self.repo / "a.txt")}}))

    def test_git_config_and_file_mismatch_blocks(self):
        token_file = self.start()
        run("git", "config", "--local", "ai-org.case", "case-" + "0" * 32, cwd=self.repo)
        result = self.commit(dict(self.env, AI_ORG_TOKEN_FILE=str(token_file)))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("食い違", result.stderr)

    def test_git_am_is_guarded(self):
        token_file = self.start()
        holder = dict(self.env, AI_ORG_TOKEN_FILE=str(token_file))
        self.assertEqual(self.commit(holder).returncode, 0)
        self.assertEqual(self.commit(holder).returncode, 0)
        patch = run("git", "format-patch", "-1", "HEAD", "--stdout", cwd=self.repo).stdout
        run("git", "reset", "-q", "--hard", "HEAD~1", cwd=self.repo)
        before = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout
        subprocess.run(["git", "am"], input=patch, cwd=self.repo, capture_output=True, text=True, encoding="utf-8", env=self.env)
        run("git", "am", "--abort", cwd=self.repo)
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout, before)

    def test_register_records_git_config(self):
        (self.repo / ".ai-org.json").unlink()
        token_file = self.start()
        self.assertEqual(dev.main(["register", "--project", str(self.repo), "--case", self.case_id,
                                   "--token-file", str(token_file)]), 0)
        self.assertEqual(run("git", "config", "--get", "ai-org.case", cwd=self.repo).stdout.strip(), self.case_id)

    def test_chain_hooks_path_setting_is_used(self):
        old = self.root / "old-hooks"
        old.mkdir()
        (old / "pre-commit").write_text("#!/bin/sh\necho old-path >&2\nexit 1\n", encoding="utf-8")
        os.chmod(old / "pre-commit", 0o755)
        run("git", "config", "ai-org.chainHooksPath", str(old), cwd=self.repo)
        token_file = self.start()
        result = self.commit(dict(self.env, AI_ORG_TOKEN_FILE=str(token_file)))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("old-path", result.stderr)

    def test_finish_refuses_non_git_folder_and_non_holder_before_check(self):
        token_file = self.start()
        plain = self.root / "plain"
        plain.mkdir()
        (plain / ".ai-org.json").write_text((self.repo / ".ai-org.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(dev.main(["finish", "--project", str(plain), "--token-file", str(token_file),
                                   "--status-unchanged", "--case-status-unchanged"]), 1)
        self.assertTrue(token_file.exists())
        marker = self.root / "check-ran"
        config = json.loads((self.repo / ".ai-org.json").read_text(encoding="utf-8"))
        config["check"] = [sys.executable, "-c", f"open(r'{marker}', 'w').close()"]
        (self.repo / ".ai-org.json").write_text(json.dumps(config), encoding="utf-8")
        self.assertEqual(dev.main(["finish", "--project", str(self.repo), "--token-file", str(self.root / "none.token")]), 1)
        self.assertFalse(marker.exists())

    def test_claude_guard_ignores_unrelated_paths(self):
        self.assertIsNone(self.claude({"session_id": "s", "tool_input": {"file_path": str(self.root / "elsewhere.txt")}}))

    def test_claude_guard_cli_fails_closed_on_bad_input(self):
        result = subprocess.run([sys.executable, str(HERE / "dev.py"), "claude-guard"], input="not json",
                                capture_output=True, text=True, encoding="utf-8", env=self.env)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
