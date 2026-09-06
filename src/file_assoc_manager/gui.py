"""tkinter 图形界面（中英双语，代码内文案为英文 key）。

薄封装：业务逻辑在 scanner/resolver/cleaner/backup/managed_progid，
本模块只负责展示与触发。视觉验证由用户实机进行。
"""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import i18n
from .backup import BackupManager, Operation
from .cleaner import remove_open_with_entry, remove_open_with_progid
from .i18n import LANGUAGES, get_language, set_language, t, translate_reason
from .managed_progid import ProgIdManager
from .models import Association, RegistryView, Status
from .registry import WinRegAdapter
from .resolver import resolve_all
from .scanner import scan

_STATUS_LABELS = {
    Status.VALID: "Valid",
    Status.INVALID: "Invalid",
    Status.UNKNOWN: "Unknown",
}

_VIEW_LABELS = {
    RegistryView.USER: "User level",
    RegistryView.SYSTEM_64: "System 64-bit",
    RegistryView.SYSTEM_32: "System 32-bit",
}

# 常见格式（选择器置顶展示）；分组名与标签名是 i18n key。
COMMON_FORMAT_GROUPS: dict[str, list[tuple[str, str]]] = {
    "Documents": [
        ("Word Document", ".docx"),
        ("Word 97-2003", ".doc"),
        ("PDF Document", ".pdf"),
        ("Plain Text", ".txt"),
        ("Markdown", ".md"),
        ("Excel Spreadsheet", ".xlsx"),
        ("PowerPoint Presentation", ".pptx"),
        ("CSV Table", ".csv"),
        ("RTF Document", ".rtf"),
    ],
    "Images": [
        ("JPEG Image", ".jpg"),
        ("PNG Image", ".png"),
        ("GIF Image", ".gif"),
        ("BMP Image", ".bmp"),
        ("SVG Vector", ".svg"),
        ("WebP Image", ".webp"),
        ("ICO Icon", ".ico"),
        ("TIFF Image", ".tif"),
    ],
    "Audio": [
        ("MP3 Audio", ".mp3"),
        ("WAV Audio", ".wav"),
        ("FLAC Lossless Audio", ".flac"),
        ("AAC Audio", ".aac"),
        ("M4A Audio", ".m4a"),
        ("OGG Audio", ".ogg"),
    ],
    "Video": [
        ("MP4 Video", ".mp4"),
        ("MKV Video", ".mkv"),
        ("AVI Video", ".avi"),
        ("MOV Video", ".mov"),
        ("WMV Video", ".wmv"),
        ("FLV Video", ".flv"),
        ("WebM Video", ".webm"),
    ],
    "Archives": [
        ("ZIP Archive", ".zip"),
        ("RAR Archive", ".rar"),
        ("7Z Archive", ".7z"),
        ("TAR Archive", ".tar"),
        ("GZ Archive", ".gz"),
    ],
    "Code & Web": [
        ("Python Script", ".py"),
        ("C Source File", ".c"),
        ("Java Source File", ".java"),
        ("JSON Data", ".json"),
        ("XML Document", ".xml"),
        ("HTML Page", ".html"),
        ("CSS Stylesheet", ".css"),
        ("JavaScript", ".js"),
        ("SQL Script", ".sql"),
    ],
}


def can_clean(record: Association) -> bool:
    """记录是否属于可清理的来源（FileExts 的 OpenWithList / OpenWithProgids）。"""
    return bool(
        ("\\OpenWithList" in record.source and record.command)
        or ("\\OpenWithProgids" in record.source and record.prog_id)
    )


def current_default_of(records: list[Association], extension: str) -> str | None:
    """查扩展名当前的默认程序显示名；无 UserChoice 记录返回 None。"""
    ext_lower = extension.lower()
    choice = next(
        (
            r
            for r in records
            if r.extension.lower() == ext_lower
            and "\\UserChoice" in r.source
            and r.prog_id
        ),
        None,
    )
    if choice is None:
        return None
    target = next(
        (r.target_path for r in records if r.prog_id == choice.prog_id and r.target_path),
        None,
    )
    return target or choice.prog_id


