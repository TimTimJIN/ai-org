"""Experimental Windows UIA adapter. Fail closed; no coordinate/keyboard fallback."""
import json
from pathlib import Path
import subprocess
from core import Snapshot, RelayError


class Native:
    def __init__(self, kind, target, stop_file):
        self.kind, self.target, self.stop_file = kind, target, str(stop_file)

    def call(self, action, **values):
        request = {"kind": self.kind, "target": self.target, "action": action,
                   "stop_file": self.stop_file, **values}
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-File",
             str(Path(__file__).with_name("uia.ps1"))],
            input=json.dumps(request, ensure_ascii=False), encoding="utf-8",
            capture_output=True, timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            result = json.loads(proc.stdout.lstrip("\ufeff"))
        except ValueError:
            raise RelayError("Windows接続に失敗しました。実行ポリシー・UIA対応を確認してください。")
        if not result.get("ok"):
            raise RelayError(result.get("error", "Windows接続エラー"))
        return result

    def snapshot(self):
        result = self.call("read")
        return Snapshot(result["target"], result["draft"], result["busy"],
                        tuple(tuple(t) for t in result["turns"]), result["ready"])

    def send(self, text, before, stop):
        raise RelayError("実アプリ送信は検証待ちです。送信先の一意性・画面の鮮度・回答完了を確認する実装が必要です。")

class Demo:
    """Local simulator; never accesses other apps."""
    def __init__(self, name, target):
        self.name, self.target, self.turns = name, target, []

    def snapshot(self):
        return Snapshot(self.target, "", False, tuple(self.turns), completed=True)

    def send(self, text, before, stop):
        if stop.is_set():
            raise RelayError("停止しました。")
        self.turns.extend([("user", text), ("assistant", f"{self.name}の模擬回答です。送信・受信・回数制御を確認しました。")])
