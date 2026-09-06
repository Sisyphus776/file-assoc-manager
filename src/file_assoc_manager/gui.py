"""tkinter 图形界面。

薄封装：业务逻辑在 scanner/resolver/cleaner/backup/managed_progid，
本模块只负责展示与触发。视觉验证由用户实机进行。

三个页面均支持勾选框列（点击 ☑/☐ 切换）与批量操作确认。
"""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .backup import BackupManager, Operation
from .cleaner import remove_open_with_entry, remove_open_with_progid
from .managed_progid import ProgIdManager
from .models import Association, RegistryView, Status
from .registry import WinRegAdapter
from .resolver import resolve_all
from .scanner import scan

_STATUS_LABELS = {
    Status.VALID: "有效",
    Status.INVALID: "失效",
    Status.UNKNOWN: "无法判断",
}

_VIEW_LABELS = {
    RegistryView.USER: "用户级",
    RegistryView.SYSTEM_64: "系统64位",
    RegistryView.SYSTEM_32: "系统32位",
}

# 常见格式（置顶展示，带中文说明）；硬编码维护。
COMMON_FORMAT_GROUPS: dict[str, list[tuple[str, str]]] = {
    "文档": [
        ("Word 文档", ".docx"),
        ("Word 97-2003", ".doc"),
        ("PDF 文档", ".pdf"),
        ("纯文本", ".txt"),
        ("Markdown", ".md"),
        ("Excel 表格", ".xlsx"),
        ("PowerPoint 演示", ".pptx"),
        ("CSV 表格", ".csv"),
        ("RTF 文档", ".rtf"),
    ],
    "图片": [
        ("JPEG 图片", ".jpg"),
        ("PNG 图片", ".png"),
        ("GIF 图片", ".gif"),
        ("BMP 图片", ".bmp"),
        ("SVG 矢量图", ".svg"),
        ("WebP 图片", ".webp"),
        ("ICO 图标", ".ico"),
        ("TIFF 图片", ".tif"),
    ],
    "音频": [
        ("MP3 音频", ".mp3"),
        ("WAV 音频", ".wav"),
        ("FLAC 无损音频", ".flac"),
        ("AAC 音频", ".aac"),
        ("M4A 音频", ".m4a"),
        ("OGG 音频", ".ogg"),
    ],
    "视频": [
        ("MP4 视频", ".mp4"),
        ("MKV 视频", ".mkv"),
        ("AVI 视频", ".avi"),
        ("MOV 视频", ".mov"),
        ("WMV 视频", ".wmv"),
        ("FLV 视频", ".flv"),
        ("WebM 视频", ".webm"),
    ],
    "压缩": [
        ("ZIP 压缩包", ".zip"),
        ("RAR 压缩包", ".rar"),
        ("7Z 压缩包", ".7z"),
        ("TAR 归档", ".tar"),
        ("GZ 压缩", ".gz"),
    ],
    "代码与网页": [
        ("Python 脚本", ".py"),
        ("C 源文件", ".c"),
        ("Java 源文件", ".java"),
        ("JSON 数据", ".json"),
        ("XML 文档", ".xml"),
        ("HTML 网页", ".html"),
        ("CSS 样式", ".css"),
        ("JavaScript", ".js"),
        ("SQL 脚本", ".sql"),
    ],
}


def can_clean(record: Association) -> bool:
    """记录是否属于可清理的来源（FileExts 的 OpenWithList / OpenWithProgids）。"""
    return bool(
        ("\\OpenWithList" in record.source and record.command)
        or ("\\OpenWithProgids" in record.source and record.prog_id)
    )