def build_all_extensions(records: list[Association]) -> list[str]:
    """扫描记录中全部扩展名去重（大小写不敏感），按字母排序。"""
    seen: set[str] = set()
    result: list[str] = []
    for record in records:
        lower = record.extension.lower()
        if lower not in seen:
            seen.add(lower)
            result.append(record.extension)
    return sorted(result, key=str.lower)


class FormatPickerDialog(tk.Toplevel):
    """格式选择弹窗：常见类型置顶 + 全部扩展名，支持搜索与当前默认提示。"""

    def __init__(self, master, records: list[Association]):
        super().__init__(master)
        self.title(t("Select file format"))
        self.geometry("520x560")
        self.transient(master)
        self.grab_set()
        self.result: str | None = None

        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(search_frame, text=t("Search:")).pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        self.tree = ttk.Treeview(self, columns=("label", "ext"), show="headings")
        self.tree.heading("label", text=t("Name"))
        self.tree.heading("ext", text=t("Extension"))
        self.tree.column("label", width=200)
        self.tree.column("ext", width=90)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        self.default_label = ttk.Label(self, text="", foreground="#8a6d1a")
        self.default_label.pack(fill="x", padx=8, pady=(0, 4))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text=t("OK"), command=self._ok).pack(side="right")
        ttk.Button(buttons, text=t("Cancel"), command=self.destroy).pack(
            side="right", padx=(0, 6)
        )

        # 行数据：iid -> 扩展名。常见类型置顶，全部扩展名去重兜底。
        self._ext_by_iid: dict[str, str] = {}
        common_exts = {
            ext.lower() for group in COMMON_FORMAT_GROUPS.values() for _, ext in group
        }
        for group in COMMON_FORMAT_GROUPS.values():
            for label, ext in group:
                iid = self.tree.insert("", "end", values=(f"{t(label)}  {ext}", ext))
                self._ext_by_iid[iid] = ext
        for ext in build_all_extensions(records):
            if ext.lower() in common_exts:
                continue
            iid = self.tree.insert("", "end", values=("", ext))
            self._ext_by_iid[iid] = ext
        self._shown = {iid: True for iid in self._ext_by_iid}

        self._records = records
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_default())
        self.tree.bind("<Double-1>", lambda _e: self._ok())

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        for iid, ext in self._ext_by_iid.items():
            label = self.tree.set(iid, "label")
            should_show = not query or query in label.lower() or query in ext.lower()
            if should_show and not self._shown[iid]:
                self.tree.reattach(iid, "", "end")
                self._shown[iid] = True
            elif not should_show and self._shown[iid]:
                self.tree.detach(iid)
                self._shown[iid] = False

    def _update_default(self):
        selection = self.tree.selection()
        if not selection:
            self.default_label.configure(text="")
            return
        ext = self._ext_by_iid[selection[0]]
        default = current_default_of(self._records, ext)
        if default is None:
            self.default_label.configure(
                text=t("{ext} current default: not set", ext=ext)
            )
        else:
            self.default_label.configure(
                text=t("{ext} current default: {program}", ext=ext, program=default)
            )

    def _ok(self):
        selection = self.tree.selection()
        if selection:
            self.result = self._ext_by_iid[selection[0]]
        self.destroy()


class FileAssocManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(t("File Association Manager"))
        self.geometry("1150x680")

        self.reg = WinRegAdapter()
        self.backup = BackupManager()
        self.config_path = self.backup.data_dir / "config.json"
        set_language(i18n.load_language(self.config_path))

        self.progid_mgr = ProgIdManager(self.reg, self.backup)
        self.records: list[Association] = []
        self._scan_thread: threading.Thread | None = None
        self._check_state: dict[ttk.Treeview, set[str]] = {}
        # 语言切换时需重设文案的控件与表头
        self._i18n_labels: list[tuple[ttk.Widget, str, dict]] = []
        self._trees: list[tuple[ttk.Treeview, tuple[str, ...]]] = []

        self._build_widgets()
        self._start_scan()

    # ---------- 界面骨架 ----------

    def _register_label(self, widget: ttk.Widget, key: str, **kwargs) -> None:
        widget.configure(text=t(key, **kwargs))
        self._i18n_labels.append((widget, key, kwargs))

    def _build_widgets(self):
        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=(6, 0))
        lang_label = ttk.Label(top)
        self._register_label(lang_label, "Language:")
        lang_label.pack(side="left")
        self.lang_box = ttk.Combobox(
            top,
            values=list(LANGUAGES.values()),
            state="readonly",
            width=8,
        )
        self.lang_box.set(LANGUAGES[get_language()])
        self.lang_box.pack(side="left", padx=(4, 0))
        self.lang_box.bind("<<ComboboxSelected>>", self._on_language_change)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=6, pady=6)
        self._tab_keys = ("Scan Results", "Backup & Restore", "My Associations")
        self.notebook.add(self._build_scan_page(self.notebook), text=t(self._tab_keys[0]))
        self.notebook.add(self._build_backup_page(self.notebook), text=t(self._tab_keys[1]))
        self.notebook.add(self._build_managed_page(self.notebook), text=t(self._tab_keys[2]))

    def _on_language_change(self, _event=None):
        display = self.lang_box.get()
        language = next(k for k, v in LANGUAGES.items() if v == display)
        set_language(language)
        i18n.save_language(self.config_path, language)
        self._apply_language()

    def _apply_language(self):
        self.title(t("File Association Manager"))
        for index, key in enumerate(self._tab_keys):
            self.notebook.tab(index, text=t(key))
        for widget, key, kwargs in self._i18n_labels:
            widget.configure(text=t(key, **kwargs))
        for tree, header_keys in self._trees:
            columns = tree["columns"][1:]  # 跳过勾选列
            for col, key in zip(columns, header_keys):
                tree.heading(col, text=t(key))
        # 筛选下拉的选项与当前值
        self.filter_box.configure(
            values=(t("All"), t("Invalid"), t("Unknown"), t("Valid"))
        )
        self.filter_var.set(t("All"))
        self._populate_scan()
        self._populate_backup()
        self._populate_managed()
        self.lang_box.set(LANGUAGES[get_language()])
        if self.records:
            self.scan_status.configure(
                text=t("{count} records", count=len(self.records))
            )

    def _build_scan_page(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)

        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 4))
        label = ttk.Label(toolbar)
        self._register_label(label, "Filter:")
        label.pack(side="left")
        self.filter_var = tk.StringVar(value=t("All"))
        self.filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=(t("All"), t("Invalid"), t("Unknown"), t("Valid")),
            state="readonly",
            width=12,
        )
        self.filter_box.pack(side="left", padx=(0, 8))
        self.filter_box.bind("<<ComboboxSelected>>", lambda _e: self._populate_scan())
        refresh = ttk.Button(toolbar, command=self._start_scan)
        self._register_label(refresh, "Rescan")
        refresh.pack(side="left")
        self.scan_status = ttk.Label(toolbar, text="")
        self.scan_status.pack(side="left", padx=10)

        columns = ("extension", "view", "status", "prog_id", "target", "reason")
        header_keys = ("Extension", "Source", "Status", "ProgID", "Program Path", "Note")
        self.scan_tree = self._make_tree(page, columns, header_keys, (80, 80, 70, 220, 280, 300))

        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(4, 0))
        select_all = ttk.Button(bottom, command=lambda: self._check_all(self.scan_tree))
        self._register_label(select_all, "Select All")
        select_all.pack(side="left")
        clear = ttk.Button(bottom, command=lambda: self._clear_checks(self.scan_tree))
        self._register_label(clear, "Clear")
        clear.pack(side="left", padx=(4, 12))
        clean = ttk.Button(bottom, command=self._clean_selected)
        self._register_label(clean, "Clean checked items")
        clean.pack(side="left")
        hint = ttk.Label(bottom)
        self._register_label(
            hint,
            "Only 'Open With' leftovers can be cleaned; system definitions "
            "and UserChoice are read-only.",
        )
        hint.pack(side="left", padx=10)
        return page

    def _build_backup_page(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 4))
        select_all = ttk.Button(toolbar, command=lambda: self._check_all(self.backup_tree))
        self._register_label(select_all, "Select All")
        select_all.pack(side="left")
        clear = ttk.Button(toolbar, command=lambda: self._clear_checks(self.backup_tree))
        self._register_label(clear, "Clear")
        clear.pack(side="left", padx=(4, 12))
        restore = ttk.Button(toolbar, command=self._restore_selected)
        self._register_label(restore, "Restore checked items")
        restore.pack(side="left")
        hint = ttk.Label(toolbar)
        self._register_label(hint, "Operation log: {path}", path=str(self.backup.log_path))
        hint.pack(side="left", padx=10)

        columns = ("timestamp", "extension", "key_path", "value_name", "value_data")
        header_keys = ("Time", "Extension", "Key Path", "Value Name", "Value Data")
        self.backup_tree = self._make_tree(page, columns, header_keys, (180, 90, 330, 90, 260))
        self._populate_backup()
        return page

    def _build_managed_page(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)
        form = ttk.Frame(page)
        form.pack(fill="x", pady=(0, 6))
        ext_label = ttk.Label(form)
        self._register_label(ext_label, "Extension:")
        ext_label.pack(side="left")
        self.ext_entry = ttk.Entry(form, width=12)
        self.ext_entry.pack(side="left", padx=(0, 4))
        pick = ttk.Button(form, command=self._pick_format)
        self._register_label(pick, "Pick format...")
        pick.pack(side="left", padx=(0, 8))
        path_label = ttk.Label(form)
        self._register_label(path_label, "Program path:")
        path_label.pack(side="left")
        self.path_entry = ttk.Entry(form, width=50)
        self.path_entry.pack(side="left", padx=(0, 4))
        browse = ttk.Button(form, command=self._browse_program)
        self._register_label(browse, "Browse...")
        browse.pack(side="left", padx=(0, 8))
        register = ttk.Button(form, command=self._register_association)
        self._register_label(register, "Register association")
        register.pack(side="left")

        columns = ("prog_id", "extension", "program_path", "previous_default")
        header_keys = ("ProgID", "Extension", "Program Path", "Previous default")
        self.managed_tree = self._make_tree(page, columns, header_keys, (160, 90, 320, 160))
        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(4, 0))
        select_all = ttk.Button(bottom, command=lambda: self._check_all(self.managed_tree))
        self._register_label(select_all, "Select All")
        select_all.pack(side="left")
        clear = ttk.Button(bottom, command=lambda: self._clear_checks(self.managed_tree))
        self._register_label(clear, "Clear")
        clear.pack(side="left", padx=(4, 12))
        unregister = ttk.Button(bottom, command=self._unregister_selected)
        self._register_label(unregister, "Unregister checked")
        unregister.pack(side="left")
        hint = ttk.Label(bottom)
        self._register_label(
            hint,
            "Undo restores the previous default and removes the tool-created ProgID.",
        )
        hint.pack(side="left", padx=10)
        self._populate_managed()
        return page

    def _make_tree(
        self, parent, columns, header_keys, column_widths
    ) -> ttk.Treeview:
        """带勾选列的表格；勾选状态由 self._check_state 管理。"""
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        full_columns = ("_check",) + tuple(columns)
        tree = ttk.Treeview(frame, columns=full_columns, show="headings")
        tree.heading("_check", text="☑")
        tree.column("_check", width=34, anchor="center", stretch=False)
        for col, key, width in zip(columns, header_keys, column_widths):
            tree.heading(col, text=t(key))
            tree.column(col, width=width)
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._check_state[tree] = set()
        self._trees.append((tree, header_keys))
        tree.bind("<Button-1>", self._on_tree_click)
        return tree

    # ---------- 勾选交互 ----------

    def _on_tree_click(self, event):
        tree = event.widget
        if tree not in self._check_state or tree.identify_column(event.x) != "#1":
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        checked = self._check_state[tree]
        if iid in checked:
            checked.discard(iid)
        else:
            checked.add(iid)
        self._refresh_checks(tree)

    def _refresh_checks(self, tree):
        checked = self._check_state[tree]
        for iid in tree.get_children():
            tree.set(iid, "_check", "☑" if iid in checked else "☐")

    def _check_all(self, tree):
        self._check_state[tree].update(tree.get_children())
        self._refresh_checks(tree)

    def _clear_checks(self, tree):
        self._check_state[tree].clear()
        self._refresh_checks(tree)

    # ---------- 扫描页 ----------

    def _start_scan(self):
        if self._scan_thread and self._scan_thread.is_alive():
            return
        self.scan_status.configure(text=t("Scanning..."))
        self._scan_result: tuple | None = None
        self._scan_thread = threading.Thread(target=self._scan_worker, daemon=True)
        self._scan_thread.start()
        self.after(100, self._poll_scan)

    def _scan_worker(self):
        """后台线程：只写结果，所有 UI 更新由主线程轮询完成。"""
        try:
            records = scan(self.reg)
            resolve_all(records, self.reg)
            self._scan_result = ("ok", records)
        except Exception as exc:  # 注册表读取异常兜底，保证 UI 不崩
            self._scan_result = ("error", exc)

    def _poll_scan(self):
        if self._scan_result is None:
            self.after(100, self._poll_scan)
            return
        status, payload = self._scan_result
        if status == "ok":
            self._scan_done(payload)
        else:
            self._scan_failed(payload)

    def _scan_done(self, records):
        self.records = records
        self._check_state[self.scan_tree].clear()  # 数据变了，旧勾选失效
        self.scan_status.configure(text=t("{count} records", count=len(records)))
        self._populate_scan()

    def _scan_failed(self, exc):
        self.scan_status.configure(text=t("Scan failed"))
        messagebox.showerror(t("Scan failed"), str(exc))

    def _populate_scan(self):
        self.scan_tree.delete(*self.scan_tree.get_children())
        selected = self.filter_var.get()
        labels = (
            (t("All"), None),
            (t("Invalid"), Status.INVALID),
            (t("Unknown"), Status.UNKNOWN),
            (t("Valid"), Status.VALID),
        )
        want_status = next((s for label, s in labels if label == selected), None)
        for index, record in enumerate(self.records):
            if want_status is not None and record.status != want_status:
                continue
            self.scan_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "",
                    record.extension,
                    t(_VIEW_LABELS[record.view]),
                    t(_STATUS_LABELS[record.status]),
                    record.prog_id or "",
                    record.target_path or "",
                    translate_reason(record.reason or ""),
                ),
            )
        self._refresh_checks(self.scan_tree)

    def _clean_record(self, record: Association) -> Operation | None:
        """按记录来源分派到对应清理动作；不可清理的来源返回 None。"""
        if "\\OpenWithList" in record.source and record.command:
            return remove_open_with_entry(
                self.reg, self.backup, record.extension, record.command
            )
        if "\\OpenWithProgids" in record.source and record.prog_id:
            return remove_open_with_progid(
                self.reg, self.backup, record.extension, record.prog_id
            )
        return None

    def _clean_selected(self):
        checked_ids = self._check_state[self.scan_tree]
        if not checked_ids:
            messagebox.showinfo(t("Please check the items to clean first."), "")
            return
        targets = [self.records[int(i)] for i in checked_ids]
        cleanable = [r for r in targets if can_clean(r)]
        skipped = len(targets) - len(cleanable)
        if not cleanable:
            messagebox.showinfo(
                t("None of the checked items can be cleaned (only 'Open With' leftovers)."),
                "",
            )
            return
        if not messagebox.askyesno(
            t("Confirm Cleanup"),
            t(
                "Will clean {clean} item(s), skip {skip} item(s) that cannot be "
                "cleaned.\nEach item is backed up before removal and can be "
                "restored anytime.\n\nProceed?",
                clean=len(cleanable),
                skip=skipped,
            ),
            parent=self,
        ):
            return
        failed = []
        for record in cleanable:
            try:
                self._clean_record(record)
            except Exception as exc:
                failed.append(f"{record.extension}: {exc}")
        if failed:
            messagebox.showerror(
                t("Cleanup partially failed"), "\n".join(failed[:5]), parent=self
            )
        else:
            messagebox.showinfo(
                t("Cleanup complete"), t("Cleaned {count} item(s).", count=len(cleanable))
            )
        self._populate_backup()
        self._start_scan()

    # ---------- 备份恢复页 ----------

    def _populate_backup(self):
        self.backup_tree.delete(*self.backup_tree.get_children())
        for index, operation in enumerate(self.backup.list_operations()):
            self.backup_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "",
                    operation.timestamp,
                    operation.extension,
                    operation.key_path,
                    operation.value_name or t("(default value)"),
                    operation.value_data,
                ),
            )
        self._refresh_checks(self.backup_tree)

    def _restore_selected(self):
        operations = self.backup.list_operations()
        checked_ids = self._check_state[self.backup_tree]
        if not checked_ids:
            messagebox.showinfo(t("Please check the operation records to restore first."), "")
            return
        selected = [operations[int(i)] for i in checked_ids]
        if not messagebox.askyesno(
            t("Confirm Restore"),
            t(
                "Will restore {count} operation record(s) (writing values back).\n\n"
                "Proceed?",
                count=len(selected),
            ),
            parent=self,
        ):
            return
        for operation in selected:
            try:
                self.backup.restore(self.reg, operation)
            except Exception as exc:
                messagebox.showerror(
                    t("Restore failed"), f"{operation.key_path}: {exc}", parent=self
                )
                return
        messagebox.showinfo(
            t("Restore complete"), t("Restored {count} item(s).", count=len(selected))
        )
        self._start_scan()

    # ---------- 我的关联页 ----------

    def _pick_format(self):
        dialog = FormatPickerDialog(self, self.records)
        self.wait_window(dialog)
        if dialog.result:
            self.ext_entry.delete(0, "end")
            self.ext_entry.insert(0, dialog.result)

    def _browse_program(self):
        path = filedialog.askopenfilename(
            title=t("Select program"),
            filetypes=[(t("Executables"), "*.exe"), (t("All files"), "*.*")],
        )
        if path:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, path)

    def _register_association(self):
        extension = self.ext_entry.get().strip()
        program_path = self.path_entry.get().strip()
        if not extension or not program_path:
            messagebox.showinfo(
                t(
                    "Please fill in the extension and program path "
                    "(or use 'Pick format...')."
                ),
                "",
            )
            return
        try:
            self.progid_mgr.register(extension, program_path)
        except Exception as exc:
            messagebox.showerror(t("Register failed"), str(exc), parent=self)
            return
        self.ext_entry.delete(0, "end")
        self.path_entry.delete(0, "end")
        self._populate_managed()
        self._start_scan()

    def _populate_managed(self):
        self.managed_tree.delete(*self.managed_tree.get_children())
        for index, managed in enumerate(self.progid_mgr.list_managed()):
            self.managed_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "",
                    managed.prog_id,
                    managed.extension,
                    managed.program_path,
                    managed.previous_default or t("(none)"),
                ),
            )
        self._refresh_checks(self.managed_tree)

    def _unregister_selected(self):
        managed = self.progid_mgr.list_managed()
        checked_ids = self._check_state[self.managed_tree]
        if not checked_ids:
            messagebox.showinfo(t("Please check the associations to unregister first."), "")
            return
        selected = [managed[int(i)] for i in checked_ids]
        if not messagebox.askyesno(
            t("Confirm Unregister"),
            t(
                "Will unregister {count} association(s) (restoring previous "
                "defaults).\n\nProceed?",
                count=len(selected),
            ),
            parent=self,
        ):
            return
        for entry in selected:
            try:
                self.progid_mgr.unregister(entry.prog_id)
            except Exception as exc:
                messagebox.showerror(
                    t("Unregister failed"), f"{entry.prog_id}: {exc}", parent=self
                )
                return
        messagebox.showinfo(
            t("Unregister complete"),
            t("Unregistered {count} association(s).", count=len(selected)),
        )
        self._populate_managed()
        self._start_scan()


def main():
    FileAssocManagerApp().mainloop()


if __name__ == "__main__":
    main()
