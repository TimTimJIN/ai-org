"""Coordinate writers and publish copies for reviewers on the local Windows PC."""
from contextlib import contextmanager
from hashlib import sha256
import json
import msvcrt
import os
from pathlib import Path, PureWindowsPath
import secrets
import tempfile
import uuid
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile


class CaseEditing:
    def __init__(self, store, case_id):
        self.store = store
        self.case_id = case_id
        store.read(case_id)
        self.case = store.folder(case_id)
        self.state = self.case / ".editing"
        store.inside(self.case, self.state)
        self.owner = self.state / "owner.json"
        self.control = self.state / "work-control.json"

    @contextmanager
    def guard(self):
        # Keep this file in place. Windows releases the byte lock when the
        # process exits, but the separate owner record survives a crash.
        gate = self.state / "gate"
        self.store.inside(self.case, gate)
        self.state.mkdir(exist_ok=True)
        with gate.open("a+b") as stream:
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError("別の担当が編集権またはレビュー用コピーを処理中です。再試行してください。") from error
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)

    def current(self):
        self.store.inside(self.case, self.owner)
        try:
            with self.owner.open("r", encoding="utf-8") as stream:
                owner = json.load(stream)
        except FileNotFoundError:
            return None
        if (not isinstance(owner, dict) or not all(
                isinstance(owner.get(key), str) for key in ("agent", "proof", "since", "claim_id"))):
            raise ValueError("編集権の記録を読み取れません。作業状況を確認してください。")
        return owner

    def acquire(self, agent):
        from workspace_hub import now, write_new_json

        agent = agent.strip()
        if not agent or len(agent) > 100:
            raise ValueError("担当とセッションを100文字以内で指定してください。")
        with self.guard():
            if self.work_control()["state"] != "active":
                raise ValueError("案件は停止中です。画面からの再開を待ってください。")
            owner = self.current()
            if owner is not None:
                raise ValueError(f"編集権は {owner['agent']} が保持しています。")
            token = secrets.token_hex(32)
            write_new_json(self.owner, {"agent": agent, "since": now(), "claim_id": uuid.uuid4().hex,
                                       "proof": sha256(token.encode()).hexdigest()})
            return token

    def require_owner(self, token):
        owner = self.current()
        proof = sha256(token.encode()).hexdigest()
        if owner is None or not secrets.compare_digest(owner["proof"], proof):
            raise ValueError("この作業の編集権を確認できません。")
        return owner

    def release(self, token, complete_turn=False):
        """Return the edit claim. With `complete_turn` (the AI said its round of
        implementation and review is done), an alternating role plan is swapped
        (see CaseStore.rotate_roles); returns a note or None.

        Every path that ends a turn (ai_org.py finish, dev.py finish,
        workspace_hub.py release) comes here, so Codex and Claude Code get the
        same rotation.
        """
        with self.guard():
            owner = self.require_owner(token)
            if self.control_view()["phase"] == "pending":
                raise ValueError("編集権を返す前に、書き込みを止めて停止を報告してください。")
            self.owner.unlink()
            if not complete_turn:
                return None
            try:
                return self.store.rotate_roles(self.case_id, owner["agent"])
            except (OSError, ValueError) as error:
                # The claim is already returned; never leave it held because of the plan.
                return f"交互：担当予定を入れ替えられませんでした（{error}）。案件画面で確認してください。"

    def work_control(self):
        from workspace_hub import RECORD_ID, bounded_text

        self.store.inside(self.case, self.control)
        try:
            state = json.loads(bounded_text(self.control))
        except FileNotFoundError:
            return {"state": "active", "direction": ""}
        if (not isinstance(state, dict) or state.get("state") not in {"active", "paused"}
                or not isinstance(state.get("direction"), str)
                or not isinstance(state.get("request_id"), str)
                or not RECORD_ID.fullmatch(state["request_id"])
                or not isinstance(state.get("requested_at"), str)
                or any(state.get(field) is not None and (
                    not isinstance(state[field], dict)
                    or not all(isinstance(state[field].get(key), str)
                               for key in ("agent", "at", "claim_id")))
                    for field in ("ack", "confirmation"))):
            raise ValueError("停止・再開の記録が不正です。作業前に状態を確認してください。")
        return state

    def control_view(self):
        state = self.work_control()
        owner = self.current()
        phase = "active"
        if state["state"] == "paused":
            if state.get("ack") and (owner is None or state["ack"]["claim_id"] == owner["claim_id"]):
                phase = "acknowledged"
            else:
                phase = "pending" if owner else "unassigned"
        needs_confirmation = (phase == "active" and "resumed_at" in state and (
            owner is None or (state.get("confirmation") or {}).get("claim_id") != owner["claim_id"]))
        return {**state, "phase": phase, "needs_direction_confirmation": needs_confirmation}

    def save_control(self, state):
        from workspace_hub import replace_json

        self.store.inside(self.case, self.control)
        replace_json(self.control, state)

    def request_pause(self):
        from workspace_hub import now

        with self.guard():
            state = self.work_control()
            if state["state"] != "active":
                raise ValueError("この案件にはすでに停止要求があります。")
            self.save_control({**state, "state": "paused", "request_id": uuid.uuid4().hex,
                               "requested_at": now(), "ack": None})
            return self.control_view()

    def acknowledge_pause(self, token, request_id):
        from workspace_hub import now

        with self.guard():
            owner = self.require_owner(token)
            state = self.control_view()
            if state["phase"] != "pending" or state["request_id"] != request_id:
                raise ValueError("現在の停止要求と一致しないか、すでに停止報告があります。")
            state.pop("phase")
            state.pop("needs_direction_confirmation")
            self.save_control({**state, "ack": {"agent": owner["agent"], "at": now(),
                                                  "claim_id": owner["claim_id"]}})
            return self.control_view()

    def resume(self, request_id, direction):
        from workspace_hub import now

        direction = direction.strip()
        if len(direction) > 12000:
            raise ValueError("再開時の方針は12,000文字以内で入力してください。")
        with self.guard():
            state = self.control_view()
            if state["phase"] not in {"acknowledged", "unassigned"} or state["request_id"] != request_id:
                raise ValueError("現在の停止状態を更新し、担当の停止報告を確認してください。")
            state.pop("phase")
            state.pop("needs_direction_confirmation")
            self.save_control({**state, "state": "active", "resumed_at": now(),
                               "direction": direction or state["direction"], "confirmation": None})
            return self.control_view()

    def confirm_direction(self, token, request_id):
        from workspace_hub import now

        with self.guard():
            owner = self.require_owner(token)
            state = self.work_control()
            if (state["state"] != "active" or "resumed_at" not in state
                    or state["request_id"] != request_id):
                raise ValueError("再開時の方針が更新されたか、案件が停止中です。最新状態を確認してください。")
            if (state.get("confirmation") or {}).get("claim_id") != owner["claim_id"]:
                self.save_control({**state, "confirmation": {
                    "agent": owner["agent"], "at": now(), "claim_id": owner["claim_id"]}})
            return self.control_view()

    def recover(self, claim_id, agent, reason):
        from workspace_hub import now, write_new_json

        agent, reason = agent.strip(), reason.strip()
        if not agent or len(agent) > 100 or not reason or len(reason) > 12000:
            raise ValueError("復旧者と、旧担当が停止した確認内容を指定してください。")
        with self.guard():
            owner = self.current()
            if owner is None or owner["claim_id"] != claim_id:
                raise ValueError("画面で確認した編集権と現在の記録が一致しません。")
            record = self.state / f"recovery-{uuid.uuid4().hex}.json"
            write_new_json(record, {
                "claim_id": claim_id, "previous_agent": owner["agent"], "since": owner["since"],
                "operator": agent, "reason": reason, "created_at": now(),
            })
            self.owner.unlink()
            return record

    @staticmethod
    def file_state(source):
        info = source.stat()
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

    def review_source(self, name):
        relative = PureWindowsPath(name)
        if (not relative.parts or relative.anchor or ".." in relative.parts
                or any(part.startswith(".") or ":" in part for part in relative.parts)
                or relative.parts[0].casefold() in {"feedback", "reviews"}):
            raise ValueError(f"レビュー用コピーに指定できない場所です: {name}")
        source = self.case.joinpath(*relative.parts)
        self.store.inside(self.case, source)
        if source.resolve() != source or not source.is_file():
            raise ValueError(f"案件内の通常ファイルを指定してください: {name}")
        return relative.as_posix(), source

    def review(self, token, paths):
        """Copy explicitly selected files while the writer pauses at a checkpoint."""
        from workspace_hub import MAX_BYTES, now

        with self.guard():
            self.require_owner(token)
            selected = {}
            for name in paths:
                archive_name, source = self.review_source(name)
                if archive_name.casefold() == "review-manifest.json":
                    raise ValueError("REVIEW-MANIFEST.json は予約名です。")
                selected[archive_name.casefold()] = (archive_name, source)
            if not selected:
                raise ValueError("レビュー対象を1件以上指定してください。")
            before = {source: self.file_state(source) for _, source in selected.values()}
            directory = self.case / "reviews"
            self.store.inside(self.case, directory)
            directory.mkdir(exist_ok=True)
            review_id = uuid.uuid4().hex
            file = directory / (review_id + ".zip")
            fd, temp_name = tempfile.mkstemp(dir=directory, suffix=".tmp")
            os.close(fd)
            temp = Path(temp_name)
            try:
                with ZipFile(temp, "w", ZIP_DEFLATED) as archive:
                    hashes = {}
                    for name, source in selected.values():
                        digest = sha256()
                        with source.open("rb") as original, archive.open(name, "w", force_zip64=True) as copy:
                            for chunk in iter(lambda: original.read(1024 * 1024), b""):
                                digest.update(chunk)
                                copy.write(chunk)
                        hashes[name] = digest.hexdigest()
                    manifest = json.dumps(
                        {"case_id": self.case_id, "review_id": review_id,
                         "created_at": now(), "files": hashes}, indent=2).encode("utf-8")
                    if len(manifest) > MAX_BYTES:
                        raise ValueError("レビュー対象を分けてください。マニフェストが大きすぎます。")
                    archive.writestr("REVIEW-MANIFEST.json", manifest)
                for source, state in before.items():
                    if source.resolve() != source or self.file_state(source) != state:
                        raise ValueError(f"コピー中に対象が変更されました。書き込みを止めて再試行してください: {source.name}")
                os.rename(temp, file)
            finally:
                temp.unlink(missing_ok=True)
            return file

    def review_note(self, review_id, agent, note):
        from workspace_hub import MAX_BYTES, RECORD_ID, now, write_new_json

        if not RECORD_ID.fullmatch(review_id):
            raise ValueError("レビューIDが不正です。")
        agent, note = agent.strip(), note.strip()
        if not agent or len(agent) > 100 or not note or len(note) > 12000:
            raise ValueError("担当名（100文字以内）とレビュー内容（12,000文字以内）は必須です。")
        directory = self.case / "reviews"
        snapshot = directory / (review_id + ".zip")
        self.store.inside(self.case, snapshot)
        if not snapshot.is_file():
            raise ValueError("対象のレビュー用コピーが見つかりません。")
        try:
            with ZipFile(snapshot) as review, review.open("REVIEW-MANIFEST.json") as item:
                raw = item.read(MAX_BYTES + 1)
        except (BadZipFile, KeyError) as error:
            raise ValueError("レビュー用コピーを読み取れません。") from error
        if len(raw) > MAX_BYTES:
            raise ValueError("レビューのマニフェストが大きすぎます。")
        manifest = json.loads(raw)
        if (not isinstance(manifest, dict) or manifest.get("case_id") != self.case_id
                or manifest.get("review_id") != review_id or not isinstance(manifest.get("files"), dict)):
            raise ValueError("レビューのマニフェストが一致しません。")
        changed = 0
        for name, digest in manifest["files"].items():
            try:
                _, source = self.review_source(name)
                before = self.file_state(source)
                with source.open("rb") as stream:
                    live = sha256()
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        live.update(chunk)
                if live.hexdigest() != digest or self.file_state(source) != before:
                    changed += 1
            except (ValueError, OSError):
                changed += 1
        target = directory / f"{review_id}-{uuid.uuid4().hex}.json"
        write_new_json(target, {"case_id": self.case_id, "review_id": review_id,
                               "agent": agent, "note": note, "created_at": now(),
                               "changed_or_unreadable_at_report": changed})
        return target, changed
