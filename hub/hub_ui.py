"""Desktop entry point for existing Codex / Claude Code workspaces."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from case_editing import CaseEditing
from case_guide import (DEFAULT_ALTERNATE, DEFAULT_PLAN, ROLE_PLANS, draft_from_text, load_case_draft,
                        next_step, plan_label, start_instruction)
from workspace_hub import CaseStore

PLAN_BY_LABEL = {plan_label(plan): plan for plan in ROLE_PLANS}
# 交互の意味をチェックボックスの横に短く常に出す（docs/DESIGN.md 原則4）。
ALTERNATE_TEXT = "交互（作業を終えるたびに実装とレビューを入れ替え）"
FONT = "Yu Gothic UI"

# Colours follow docs/DESIGN.md (contrast checked: text 4.5:1, borders 3:1).
BG, TEXT, SUBTLE, BORDER = "#f4f6fa", "#172b42", "#526579", "#7b8794"
PRIMARY, PRIMARY_HOVER = "#0b5cad", "#094a8c"
SELECT_BG, SELECT_FG = "#e8f1fb", "#0b5cad"
TONES = {  # status tone -> (text colour, badge background)
    "ok": ("#1d6b3a", "#e6f4ea"),
    "wait": ("#8a4b00", "#fdf1e1"),
    "stop": ("#a1261b", "#fdecea"),
    "none": (SUBTLE, "#e9edf2"),
}


def case_status(store, case_id):
    """Read one case's pause/resume state and edit claim, and name it in the
    words the list and the badge share. Never raises: a broken record shows as
    「要確認」 so one bad case cannot break the whole list."""
    result = {"control": None, "owner": None, "owner_error": None,
              "label": "要確認", "tone": "stop"}
    try:
        editing = CaseEditing(store, case_id)
    except (OSError, ValueError) as error:
        result["owner_error"] = str(error)
        return result
    try:
        control = editing.control_view()
    except (OSError, ValueError):
        control = None
    # Read the claim separately so a broken owner record is reported, never shown as 「空き」.
    try:
        result["owner"] = editing.current()
    except (OSError, ValueError) as error:
        result["owner_error"] = str(error)
    if control is None:
        return result
    result["control"] = control
    phase, owner = control["phase"], result["owner"]
    if phase == "pending":
        label, tone = "停止要求中", "wait"
    elif phase in {"acknowledged", "unassigned"}:
        label, tone = "停止中", "stop"
    elif control["needs_direction_confirmation"] and owner:
        label, tone = "再開待ち", "wait"
    elif owner:
        label, tone = "作業中", "ok"
    elif result["owner_error"]:
        label, tone = "要確認", "stop"
    else:
        label, tone = "開始待ち", "none"
    result.update(label=label, tone=tone)
    return result


class NewCaseDialog:
    """New case form. A chat-made JSON only fills the form as an editable draft;
    nothing is saved until the user presses the normal create button."""

    def __init__(self, hub):
        self.hub = hub
        self.draft_id = None
        self.dialog = dialog = tk.Toplevel(hub.window)
        dialog.title("案件を作る")
        dialog.geometry("640x580")
        dialog.minsize(520, 440)
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        # Bottom area is packed first so it keeps its space; the text boxes shrink instead.
        bottom = ttk.Frame(frame)
        bottom.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Label(bottom, text="担当予定（後で変更可・編集権とは別）").pack(anchor="w")
        self.plan = tk.StringVar(value=DEFAULT_PLAN)
        plans = ttk.Frame(bottom)
        plans.pack(fill="x")
        for plan in ROLE_PLANS:
            ttk.Radiobutton(plans, text=plan_label(plan), value=plan, variable=self.plan).pack(side="left", padx=(0, 12))
        self.alternate = tk.BooleanVar(value=DEFAULT_ALTERNATE)
        ttk.Checkbutton(bottom, text=ALTERNATE_TEXT, variable=self.alternate).pack(anchor="w", pady=(4, 0))
        footer = ttk.Frame(bottom)
        footer.pack(fill="x", pady=(8, 0))
        self.create_button = ttk.Button(footer, text="作業場所を作成", command=self.create)
        self.create_button.pack(side="right")
        self.create_and_copy = ttk.Button(footer, text="作成して指示をコピー",
                                          command=lambda: self.create(copy_instruction=True))
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="何を作りたいですか？", font=(FONT, 15, "bold")).pack(side="left")
        ttk.Button(top, text="JSONを読み込む…", command=self.choose_draft).pack(side="right")
        self.draft_info = tk.StringVar(value="直接入力、またはチャットで作ったUTF-8のJSONを下書きとして読み込めます。")
        ttk.Label(frame, textvariable=self.draft_info, style="Sub.TLabel", wraplength=580).pack(anchor="w", pady=(4, 8))
        ttk.Label(frame, text="案件名（必須・100文字以内）").pack(anchor="w")
        self.title = ttk.Entry(frame, font=(FONT, 11))
        self.title.pack(fill="x", pady=(2, 8))
        ttk.Label(frame, text="依頼内容（必須・12,000文字以内）").pack(anchor="w")
        self.objective = tk.Text(frame, height=3, wrap="word", font=(FONT, 11))
        self.objective.pack(fill="both", expand=True, pady=(2, 8))
        ttk.Label(frame, text="完成の目安（任意・12,000文字以内）").pack(anchor="w")
        self.acceptance = tk.Text(frame, height=2, wrap="word", font=(FONT, 11))
        self.acceptance.pack(fill="both", expand=True, pady=(2, 0))
        dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.title.focus_set()

    def values(self):
        return (self.title.get(), self.objective.get("1.0", "end-1c"), self.acceptance.get("1.0", "end-1c"))

    def dirty(self):
        return any(value.strip() for value in self.values())

    def choose_draft(self):
        path = filedialog.askopenfilename(parent=self.dialog, title="チャットで作った案件JSONを選択",
                                          filetypes=[("JSON", "*.json"), ("すべてのファイル", "*.*")])
        if path:
            self.load_draft(path)

    def load_draft(self, path):
        try:
            draft = load_case_draft(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("JSONを読み込めません", str(error), parent=self.dialog)
            return False
        if self.dirty() and not messagebox.askyesno(
                "入力中の内容", "入力中の内容を読み込んだ下書きで置き換えますか？", parent=self.dialog):
            return False
        self.draft_id = None
        self.create_button.configure(text="作業場所を作成")
        self.create_and_copy.pack_forget()
        self.fill_draft(draft)
        self.draft_info.set(f"下書きとして「{Path(path).name}」を読み込みました（まだ作成していません）。"
                            "内容と担当予定を確認・編集し「作業場所を作成」を押すと確定します。")
        return True

    def fill_draft(self, draft):
        self.title.delete(0, "end")
        self.title.insert(0, draft["title"])
        for widget, key in ((self.objective, "objective"), (self.acceptance, "acceptance")):
            widget.delete("1.0", "end")
            widget.insert("1.0", draft[key])

    def open_inbox_draft(self, draft_id, draft):
        self.draft_id = draft_id
        self.fill_draft(draft)
        self.draft_info.set("内容と担当を確認して作成したら、元の会話で「進めて」。別の会話に渡す場合は指示をコピーします。")
        self.create_button.configure(text="この内容で作成")
        self.create_and_copy.pack(side="right", padx=(0, 8))

    def open_copied_draft(self, draft):
        self.fill_draft(draft)
        self.plan.set("claude-implements")
        self.draft_info.set("コピーした回答を下書きにしました。内容と担当を確認して作成します。")
        self.create_and_copy.pack(side="right", padx=(0, 8))

    def create(self, *, copy_instruction=False):
        hub = self.hub
        pending = hub.unsaved_message() if hub.selected else ""
        if pending:
            messagebox.showinfo("未保存の内容", f"先に現在の案件の{pending}を保存するか、元に戻してください。", parent=self.dialog)
            return None
        try:
            task = hub.store.create(*self.values(), plan=self.plan.get(), draft_id=self.draft_id,
                                    alternate=self.alternate.get())
        except (OSError, ValueError) as error:
            messagebox.showerror("案件を作成できません", str(error), parent=self.dialog)
            return None
        # Drop the previous case's role state so it is never carried to the new case.
        hub.roles = None
        hub.selected = task["id"]
        self.dialog.destroy()
        hub.refresh()
        hub.notice.set("案件を準備しました。上部の「次の操作」に沿って開始指示をコピーしてください。AIはまだ起動していません。")
        if copy_instruction:
            hub.copy_start("implementer")
        elif self.draft_id:
            hub.notice.set("案件を作成しました。同じ担当で続ける場合は、下書きを出した会話で「進めて」と伝えます。")
        return task

    def close(self):
        if self.dirty() and not messagebox.askyesno(
                "未作成の下書き", "入力中の内容は保存されていません。破棄して閉じますか？", parent=self.dialog):
            return
        self.dialog.destroy()


class Hub:
    def __init__(self, window, store=None):
        self.window, self.store = window, store or CaseStore()
        self.selected = None
        self.work_state = None
        self.roles = None
        self.unreported = 0
        window.title("AI自律基盤 · 案件ワークスペース")
        window.geometry("1100x680")
        window.minsize(920, 620)
        window.configure(bg=BG)
        style = ttk.Style(window)
        style.theme_use("clam")
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT, font=(FONT, 10))
        style.configure("TRadiobutton", background=BG, font=(FONT, 10))
        style.configure("TCheckbutton", background=BG, foreground=TEXT, font=(FONT, 10))
        style.map("TCheckbutton", background=[("active", BG), ("disabled", BG)])
        style.configure("TButton", font=(FONT, 10), padding=(10, 5))
        # One primary button at a time: the one the "next step" asks for.
        style.configure("Primary.TButton", font=(FONT, 10, "bold"), padding=(12, 5),
                        background=PRIMARY, foreground="#ffffff", bordercolor=PRIMARY,
                        lightcolor=PRIMARY, darkcolor=PRIMARY, focuscolor="#ffffff")
        primary_states = [("disabled", "#dcdad5"), ("pressed", PRIMARY_HOVER), ("active", PRIMARY_HOVER)]
        style.map("Primary.TButton", background=primary_states, foreground=[("disabled", "#a3a3a3")],
                  bordercolor=[("disabled", BORDER), ("pressed", PRIMARY_HOVER), ("active", PRIMARY_HOVER)],
                  lightcolor=primary_states, darkcolor=primary_states)
        style.configure("Title.TLabel", font=(FONT, 18, "bold"))
        style.configure("Sub.TLabel", foreground=SUBTLE)
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1, bordercolor=BORDER)
        style.configure("Plain.TFrame", background="#ffffff", borderwidth=0)
        style.configure("Card.TLabel", background="#ffffff", foreground=TEXT, font=(FONT, 10))
        style.configure("Card.TCheckbutton", background="#ffffff", foreground=TEXT, font=(FONT, 10))
        style.map("Card.TCheckbutton", background=[("active", "#ffffff"), ("disabled", "#ffffff")])
        style.configure("Next.TLabel", background="#ffffff", foreground="#0b4f8a", font=(FONT, 11, "bold"))
        for name in ("TEntry", "TCombobox"):
            style.configure(name, bordercolor=BORDER)
        style.configure("Treeview", font=(FONT, 11), rowheight=36, bordercolor=BORDER)
        # Same selection colours whether or not the window is in front (clam greys it otherwise).
        style.map("Treeview",
                  background=[("disabled", "#dcdad5"), ("selected", SELECT_BG)],
                  foreground=[("disabled", "#a3a3a3"), ("selected", SELECT_FG)])
        box = ttk.Frame(window, padding=(16, 10))
        box.pack(fill="both", expand=True)
        header = ttk.Frame(box)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="案件から、作業をはじめる", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="依頼・成果物・コメントを一つの作業場所へ", style="Sub.TLabel").pack(side="left", padx=(14, 0), pady=(8, 0))
        self.notice = tk.StringVar(value="案件準備・引き継ぎ用の画面です。AIの自動起動・常駐運転・外部送信は行いません。")
        ttk.Label(box, textvariable=self.notice, style="Sub.TLabel", wraplength=1000).pack(side="bottom", anchor="w", pady=(6, 0))
        body = ttk.Frame(box)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, width=270)
        left.pack(side="left", fill="y", padx=(0, 22))
        list_head = ttk.Frame(left)
        list_head.pack(fill="x", pady=(0, 6))
        ttk.Label(list_head, text="案件一覧", font=(FONT, 11, "bold")).pack(side="left")
        ttk.Button(list_head, text="＋ 案件を作る", command=self.new_case).pack(side="right")
        # Buttons are packed before the list so they stay visible on short screens.
        # Less frequent ways in (import, inbox) and the manual refresh sit below the list.
        ttk.Button(left, text="一覧・進捗を更新", command=self.refresh).pack(side="bottom", fill="x")
        ttk.Button(left, text="受け取った依頼", command=self.open_inbox).pack(side="bottom", fill="x", pady=(0, 6))
        self.paste_claude_button = ttk.Button(left, text="Claudeの回答を取り込む", command=self.import_claude_reply)
        self.paste_claude_button.pack(side="bottom", fill="x", pady=(8, 6))
        # Each row shows its state in words, so the user need not open every case.
        self.tree = ttk.Treeview(left, columns=("title", "state"), show="", selectmode="browse", height=4)
        self.tree.column("title", width=180, stretch=True)
        self.tree.column("state", width=86, stretch=False, anchor="e")
        # Rows keep the tone as a tag but are not coloured: Treeview can only colour
        # whole rows, which tinted the case names too. Colour lives in the badge.
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.select)
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        # Case name, its state badge and the pause/resume controls share one row,
        # so the state sits next to what it describes.
        title_row = ttk.Frame(right)
        title_row.pack(fill="x")
        self.work_label = tk.StringVar(value="")
        self.resume_button = ttk.Button(title_row, text="方針を確認して再開", command=self.resume_work, state="disabled")
        self.resume_button.pack(side="right", padx=(6, 0))
        self.pause_button = ttk.Button(title_row, text="一時停止を要求", command=self.pause_work, state="disabled")
        self.pause_button.pack(side="right")
        self.heading = tk.StringVar(value="最初の案件を作成してください")
        self.heading_label = ttk.Label(title_row, textvariable=self.heading, font=(FONT, 14, "bold"), wraplength=420)
        self.heading_label.pack(side="left")
        self.badge = tk.Label(title_row, textvariable=self.work_label, font=(FONT, 10, "bold"),
                              padx=8, pady=1, bg=BG, fg=SUBTLE)
        self.badge.pack(side="left", padx=(10, 0))
        self.title_row = title_row
        # A long case name wraps instead of pushing the badge (packed later) out of sight.
        title_row.bind("<Configure>", lambda _event: self.fit_heading())

        # Summary card: who acts, what to do next, and the hand-over buttons.
        card = ttk.Frame(right, style="Card.TFrame", padding=(10, 6))
        card.pack(fill="x", pady=(4, 6))
        role_row = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        role_row.pack(fill="x")
        ttk.Label(role_row, text="担当予定", style="Card.TLabel", font=(FONT, 10, "bold")).pack(side="left")
        self.role_choice = tk.StringVar(value=plan_label(DEFAULT_PLAN))
        self.role_box = ttk.Combobox(role_row, textvariable=self.role_choice, state="disabled",
                                     values=list(PLAN_BY_LABEL), width=32, font=(FONT, 10))
        self.role_box.pack(side="left", padx=(8, 6))
        self.role_box.bind("<<ComboboxSelected>>", lambda _event: self.update_role_state())
        self.role_alternate = tk.BooleanVar(value=False)
        self.role_alternate_box = ttk.Checkbutton(role_row, text="交互", variable=self.role_alternate, state="disabled",
                                                  command=self.update_role_state, style="Card.TCheckbutton")
        self.role_alternate_box.pack(side="left", padx=(0, 6))
        self.role_save = ttk.Button(role_row, text="保存", command=self.save_roles, state="disabled")
        self.role_save.pack(side="left")
        self.role_state = tk.StringVar(value="")
        ttk.Label(role_row, textvariable=self.role_state, style="Card.TLabel", foreground="#526579").pack(side="left", padx=(8, 0))
        self.owner_label = tk.StringVar(value="編集権: —")
        ttk.Label(card, textvariable=self.owner_label, style="Card.TLabel").pack(anchor="w", pady=(4, 0))
        self.next_label = tk.StringVar(value="次の操作: 案件を選択してください")
        ttk.Label(card, textvariable=self.next_label, style="Next.TLabel", wraplength=700).pack(anchor="w", pady=(2, 6))
        hand = ttk.Frame(card, style="Card.TFrame", borderwidth=0)
        hand.pack(fill="x")
        self.copy_impl = ttk.Button(hand, text="実装向け指示をコピー", command=lambda: self.copy_start("implementer"), state="disabled")
        self.copy_impl.pack(side="left", padx=(0, 6))
        self.copy_review = ttk.Button(hand, text="レビュー向け指示をコピー…", command=self.choose_review, state="disabled")
        self.copy_review.pack(side="left", padx=(0, 6))
        self.open_outputs_button = ttk.Button(hand, text="成果物を開く", command=self.open_outputs, state="disabled")
        self.open_outputs_button.pack(side="left")
        ttk.Label(hand, text="貼り付けは手動・自動送信なし", style="Card.TLabel", foreground="#526579").pack(side="left", padx=(8, 0))

        # Location and folder actions share one row to save vertical space.
        self.location = tk.StringVar(value="作業場所は案件ごとに自動で作成します")
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(0, 4))
        self.actions = [self.copy_impl, self.copy_review, self.open_outputs_button]
        for label, action in (("場所をコピー", self.copy_path), ("フォルダーを開く", self.open_folder)):
            button = ttk.Button(actions, text=label, command=action, state="disabled")
            button.pack(side="right", padx=(6, 0))
            self.actions.append(button)
        ttk.Entry(actions, textvariable=self.location, state="readonly").pack(side="left", fill="x", expand=True)
        self.tabs = ttk.Notebook(right)
        self.views = {}
        for key, label in (("task", "依頼"), ("status", "進捗・成果物"), ("feedback", "修正コメント")):
            frame = ttk.Frame(self.tabs)
            self.tabs.add(frame, text=label)
            # spacing2 widens wrapped lines towards the 1.5 line height in docs/DESIGN.md.
            text = tk.Text(frame, height=3, wrap="word", font=(FONT, 11), padx=12, pady=8, relief="flat", bg="white",
                           spacing2=5, spacing3=5, state="disabled")
            scroll = ttk.Scrollbar(frame, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            scroll.pack(side="right", fill="y")
            text.pack(fill="both", expand=True)
            self.views[key] = text
        comment_section = ttk.Frame(right)
        comment_section.pack(side="bottom", fill="x")
        comment_head = ttk.Frame(comment_section)
        comment_head.pack(fill="x", pady=(6, 2))
        ttk.Label(comment_head, text="修正したい点・追加の依頼", font=(FONT, 11, "bold")).pack(side="left")
        ttk.Label(comment_head, text="担当AIが次にファイルを読むときに反映（即時通知・強制停止なし）", style="Sub.TLabel").pack(side="left", padx=(10, 0))
        self.save = ttk.Button(comment_section, text="コメントを保存", command=self.add_comment, state="disabled")
        self.save.pack(side="right", anchor="n", padx=(6, 0))
        self.comment = tk.Text(comment_section, height=2, wrap="word", font=(FONT, 11), relief="solid", bd=1)
        self.comment.pack(side="left", fill="x", expand=True)
        self.tabs.pack(fill="both", expand=True)
        self.refresh()
        window.after(1500, self.poll_work)
        window.protocol("WM_DELETE_WINDOW", self.close)

    # --- roles -----------------------------------------------------------
    def chosen_plan(self):
        return PLAN_BY_LABEL.get(self.role_choice.get())

    def role_dirty(self):
        return bool(self.roles) and (self.chosen_plan() != self.roles["plan"]
                                     or self.role_alternate.get() != self.roles["alternate"])

    def update_role_state(self):
        if not self.roles:
            self.role_state.set("")
            self.role_save.configure(state="disabled")
            return
        if self.role_dirty():
            text = "未保存の変更があります"
        elif self.roles["warning"]:
            text = "要確認（既定値を表示）"
        elif self.roles["saved"]:
            text = "保存済み"
        else:
            text = "既定値（未保存）"
        self.role_state.set(text)
        can_save = self.role_dirty() or not self.roles["saved"]
        self.role_save.configure(state="normal" if can_save else "disabled")

    def load_roles(self, case_id):
        self.roles = self.store.roles(case_id)
        self.role_choice.set(plan_label(self.roles["plan"]))
        self.role_alternate.set(self.roles["alternate"])
        self.role_box.configure(state="readonly")
        self.role_alternate_box.configure(state="normal")
        if self.roles["warning"]:
            self.notice.set(self.roles["warning"])
        self.update_role_state()

    def save_roles(self):
        plan = self.chosen_plan()
        if not self.selected or not self.roles or plan is None:
            return
        try:
            alternate = self.role_alternate.get()
            self.roles = self.store.set_roles(self.selected, plan, self.roles["revision"], alternate)
            self.notice.set(f"担当予定を「{plan_label(plan, alternate)}」で保存しました。編集権は変わりません。")
        except (OSError, ValueError) as error:
            self.report_error(error)
            try:
                self.load_roles(self.selected)
            except (OSError, ValueError):
                pass
        self.update_role_state()
        self.update_work_controls()

    def reload_rotated_roles(self):
        """Show a plan swapped by an AI's finish (交互) without touching unsaved choices."""
        if not self.selected or not self.roles or self.role_dirty():
            return
        try:
            latest = self.store.roles(self.selected)
        except (OSError, ValueError):
            return
        if latest["revision"] != self.roles["revision"]:
            before = self.roles["plan"]
            self.load_roles(self.selected)
            self.update_work_controls()
            if latest["saved"] and latest["alternate"] and latest["plan"] != before:
                self.notice.set(f"交互で担当予定が入れ替わりました：{plan_label(latest['plan'], True)}")

    # --- work state / summary ------------------------------------------
    def fit_heading(self):
        used = sum(w.winfo_reqwidth() for w in (self.badge, self.pause_button, self.resume_button)) + 24
        width = max(160, self.title_row.winfo_width() - used)
        if int(str(self.heading_label.cget("wraplength")) or 0) != width:
            self.heading_label.configure(wraplength=width)

    def poll_work(self):
        try:
            self.update_work_controls()
            self.update_list_states()
            self.reload_rotated_roles()
        finally:  # an unexpected error must not stop polling for good
            self.window.after(1500, self.poll_work)

    def show_list_state(self, case_id, status):
        # tree.set never touches the selection, so polling cannot steal it.
        if self.tree.exists(case_id):
            self.tree.set(case_id, "state", status["label"])
            self.tree.item(case_id, tags=(status["tone"],))

    def update_list_states(self):
        for case_id in self.tree.get_children():
            if case_id != self.selected:  # the selected case is refreshed by update_work_controls
                self.show_list_state(case_id, case_status(self.store, case_id))

    def update_work_controls(self):
        self.work_state = None
        phase = None
        owner, owner_error = None, None
        if self.selected:
            status = case_status(self.store, self.selected)
            self.work_state, owner, owner_error = status["control"], status["owner"], status["owner_error"]
            phase = (self.work_state or {}).get("phase")
            fg, bg = TONES[status["tone"]]
            self.work_label.set(status["label"])
            self.badge.configure(fg=fg, bg=bg)
            self.show_list_state(self.selected, status)
        else:
            self.work_label.set("")
            self.badge.configure(fg=SUBTLE, bg=BG)
        self.pause_button.configure(state="normal" if phase == "active" else "disabled")
        self.resume_button.configure(state="normal" if phase in {"acknowledged", "unassigned"} else "disabled")
        self.update_summary(owner, owner_error)
        self.mark_primary(owner, owner_error)
        self.fit_heading()

    def primary_button(self, owner, owner_error=None):
        """The button for the step next_step() describes, or None when the
        user only has to wait. Mirrors the branches of case_guide.next_step
        (update_summary passes control=None when the claim is unreadable)."""
        control = self.work_state
        if not self.selected or not self.roles or control is None or owner_error:
            return None
        if control["phase"] in {"acknowledged", "unassigned"}:
            return self.resume_button
        if control["phase"] == "pending" or (control["needs_direction_confirmation"] and owner):
            return None
        return self.copy_review if owner else self.copy_impl

    def mark_primary(self, owner, owner_error=None):
        primary = self.primary_button(owner, owner_error)
        for button in (self.copy_impl, self.copy_review, self.resume_button):
            style = "Primary.TButton" if button is primary else "TButton"
            if button.cget("style") != style:
                button.configure(style=style)

    def update_summary(self, owner, owner_error=None):
        if not self.selected or not self.roles:
            self.owner_label.set("編集権: —")
            self.next_label.set("次の操作: 案件を選択するか、新しい案件を作成してください")
            return
        if owner_error:
            self.owner_label.set(f"編集権: 要確認（{owner_error}）")
        elif owner:
            self.owner_label.set(f"編集権: {owner['agent']} が保持（担当予定とは別に記録）")
        else:
            self.owner_label.set("編集権: 空き（担当予定とは別。作業開始時に claim で取得）")
        control = self.work_state if not owner_error else None
        who, action = next_step(self.roles["plan"], control, owner, self.unreported)
        self.next_label.set(f"いまの担当: {who}　次の操作: {action}")

    def pause_work(self):
        try:
            CaseEditing(self.store, self.selected).request_pause()
            self.select()
            self.notice.set("停止要求を保存しました。急いで止める場合は作業中のアプリでも停止してください。")
        except (OSError, ValueError) as error:
            self.report_error(error)

    def resume_work(self):
        case_id, state = self.selected, self.work_state
        if not state or state["phase"] not in {"acknowledged", "unassigned"}:
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("再開時の方針")
        dialog.geometry("580x340")
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="再開時に担当へ伝える方針").pack(anchor="w", pady=(0, 8))
        ttk.Label(frame, text="同じ方針で再開する場合は空欄のまま進めます。").pack(anchor="w")
        direction = tk.Text(frame, wrap="word", height=6, font=(FONT, 11))
        direction.pack(fill="both", expand=True, pady=8)
        def resume():
            try:
                CaseEditing(self.store, case_id).resume(state["request_id"], direction.get("1.0", "end"))
                dialog.destroy()
                self.select()
                self.notice.set("再開を記録しました。担当AIが次に状態と方針を確認します。")
            except (OSError, ValueError) as error:
                messagebox.showerror("再開できませんでした", str(error), parent=dialog)
        ttk.Button(frame, text="方針を保存して再開", command=resume).pack(anchor="e")
        direction.focus_set()

    def unsaved_message(self):
        parts = []
        if self.comment.get("1.0", "end").strip():
            parts.append("入力中のコメント")
        if self.role_dirty():
            parts.append("未保存の担当予定")
        return "・".join(parts)

    def close(self):
        pending = self.unsaved_message()
        if pending and not messagebox.askyesno("未保存の内容", f"{pending}を破棄して閉じますか？", parent=self.window):
            return
        self.window.destroy()

    def report_error(self, error):
        messagebox.showerror("操作を完了できませんでした", str(error), parent=self.window)

    def display(self, key, value):
        widget = self.views[key]
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def set_actions(self, state):
        for button in self.actions + [self.save]:
            button.configure(state=state)

    def refresh(self):
        try:
            cases, warnings = self.store.list()
            selected = self.selected
            for item in self.tree.get_children():
                self.tree.delete(item)
            for case in cases:
                status = case_status(self.store, case["id"])
                self.tree.insert("", "end", iid=case["id"], values=(case["title"], status["label"]),
                                 tags=(status["tone"],))
            if selected and self.tree.exists(selected):
                self.tree.selection_set(selected)
                self.select()
            elif cases:
                self.tree.selection_set(cases[0]["id"])
                self.select()
            else:
                self.selected = None
                self.roles = None
                self.role_box.configure(state="disabled")
                self.role_alternate_box.configure(state="disabled")
                self.update_role_state()
                self.update_work_controls()
                self.heading.set("最初の案件を作成してください")
                self.location.set("作業場所は案件ごとに自動で作成します")
                for view in self.views:
                    self.display(view, "")
                self.set_actions("disabled")
            if warnings:
                self.notice.set(f"{len(warnings)}件を読み取れません。対象の記録を確認してください。 " + warnings[0])
        except (OSError, ValueError) as error:
            self.report_error(error)

    def select(self, _event=None):
        selection = self.tree.selection()
        if not selection:
            return
        next_id = selection[0]
        if self.selected and self.selected != next_id:
            pending = self.unsaved_message()
            if pending:
                if not messagebox.askyesno("未保存の内容", f"{pending}を破棄して別の案件へ移動しますか？", parent=self.window):
                    self.tree.selection_set(self.selected)
                    return
                self.comment.delete("1.0", "end")
        try:
            task, status, comments = self.store.details(next_id, tolerate_corruption=True)
            same_case = self.selected == next_id
            self.selected = next_id
            if not (same_case and self.role_dirty()):
                self.load_roles(next_id)
            self.unreported = sum(1 for entry in comments if "report" not in entry)
            self.update_work_controls()
            self.heading.set(task["title"])
            self.location.set(str(self.store.folder(next_id)))
            direction = (self.work_state or {}).get("direction")
            prefix = "現在の方針\n\n" + direction + "\n\n" if direction else ""
            self.display("task", prefix + "依頼内容\n\n" + task["objective"] + "\n\n完成の目安\n\n" + (task["acceptance"] or "実行担当が目的から整理します。") + "\n\n案件ID\n" + next_id)
            try:
                owner = CaseEditing(self.store, next_id).current()
                edit_status = f"{owner['agent']}（{owner['since']}）\n編集権ID: {owner['claim_id']}" if owner else "空き"
            except (OSError, ValueError) as error:
                edit_status = f"要確認（{error}）"
            self.display("status", f"担当予定: {plan_label(self.roles['plan'], self.roles['alternate'])}\n編集権: {edit_status}\n\n" + status)
            comment_text = []
            for entry in comments:
                item = f"{entry['application']}\n{entry['created_at']}\nID: {entry['id']}\n\n{entry['message']}"
                if "report" in entry:
                    item += f"\n\n担当（自己申告）: {entry['report']['agent']}\n反映内容: {entry['report']['note']}"
                comment_text.append(item)
            self.display("feedback", "\n\n────────\n\n".join(comment_text) or "まだコメントはありません。")
            if "## 読み取り警告" in status:
                self.notice.set("一部のコメント・反映報告を読み取れません。「進捗・成果物」の警告を確認してください。")
            self.set_actions("normal")
        except (OSError, ValueError, TypeError) as error:
            self.set_actions("disabled")
            self.report_error(error)

    def new_case(self):
        return NewCaseDialog(self)

    def import_claude_reply(self):
        try:
            draft = draft_from_text(self.window.clipboard_get())
        except tk.TclError:
            self.report_error("Claudeで依頼にしたい回答をコピーしてから押してください。")
            return None
        except ValueError as error:
            self.report_error(error)
            return None
        form = self.new_case()
        form.open_copied_draft(draft)
        return form

    def open_inbox(self):
        try:
            drafts, warnings = self.store.pending_drafts()
        except (OSError, ValueError) as error:
            self.report_error(error)
            return
        if warnings:
            self.notice.set(f"受信箱に読み取れない下書きが {warnings} 件あります。")
        if not drafts:
            messagebox.showinfo("受け取った依頼", "未登録の下書きはありません。", parent=self.window)
            return

        def open_draft(draft_id):
            try:
                draft = self.store.inbox_draft(draft_id)
            except (OSError, ValueError) as error:
                self.report_error(error)
                return
            self.new_case().open_inbox_draft(draft_id, draft)

        if len(drafts) == 1:
            open_draft(drafts[0][0])
            return
        picker = tk.Toplevel(self.window)
        picker.title("受け取った依頼")
        picker.geometry("560x280")
        picker.grab_set()
        ttk.Label(picker, text="案件にする下書きを選んでください。").pack(anchor="w", padx=16, pady=8)
        choices = tk.Listbox(picker, exportselection=False, font=(FONT, 11))
        choices.pack(fill="both", expand=True, padx=16)
        for draft_id, draft in drafts:
            choices.insert("end", f"{draft['title']}   [{draft_id[:8]}]")

        def choose(_event=None):
            selected = choices.curselection()
            if selected:
                picker.destroy()
                open_draft(drafts[selected[0]][0])

        ttk.Button(picker, text="下書きを開く", command=choose).pack(anchor="e", padx=16, pady=8)
        choices.bind("<Double-1>", choose)
        choices.bind("<Return>", choose)
        choices.focus_set()

    def copy(self, text):
        self.window.clipboard_clear()
        self.window.clipboard_append(text)
        self.window.update_idletasks()

    def copy_path(self):
        self.copy(str(self.store.folder(self.selected)))
        self.notice.set("作業場所をコピーしました。Codex／Claude Codeのフォルダー選択で貼り付けてください。")

    def choose_review(self):
        """Let the user pick exactly one review snapshot before copying."""
        if self.role_dirty():
            messagebox.showinfo("担当予定が未保存です", "先に「担当予定を保存」を押してから開始指示をコピーしてください。", parent=self.window)
            return None
        try:
            snapshots = self.store.review_snapshots(self.selected)
        except (OSError, ValueError) as error:
            self.report_error(error)
            return None
        if not snapshots:
            implementer = ROLE_PLANS[self.roles["plan"]][0]
            messagebox.showinfo("レビュー用コピーがありません",
                                f"reviews にレビュー用コピー（ZIP）がありません。{implementer} に snapshot の作成を依頼してください。",
                                parent=self.window)
            return None
        case_id = self.selected
        dialog = tk.Toplevel(self.window)
        dialog.title("レビュー対象を選ぶ")
        dialog.geometry("560x220")
        dialog.grab_set()
        frame = ttk.Frame(dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="レビュー担当に渡すレビュー用コピー（新しい順）").pack(anchor="w", pady=(0, 8))
        labels = {f"{when:%Y-%m-%d %H:%M:%S}　{review_id}": review_id for review_id, when in snapshots}
        choice = tk.StringVar()
        box = ttk.Combobox(frame, textvariable=choice, values=list(labels), state="readonly", width=60)
        box.pack(fill="x")
        ttk.Label(frame, text="複数ある場合は、レビューしてほしい版を必ず選んでください（自動では選びません）。", style="Sub.TLabel", wraplength=500).pack(anchor="w", pady=(8, 8))

        def copy():
            review_id = labels.get(choice.get())
            if review_id is None:
                messagebox.showinfo("未選択", "レビューIDを選んでください。", parent=dialog)
                return
            if self.selected != case_id:
                dialog.destroy()
                return
            dialog.destroy()
            self.copy_start("reviewer", review_id)

        ttk.Button(frame, text="選んだレビューIDで開始指示をコピー", command=copy).pack(anchor="e")
        dialog.labels, dialog.choice, dialog.copy_selected = labels, choice, copy
        return dialog

    def copy_start(self, kind, review_id=None):
        try:
            if self.role_dirty():
                messagebox.showinfo("担当予定が未保存です", "先に「担当予定を保存」を押してから開始指示をコピーしてください。", parent=self.window)
                return
            latest = self.store.roles(self.selected)
            if latest["revision"] != self.roles["revision"]:
                self.load_roles(self.selected)
                self.update_work_controls()
                messagebox.showinfo("担当予定を更新しました", "担当を確認してから、もう一度開始指示をコピーしてください。", parent=self.window)
                return
            if latest["warning"]:
                raise ValueError("担当予定を確認して保存してから、開始指示をコピーしてください。")
            if kind == "reviewer" and review_id not in {rid for rid, _ in self.store.review_snapshots(self.selected)}:
                raise ValueError("選んだレビュー用コピーが見つかりません。もう一度選んでください。")
            text = start_instruction(kind, self.store.folder(self.selected), self.selected, self.roles["plan"], review_id)
            self.copy(text)
            implementer, reviewer = ROLE_PLANS[self.roles["plan"]]
            target = implementer if kind == "implementer" else reviewer
            self.notice.set(f"{target} 向けの開始指示をコピーしました。{target} の会話に貼り付けてください。送信はまだ行っていません。")
        except (OSError, ValueError) as error:
            self.report_error(error)

    def open_path(self, path):
        try:
            os.startfile(path)
        except PermissionError:
            self.copy(str(path))
            self.notice.set("この環境ではフォルダーを直接開けません。場所をコピーしました。エクスプローラーに貼り付けてください。")

    def open_folder(self):
        try:
            path = self.store.folder(self.selected)
            self.store.read(self.selected)
            self.open_path(path)
        except (OSError, ValueError) as error:
            self.report_error(error)

    def outputs_folder(self):
        self.store.read(self.selected)
        case = self.store.folder(self.selected)
        path = case / "outputs"
        self.store.inside(case, path)
        if not path.is_dir():
            raise ValueError("成果物フォルダー（outputs）がありません。案件フォルダーを確認してください。")
        return path

    def open_outputs(self):
        try:
            self.open_path(self.outputs_folder())
        except (OSError, ValueError) as error:
            self.report_error(error)

    def add_comment(self):
        try:
            self.store.feedback(self.selected, self.comment.get("1.0", "end"))
            self.comment.delete("1.0", "end")
            self.select()
            self.tabs.select(2)
            self.notice.set("コメントを保存しました。担当AIへの即時通知ではありません。反映状況は「進捗・成果物」で確認します。")
        except (OSError, ValueError) as error:
            self.report_error(error)


def main():
    root = tk.Tk()
    Hub(root)
    root.mainloop()


if __name__ == "__main__":
    main()
