"""只读扫描器。

扫描三处关联来源：
1. HKCU 的 FileExts（用户打开方式、UserChoice、历史残留）
2. HKCU\\Software\\Classes（用户级扩展名与 ProgID 定义）
3. HKCR 的 64 位与 32 位视图（系统级定义，WOW64 双视图各自扫描）

扫描结果按 (extension, source, view) 为粒度产出，不合并去重——
同一条打开方式的「用户历史」与「当前定义」是不同来源，必须分别展示。
"""

from .models import Association, RegistryView, Status
from .registry import RegistryAdapter, ViewKey

_VIEW_MAP: dict[ViewKey, RegistryView] = {
    ViewKey.USER_FILE_EXTS: RegistryView.USER,
    ViewKey.USER_CLASSES: RegistryView.USER,
    ViewKey.SYSTEM_CLASSES_64: RegistryView.SYSTEM_64,
    ViewKey.SYSTEM_CLASSES_32: RegistryView.SYSTEM_32,
}

_SOURCE_PREFIX: dict[ViewKey, str] = {
    ViewKey.USER_FILE_EXTS: (
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
    ),
    ViewKey.USER_CLASSES: r"HKCU\Software\Classes",
    ViewKey.SYSTEM_CLASSES_64: "HKCR",
    ViewKey.SYSTEM_CLASSES_32: "HKCR",
}


def scan(reg: RegistryAdapter) -> list[Association]:
    """扫描全部关联来源，返回未解析状态的记录列表。"""
    records: list[Association] = []
    records.extend(_scan_file_exts(reg))
    for view in (
        ViewKey.USER_CLASSES,
        ViewKey.SYSTEM_CLASSES_64,
        ViewKey.SYSTEM_CLASSES_32,
    ):
        records.extend(_scan_classes(reg, view))
    return records


def _scan_file_exts(reg: RegistryAdapter) -> list[Association]:
    records = []
    view = ViewKey.USER_FILE_EXTS
    prefix = _SOURCE_PREFIX[view]
    for ext in reg.list_subkeys(view, ""):
        source = f"{prefix}\\{ext}"

        user_choice = reg.read_values(view, f"{ext}\\UserChoice")
        if "ProgId" in user_choice:
            records.append(
                Association(
                    extension=ext,
                    source=f"{source}\\UserChoice",
                    view=_VIEW_MAP[view],
                    prog_id=user_choice["ProgId"],
                    command=None,
                    target_path=None,
                    status=Status.UNKNOWN,
                )
            )

        # OpenWithList 的值名是字母索引，值是程序名（裸文件名或路径）。
        # MRUList 存的是顺序索引串，不是程序名，跳过。
        open_with = reg.read_values(view, f"{ext}\\OpenWithList")
        for name, value in open_with.items():
            if name != "MRUList" and value:
                records.append(
                    Association(
                        extension=ext,
                        source=f"{source}\\OpenWithList",
                        view=_VIEW_MAP[view],
                        prog_id=None,
                        command=value,
                        target_path=None,
                        status=Status.UNKNOWN,
                    )
                )

        # OpenWithProgids 的值名是 ProgID，值通常为空。
        open_with_progids = reg.read_values(view, f"{ext}\\OpenWithProgids")
        for prog_id in open_with_progids:
            records.append(
                Association(
                    extension=ext,
                    source=f"{source}\\OpenWithProgids",
                    view=_VIEW_MAP[view],
                    prog_id=prog_id,
                    command=None,
                    target_path=None,
                    status=Status.UNKNOWN,
                )
            )
    return records


def _scan_classes(reg: RegistryAdapter, view: ViewKey) -> list[Association]:
    records = []
    prefix = _SOURCE_PREFIX[view]
    for subkey in reg.list_subkeys(view, ""):
        if not subkey.startswith("."):
            continue
        records.append(
            Association(
                extension=subkey,
                source=f"{prefix}\\{subkey}",
                view=_VIEW_MAP[view],
                prog_id=reg.read_default(view, subkey),
                command=None,
                target_path=None,
                status=Status.UNKNOWN,
            )
        )
    return records
