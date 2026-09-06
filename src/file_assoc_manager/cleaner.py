"""选择性清理：删除 OpenWithList / OpenWithProgids 的指定条目。

流程固定为「备份 -> 删除」（docs/design.md 第 4 节）：
record_removal 成功后才执行删除，未找到目标条目时不做任何操作。
只删除单个值，不删除整个键。
"""

from .backup import BackupManager, Operation
from .registry import RegistryAdapter, ViewKey


def remove_open_with_entry(
    reg: RegistryAdapter,
    backup: BackupManager,
    extension: str,
    program_name: str,
) -> Operation | None:
    """删除 FileExts\\.ext\\OpenWithList 中值内容为 program_name 的条目。

    值名是字母索引（a/b/c），必须按值内容定位；MRUList 是顺序索引串，
    跳过。未找到时返回 None。
    """
    view = ViewKey.USER_FILE_EXTS
    path = f"{extension}\\OpenWithList"
    for value_name, value_data in reg.read_values(view, path).items():
        if value_name == "MRUList":
            continue
        if value_data == program_name:
            operation = backup.record_removal(
                view, path, value_name, value_data, extension
            )
            reg.delete_value(view, path, value_name)
            return operation
    return None


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
    values = reg.read_values(view, path)
    if prog_id not in values:
        return None
    operation = backup.record_removal(
        view, path, prog_id, values[prog_id], extension
    )
    reg.delete_value(view, path, prog_id)
    return operation
