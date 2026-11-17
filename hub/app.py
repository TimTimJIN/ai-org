"""Chat Relay experimental controller. Launch: python app.py"""
from pathlib import Path
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
from core import Relay, Journal, RelayError, validate
from native import Native, Demo
from data_root import data_root

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("CHAT_RELAY_DATA") or (data_root() / "data"))
DATA.mkdir(parents=True, exist_ok=True)


class App:
    def __init__(self, window):
        self.window, self.events = window, queue.Queue()
        self.stop = threading.Event()
        self.stop_file = DATA / "STOP"
        self.lock_file = DATA / "RUNNING.lock"
        self.running, self.checked, self.checking = False, None, False
        window.title("Chat Relay · 検証版")
        window.geometry("900x760")
        window.minsize(760, 660)
        window.configure(bg="#f3f5f8")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f8")
        style.configure("TLabel", background="#f3f5f8", font=("Yu Gothic UI", 11))
        style.configure("TButton", padding=9, font=("Yu Gothic UI", 10))
        style.configure("Title.TLabel", font=("Yu Gothic UI", 24, "bold"), foreground="#102a43")
        style.configure("Note.TLabel", foreground="#526777", font=("Yu Gothic UI", 10))
        box = ttk.Frame(window, padding=24)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Chat Relay", style="Title.TLabel").pack(anchor="w")
        ttk.Label(box, text="既存の会話をつなぐ  /  Windows検証版・追加モデルAPI不要", style="Note.TLabel").pack(anchor="w", pady=(2, 16))
        self.mode = tk.StringVar(value="demo")
        mode_row = ttk.Frame(box); mode_row.pack(fill="x")
        ttk.Radiobutton(mode_row, text="模擬テスト（外部送信なし）", variable=self.mode, value="demo", command=self.invalidate).pack(side="left")
        ttk.Radiobutton(mode_row, text="実アプリ接続（読取確認のみ）", variable=self.mode, value="native", command=self.invalidate).pack(side="left", padx=20)
        self.gpt = self.entry(box, "ChatGPTのチャット名（画面上と完全一致）", "ChatGPTとClaudeを連携する方法")
        self.claude = self.entry(box, "Claudeの既存チャットURL", "https://claude.ai/chat/8008d32b-9f79-4aed-87e8-0a6925064c95")
        ttk.Label(box, text="議論するテーマ").pack(anchor="w", pady=(12, 5))
        self.topic = tk.Text(box, height=3, font=("Yu Gothic UI", 11), wrap="word", relief="solid", bd=1)
        self.topic.pack(fill="x")
        self.topic.insert("1.0", "既存チャット同士を中継する際の使いやすい運用を検討してください。")
        row = ttk.Frame(box); row.pack(fill="x", pady=12)
        ttk.Label(row, text="往復数").pack(side="left")
        self.rounds = tk.StringVar(value="2")
        ttk.Spinbox(row, from_=1, to=5, textvariable=self.rounds, width=4).pack(side="left", padx=8)
        ttk.Label(row, text="1往復 = ChatGPTの回答 → Claudeの回答", style="Note.TLabel").pack(side="left")
        self.ack = tk.BooleanVar(value=False)
        ttk.Checkbutton(box, text="実アプリではテーマと回答を両サービスへ送り、回答ログをPC内に保存することを確認", variable=self.ack).pack(anchor="w")
        row = ttk.Frame(box); row.pack(fill="x", pady=14)
        self.check_button = ttk.Button(row, text="1. 接続確認", command=self.preflight)
        self.check_button.pack(side="left")
        self.start_button = ttk.Button(row, text="2. 開始", command=self.start, state="disabled")
        self.start_button.pack(side="left", padx=10)
        self.stop_button = ttk.Button(row, text="中継を停止", command=self.cancel, state="disabled")
        self.stop_button.pack(side="right")
        self.status = tk.StringVar(value="まず模擬テストで流れを確認できます。実アプリへの自動送信は未検証です。")
        ttk.Label(box, textvariable=self.status, wraplength=820).pack(anchor="w", pady=(0, 8))
        self.log = tk.Text(box, height=6, wrap="word", font=("Yu Gothic UI", 10), bg="#ffffff", relief="flat", state="disabled")
        self.log.pack(fill="both", expand=True)
        ttk.Label(box, text="停止は次の送信を止めます。送信済み内容・相手側の生成は取り消しません。\n実アプリ接続は、両アプリを開き対象チャットを選択してから行ってください。", style="Note.TLabel").pack(anchor="w", pady=(10, 0))
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.after(100, self.drain)

    def entry(self, parent, title, initial):
        ttk.Label(parent, text=title).pack(anchor="w", pady=(12, 5))
        variable = tk.StringVar(value=initial)
        ttk.Entry(parent, textvariable=variable, font=("Yu Gothic UI", 11)).pack(fill="x")
        variable.trace_add("write", lambda *_: self.invalidate())
        return variable

    def config(self):
        return self.mode.get(), self.gpt.get().strip(), self.claude.get().strip()

    def invalidate(self):
        self.checked = None
        if hasattr(self, "start_button"):
            self.start_button.configure(state="disabled")

    def adapters(self, config):
        mode, gpt, claude = config
        if not gpt or not claude.startswith("https://claude.ai/chat/"):
            raise RelayError("チャット名とClaudeの既存チャットURLを指定してください。")
        if mode == "demo":
            return [Demo("ChatGPT", gpt), Demo("Claude", claude)]
        return [Native("chatgpt", gpt, self.stop_file), Native("claude", claude, self.stop_file)]

    def preflight(self):
        if self.running or self.checking:
            return
        self.checking = True
        config = self.config()
        self.invalidate()
        self.check_button.configure(state="disabled")
        self.status.set("接続確認中 · メッセージは送信しません")
        def worker():
            try:
                for adapter, target in zip(self.adapters(config), config[1:]):
                    snap = adapter.snapshot()
                    validate(snap, target)
                    if snap.busy:
                        raise RelayError("回答中です。完了後に再確認してください。")
                self.events.put(("checked", config))
            except Exception as error:
                self.events.put(("error", str(error)))
            finally:
                self.events.put(("check_finished", None))
        threading.Thread(target=worker, daemon=True).start()

    def start(self):
        config = self.config()
        if self.running or self.checking or config != self.checked:
            return
        if config[0] == "native":
            self.status.set("実アプリへの送信は検証待ちです。現在は読取確認のみ利用できます。")
            return
        if config[0] == "native" and not self.ack.get():
            messagebox.showinfo("送信範囲", "送信先・ログ保存についてチェックしてください。")
            return
        try:
            rounds = int(self.rounds.get())
            topic = self.topic.get("1.0", "end").strip()
            if not topic or len(topic) > 2000 or not 1 <= rounds <= 5:
                raise ValueError()
        except ValueError:
            self.status.set("テーマを2,000文字以内、往復数を1〜5で入力してください。")
            return
        try:
            fd = os.open(self.lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode()); os.close(fd)
        except OSError as error:
            self.status.set(f"開始できません。別の実行・保存先の権限を確認してください: {error}")
            return
        self.stop.clear()
        self.stop_file.unlink(missing_ok=True)
        self.running = True
        self.start_button.configure(state="disabled")
        self.check_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        path = DATA / "logs" / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".jsonl")
        def worker():
            try:
                relay = Relay(self.adapters(config), config[1:], Journal(path), self.stop,
                              lambda line: self.events.put(("log", line)),
                              stable=0.2 if config[0] == "demo" else 6,
                              poll=0.1 if config[0] == "demo" else 2)
                relay.run(topic, rounds)
                self.events.put(("log", f"ログ: {path}"))
            except Exception as error:
                Journal(path).write("stopped", reason=str(error))
                self.events.put(("error", str(error)))
            finally:
                try:
                    self.lock_file.unlink(missing_ok=True)
                finally:
                    self.events.put(("finished", None))
        threading.Thread(target=worker, daemon=True).start()

    def cancel(self):
        self.stop.set()
        try:
            self.stop_file.touch()
        except OSError as error:
            self.events.put(("error", f"停止は要求済みですが、停止ファイルを保存できません: {error}"))
        self.status.set("停止要求済み · 実行中の処理終了を待っています")

    def drain(self):
        while not self.events.empty():
            event, value = self.events.get_nowait()
            if event == "check_finished":
                self.checking = False
                self.check_button.configure(state="normal")
            elif event == "checked":
                self.check_button.configure(state="normal")
                if value == self.config():
                    self.checked = value
                    if value[0] == "demo":
                        self.start_button.configure(state="normal")
                        self.status.set("接続確認できました。開始すると指定回数だけ模擬中継します。")
                    else:
                        self.status.set("読取確認できました。実アプリ送信は検証待ちのため無効です。")
            elif event == "finished":
                self.running = False
                self.check_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                self.invalidate()
            elif event in ("log", "error"):
                self.status.set(value[:150])
                self.log.configure(state="normal")
                self.log.insert("end", value + "\n\n")
                self.log.see("end")
                self.log.configure(state="disabled")
                if event == "error" and not self.running:
                    self.check_button.configure(state="normal")
        self.window.after(100, self.drain)

    def close(self):
        if self.running:
            self.cancel()
            self.status.set("中継停止を待っています。処理終了後に閉じてください。")
        else:
            self.window.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