def current_default_of(
    records: list[Association], extension: str
) -> str | None:
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
        self.title("选择文件格式")
        self.geometry("520x560")
        self.transient(master)
        self.grab_set()
        self.result: str | None = None

        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(8, 4))
        ttk.Label(search_frame, text="搜索:").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ttk.Entry(search_frame, textvariable=self.search_var).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        self.tree = ttk.Treeview(self, columns=("label", "ext"), show="headings")
        self.tree.heading("label", text="名称")
        self.tree.heading("ext", text="扩展名")
        self.tree.column("label", width=200)
        self.tree.column("ext", width=90)
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)

        self.default_label = ttk.Label(self, text="", foreground="#8a6d1a")
        self.default_label.pack(fill="x", padx=8, pady=(0, 4))

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="确定", command=self._ok).pack(side="right")
        ttk.Button(buttons, text="取消", command=self.destroy).pack(
            side="right", padx=(0, 6)
        )

        # 行数据：iid -> 扩展名。常见类型置顶，全部扩展名去重兜底。
        self._ext_by_iid: dict[str, str] = {}
        common_exts = {
            ext.lower() for group in COMMON_FORMAT_GROUPS.values() for _, ext in group
        }
        for group in COMMON_FORMAT_GROUPS.values():
            for label, ext in group:
                iid = self.tree.insert("", "end", values=(label, ext))
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
            should_show = (
                not query or query in label.lower() or query in ext.lower()
            )
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
            self.default_label.configure(text=f"{ext} 当前默认：未设置")
        else:
            self.default_label.configure(text=f"{ext} 当前默认：{default}")

    def _ok(self):
        selection = self.tree.selection()
        if selection:
            self.result = self._ext_by_iid[selection[0]]
        self.destroy()


class FileAssocManagerApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("文件关联管家")
        self.geometry("1150x680")

        self.reg = WinRegAdapter()
        self.backup = BackupManager()
        self.progid_mgr = ProgIdManager(self.reg, self.backup)
        self.records: list[Association] = []
        self._scan_thread: threading.Thread | None = None
        self._check_state: dict[ttk.Treeview, set[str]] = {}

        self._build_widgets()
        self._start_scan()

    # ---------- 界面骨架 ----------

    def _build_widgets(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)
        notebook.add(self._build_scan_page(notebook), text="扫描结果")
        notebook.add(self._build_backup_page(notebook), text="备份与恢复")
        notebook.add(self._build_managed_page(notebook), text="我的关联")

    def _build_scan_page(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)

        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Label(toolbar, text="筛选:").pack(side="left")
        self.filter_var = tk.StringVar(value="全部")
        filter_box = ttk.Combobox(
            toolbar,
            textvariable=self.filter_var,
            values=("全部", "失效", "无法判断", "有效"),
            state="readonly",
            width=10,
        )
        filter_box.pack(side="left", padx=(0, 8))
        filter_box.bind("<<ComboboxSelected>>", lambda _e: self._populate_scan())
        self.refresh_button = ttk.Button(
            toolbar, text="重新扫描", command=self._start_scan
        )
        self.refresh_button.pack(side="left")
        self.scan_status = ttk.Label(toolbar, text="")
        self.scan_status.pack(side="left", padx=10)

        columns = ("extension", "view", "status", "prog_id", "target", "reason")
        headers = ("扩展名", "来源", "状态", "ProgID", "程序路径", "说明")
        self.scan_tree = self._make_tree(
            page, columns, headers, column_widths=(80, 80, 70, 220, 280, 300)
        )

        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(4, 0))
        ttk.Button(bottom, text="全选", command=lambda: self._check_all(self.scan_tree)).pack(
            side="left"
        )
        ttk.Button(bottom, text="清空", command=lambda: self._clear_checks(self.scan_tree)).pack(
            side="left", padx=(4, 12)
        )
        self.clean_button = ttk.Button(
            bottom, text="清理勾选条目", command=self._clean_selected
        )
        self.clean_button.pack(side="left")
        ttk.Label(
            bottom,
            text="仅「打开方式残留」类条目可清理；系统定义与 UserChoice 只读展示",
        ).pack(side="left", padx=10)
        return page

    def _build_backup_page(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)
        toolbar = ttk.Frame(page)
        toolbar.pack(fill="x", pady=(0, 4))
        ttk.Button(toolbar, text="全选", command=lambda: self._check_all(self.backup_tree)).pack(
            side="left"
        )
        ttk.Button(toolbar, text="清空", command=lambda: self._clear_checks(self.backup_tree)).pack(
            side="left", padx=(4, 12)
        )
        self.restore_button = ttk.Button(
            toolbar, text="恢复勾选条目", command=self._restore_selected
        )
        self.restore_button.pack(side="left")
        ttk.Label(
            toolbar, text="操作记录来自 %s" % self.backup.log_path
        ).pack(side="left", padx=10)

        columns = ("timestamp", "extension", "key_path", "value_name", "value_data")
        headers = ("时间", "扩展名", "键路径", "值名", "值内容")
        self.backup_tree = self._make_tree(
            page, columns, headers, column_widths=(180, 90, 330, 90, 260)
        )
        self._populate_backup()
        return page

    def _build_managed_page(self, parent) -> ttk.Frame:
        page = ttk.Frame(parent)
        form = ttk.Frame(page)
        form.pack(fill="x", pady=(0, 6))
        ttk.Label(form, text="扩展名:").pack(side="left")
        self.ext_entry = ttk.Entry(form, width=12)
        self.ext_entry.pack(side="left", padx=(0, 4))
        ttk.Button(form, text="选择格式...", command=self._pick_format).pack(
            side="left", padx=(0, 8)
        )
        ttk.Label(form, text="程序路径:").pack(side="left")
        self.path_entry = ttk.Entry(form, width=50)
        self.path_entry.pack(side="left", padx=(0, 4))
        ttk.Button(form, text="浏览...", command=self._browse_program).pack(
            side="left", padx=(0, 8)
        )
        self.register_button = ttk.Button(
            form, text="注册关联", command=self._register_association
        )
        self.register_button.pack(side="left")

        columns = ("prog_id", "extension", "program_path", "previous_default")
        headers = ("ProgID", "扩展名", "程序路径", "注册前默认值")
        self.managed_tree = self._make_tree(
            page, columns, headers, column_widths=(160, 90, 320, 160)
        )
        bottom = ttk.Frame(page)
        bottom.pack(fill="x", pady=(4, 0))
        ttk.Button(bottom, text="全选", command=lambda: self._check_all(self.managed_tree)).pack(
            side="left"
        )
        ttk.Button(bottom, text="清空", command=lambda: self._clear_checks(self.managed_tree)).pack(
            side="left", padx=(4, 12)
        )
        self.unregister_button = ttk.Button(
            bottom, text="撤销勾选关联", command=self._unregister_selected
        )
        self.unregister_button.pack(side="left")
        ttk.Label(
            bottom, text="撤销会恢复注册前的默认值并删除本工具创建的 ProgID"
        ).pack(side="left", padx=10)
        self._populate_managed()
        return page

    def _make_tree(
        self, parent, columns, headers, column_widths
    ) -> ttk.Treeview:
        """带勾选列的表格；勾选状态由 self._check_state 管理。"""
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        full_columns = ("_check",) + tuple(columns)
        tree = ttk.Treeview(frame, columns=full_columns, show="headings")
        tree.heading("_check", text="☑")
        tree.column("_check", width=34, anchor="center", stretch=False)
        for col, header, width in zip(columns, headers, column_widths):
            tree.heading(col, text=header)
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
        self.refresh_button.configure(state="disabled")
        self.scan_status.configure(text="扫描中...")
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
        self.refresh_button.configure(state="normal")
        self.scan_status.configure(text="共 %d 条记录" % len(records))
        self._populate_scan()

    def _scan_failed(self, exc):
        self.refresh_button.configure(state="normal")
        self.scan_status.configure(text="扫描失败")
        messagebox.showerror("扫描失败", str(exc))

    def _populate_scan(self):
        self.scan_tree.delete(*self.scan_tree.get_children())
        selected = self.filter_var.get()
        for index, record in enumerate(self.records):
            if selected == "失效" and record.status != Status.INVALID:
                continue
            if selected == "无法判断" and record.status != Status.UNKNOWN:
                continue
            if selected == "有效" and record.status != Status.VALID:
                continue
            self.scan_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    "",
                    record.extension,
                    _VIEW_LABELS[record.view],
                    _STATUS_LABELS[record.status],
                    record.prog_id or "",
                    record.target_path or "",
                    record.reason or "",
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
            messagebox.showinfo("提示", "请先勾选要清理的条目")
            return
        targets = [self.records[int(i)] for i in checked_ids]
        cleanable = [r for r in targets if can_clean(r)]
        skipped = len(targets) - len(cleanable)
        if not cleanable:
            messagebox.showinfo(
                "提示", "勾选的条目都不属于可清理的来源（仅「打开方式残留」可清理）"
            )
            return
        if not messagebox.askyesno(
            "确认清理",
            f"将清理 {len(cleanable)} 条，跳过 {skipped} 条（不可清理的来源）。\n"
            "每条清理前自动备份，可随时恢复。\n\n确认执行？",
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
                "部分清理失败", "\n".join(failed[:5]), parent=self
            )
        else:
            messagebox.showinfo("清理完成", f"已清理 {len(cleanable)} 条")
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
                    operation.value_name or "(默认值)",
                    operation.value_data,
                ),
            )
        self._refresh_checks(self.backup_tree)

    def _restore_selected(self):
        operations = self.backup.list_operations()
        checked_ids = self._check_state[self.backup_tree]
        if not checked_ids:
            messagebox.showinfo("提示", "请先勾选要恢复的操作记录")
            return
        selected = [operations[int(i)] for i in checked_ids]
        if not messagebox.askyesno(
            "确认恢复",
            f"将恢复 {len(selected)} 条操作记录（把值写回原位置）。\n\n确认执行？",
            parent=self,
        ):
            return
        for operation in selected:
            try:
                self.backup.restore(self.reg, operation)
            except Exception as exc:
                messagebox.showerror(
                    "恢复失败", f"{operation.key_path}: {exc}", parent=self
                )
                return
        messagebox.showinfo("恢复完成", f"已恢复 {len(selected)} 条")
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
            title="选择程序", filetypes=[("可执行程序", "*.exe"), ("所有文件", "*.*")]
        )
        if path:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, path)

    def _register_association(self):
        extension = self.ext_entry.get().strip()
        program_path = self.path_entry.get().strip()
        if not extension or not program_path:
            messagebox.showinfo("提示", "请填写扩展名和程序路径（可点「选择格式...」）")
            return
        try:
            self.progid_mgr.register(extension, program_path)
        except Exception as exc:
            messagebox.showerror("注册失败", str(exc), parent=self)
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
                    managed.previous_default or "(无)",
                ),
            )
        self._refresh_checks(self.managed_tree)

    def _unregister_selected(self):
        managed = self.progid_mgr.list_managed()
        checked_ids = self._check_state[self.managed_tree]
        if not checked_ids:
            messagebox.showinfo("提示", "请先勾选要撤销的关联")
            return
        selected = [managed[int(i)] for i in checked_ids]
        if not messagebox.askyesno(
            "确认撤销",
            f"将撤销 {len(selected)} 条关联（恢复注册前的默认值）。\n\n确认执行？",
            parent=self,
        ):
            return
        for entry in selected:
            try:
                self.progid_mgr.unregister(entry.prog_id)
            except Exception as exc:
                messagebox.showerror(
                    "撤销失败", f"{entry.prog_id}: {exc}", parent=self
                )
                return
        messagebox.showinfo("撤销完成", f"已撤销 {len(selected)} 条关联")
        self._populate_managed()
        self._start_scan()


def main():
    FileAssocManagerApp().mainloop()


if __name__ == "__main__":
    main()
