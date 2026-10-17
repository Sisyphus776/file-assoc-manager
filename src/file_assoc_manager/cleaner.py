"""选择性清理：删除打开方式残留与用户级失效关联定义。

流程固定为「备份 -> 删除」（docs/design.md 第 4 节）：
record_removal 成功后才执行删除，未找到目标条目时不做任何操作。
只删除单个值，不删除整个键，更不碰 ProgID 键树。
"""

from .backup import BackupManager, Operation
from .models import Association, RegistryView, Status
from .registry import RegistryAdapter, ViewKey


def remove_open_with_entry(
    reg: RegistryAdapter,
    backup: BackupManager,
    extension: str,
    program_name: str,
) -> Operation | None:
    """删除 FileExts\\.ext\\OpenWithList 中值内容为 program_name 的条目。

    值名是字母索引（a/b/c），必须按值内容定位；MRUList 是顺序索引串，
    跳过。删除后同步从 MRUList 中移除该字母，避免悬挂引用。
    未找到时返回 None。
    """
    view = ViewKey.USER_FILE_EXTS
    path = f"{extension}\\OpenWithList"
    typed_values = reg.read_values_typed(view, path)
    for value_name, (value_data, value_type) in typed_values.items():
        if value_name == "MRUList":
            continue
        if value_data == program_name:
            operation = backup.record_removal(
                view, path, value_name, value_data, extension, value_type
            )
            reg.delete_value(view, path, value_name)
            _sync_mru_list(reg, backup, path, value_name, extension)
            return operation
    return None


def _sync_mru_list(
    reg: RegistryAdapter,
    backup: BackupManager,
    path: str,
    removed_letter: str,
    extension: str,
) -> None:
    """删除 OpenWithList 条目后，把被删字母从 MRUList 顺序串中剔除。"""
    view = ViewKey.USER_FILE_EXTS
    typed = reg.read_values_typed(view, path)
    entry = typed.get("MRUList")
    if entry is None:
        return
    mru_old, mru_type = entry
    mru_new = mru_old.replace(removed_letter, "")
    if mru_new == mru_old:
        return
    backup.record_removal(view, path, "MRUList", mru_old, extension, mru_type)
    reg.set_value(view, path, "MRUList", mru_new, value_type=mru_type)


def remove_open_with_progid(
    reg: RegistryAdapter,
    backup: BackupManager,
    extension: str,
    prog_id: str,
) -> Operation | None:
    """删除 FileExts\\.ext\\OpenWithProgids 中指定 ProgID 的条目。

    OpenWithProgids 的值名就是 ProgID。未找到时返回 None。
    """
    view = ViewKey.USER_FILE_EXTS
    path = f"{extension}\\OpenWithProgids"
    typed_values = reg.read_values_typed(view, path)
    if prog_id not in typed_values:
        return None
    value_data, value_type = typed_values[prog_id]
    operation = backup.record_removal(
        view, path, prog_id, value_data, extension, value_type
    )
    reg.delete_value(view, path, prog_id)
    return operation


# ProgID 键树上的标志性附加功能分支（大小写不敏感）。
# 这些分支存在说明定义承载了「打开命令」之外的功能。
_EXTRAS_KEYS = {
    "shellex",
    "defaulticon",
    "drophandler",
    "previewhandlers",
    "iconhandler",
}

_PROGID_VIEWS = (
    ViewKey.USER_CLASSES,
    ViewKey.SYSTEM_CLASSES_64,
    ViewKey.SYSTEM_CLASSES_32,
)


def progid_has_extras(reg: RegistryAdapter, prog_id: str) -> bool:
    """检测 ProgID 键树是否承载打开命令之外的功能（右键扩展、
    图标、预览、拖放等）。跨三个视图查找；检测是启发式的，
    未命中不代表穷尽所有扩展类型。"""
    for view in _PROGID_VIEWS:
        for sub in reg.list_subkeys(view, prog_id):
            lowered = sub.lower()
            if lowered in _EXTRAS_KEYS:
                return True
            if lowered == "shell":
                shell_subs = reg.list_subkeys(view, f"{prog_id}\\shell")
                if any(s.lower() != "open" for s in shell_subs):
                    return True
    return False


def remove_user_class_definition(
    reg: RegistryAdapter, backup: BackupManager, record: Association
) -> Operation | None:
    """删除用户级失效关联定义（HKCU\\Software\\Classes\\.ext 的默认值）。

    硬校验四项，任一不满足抛 ValueError：
    1. 视图必须是用户级；
    2. source 必须精确等于 HKCU\\Software\\Classes\\<extension>；
    3. 状态必须是失效（invalid）；
    4. 必须有 ProgID（有默认值可删）。
    只删扩展名键的默认值，不碰 ProgID 键树；删除前备份。
    """
    if record.view != RegistryView.USER:
        raise ValueError(f"只允许清理用户级关联定义: {record.view}")
    expected_source = rf"HKCU\Software\Classes\{record.extension}"
    if record.source != expected_source:
        raise ValueError(f"来源不是用户级关联定义: {record.source}")
    if record.status != Status.INVALID:
        raise ValueError(f"只允许清理失效的关联定义: {record.status}")
    if not record.prog_id:
        raise ValueError("该扩展名没有默认值，无需清理")

    default = reg.read_default(ViewKey.USER_CLASSES, record.extension)
    if not default:
        return None
    operation = backup.record_removal(
        ViewKey.USER_CLASSES, record.extension, None, default, record.extension
    )
    reg.delete_value(ViewKey.USER_CLASSES, record.extension, None)
    return operation
