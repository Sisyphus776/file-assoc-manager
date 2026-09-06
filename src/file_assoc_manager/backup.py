"""备份与恢复。

删除任何值之前必须先调用 record_removal 生成 .reg 快照并追加 JSON
操作日志；restore 按日志把值写回。对外表述为「备份 + 操作日志 + 可恢复」，
不称为事务（注册表没有跨键事务，见 docs/design.md 第 4 节）。
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .registry import RegistryAdapter, ViewKey

APP_DIR_NAME = "FileAssocManager"

# .reg 快照仅覆盖可写的 USER 视图，键路径写死为完整注册表路径。
_HIVE_PATHS: dict[ViewKey, str] = {
    ViewKey.USER_FILE_EXTS: (
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion"
        r"\Explorer\FileExts"
    ),
    ViewKey.USER_CLASSES: r"HKEY_CURRENT_USER\Software\Classes",
}


def default_data_dir() -> Path:
    """工具数据目录：%APPDATA%\\FileAssocManager（用户范围）。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME}"


@dataclass
class Operation:
    """一次删除操作的完整记录，支持按条恢复。"""

    timestamp: str
    action: str
    extension: str
    view: str  # ViewKey.value
    key_path: str  # 视图内相对路径，如 ".txt\\OpenWithList"
    value_name: str | None  # 被删除的值；None 表示默认值
    value_data: str  # 被删除值的内容快照
    backup_file: str  # .reg 快照文件路径


class BackupManager:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or default_data_dir()
        self.backup_dir = self.data_dir / "backups"
        self.log_path = self.data_dir / "operations.json"

    def record_removal(
        self,
        view: ViewKey,
        key_path: str,
        value_name: str | None,
        value_data: str,
        extension: str = "",
    ) -> Operation:
        """删除前的快照：写 .reg 备份 + 追加 JSON 日志。

        调用方必须在 record_removal 成功返回后执行删除。
        """
        if view not in _HIVE_PATHS:
            raise ValueError(f"不可备份的视图: {view}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        backup_file = self.backup_dir / f"{timestamp}_remove.reg"
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file.write_text(
            _build_reg_file(_HIVE_PATHS[view], key_path, value_name, value_data),
            encoding="utf-16",  # reg v5 格式：UTF-16 LE 带 BOM
            newline="",  # 保持 \r\n 字面，不依赖平台换行转换
        )
        operation = Operation(
            timestamp=timestamp,
            action="remove_value",
            extension=extension,
            view=view.value,
            key_path=key_path,
            value_name=value_name,
            value_data=value_data,
            backup_file=str(backup_file),
        )
        self._append_log(operation)
        return operation

    def list_operations(self) -> list[Operation]:
        """按时间倒序返回操作历史；日志缺失时返回空列表。"""
        if not self.log_path.exists():
            return []
        try:
            raw = json.loads(self.log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        result = [Operation(**entry) for entry in raw]
        result.reverse()
        return result

    def restore(self, reg: RegistryAdapter, operation: Operation) -> None:
        """把被删除的值写回原位置。"""
        reg.set_value(
            ViewKey(operation.view),
            operation.key_path,
            operation.value_name,
            operation.value_data,
        )

    def _append_log(self, operation: Operation) -> None:
        existing = []
        if self.log_path.exists():
            try:
                existing = json.loads(self.log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = []
        self.data_dir.mkdir(parents=True, exist_ok=True)
        existing.append(asdict(operation))
        self.log_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def _build_reg_file(
    hive_path: str, key_path: str, value_name: str | None, value_data: str
) -> str:
    """生成 Windows Registry Editor Version 5.00 格式的快照文本。"""
    full_key = f"{hive_path}\\{key_path}" if key_path else hive_path
    escaped = value_data.replace("\\", "\\\\").replace('"', '\\"')
    value_line = (
        f'@="{escaped}"\r\n' if value_name is None else f'"{value_name}"="{escaped}"\r\n'
    )
    return (
        "Windows Registry Editor Version 5.00\r\n"
        "\r\n"
        f"[{full_key}]\r\n"
        f"{value_line}"
    )
