"""备份与恢复。

删除任何值之前必须先调用 record_removal 生成 .reg 快照并追加 JSON
操作日志；restore 按日志把值写回。对外表述为「备份 + 操作日志 + 可恢复」，
不称为事务（注册表没有跨键事务，见 docs/design.md 第 4 节）。
"""

import json
import os
import winreg
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
    value_type: int = winreg.REG_SZ  # 原始 winreg 类型（恢复时保真）


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
        value_type: int = winreg.REG_SZ,
    ) -> Operation:
        """删除前的快照：写 .reg 备份 + 追加 JSON 日志。

        调用方必须在 record_removal 成功返回后执行删除。
        """
        if view not in _HIVE_PATHS:
            raise ValueError(f"不可备份的视图: {view}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        backup_file = self._unique_backup_path(timestamp)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        backup_file.write_text(
            _build_reg_file(
                _HIVE_PATHS[view], key_path, value_name, value_data, value_type
            ),
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
            value_type=value_type,
        )
        self._append_log(operation)
        return operation

    def _unique_backup_path(self, timestamp: str) -> Path:
        """同毫秒内的多次操作不能互相覆盖：追加序号直到不重名。"""
        candidate = self.backup_dir / f"{timestamp}_remove.reg"
        counter = 1
        while candidate.exists():
            candidate = self.backup_dir / f"{timestamp}_remove_{counter}.reg"
            counter += 1
        return candidate

    def list_operations(self) -> list[Operation]:
        """按时间倒序返回操作历史；日志缺失时返回空列表。"""
        if not self.log_path.exists():
            return []
        try:
            raw = json.loads(self.log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        result = [
            Operation(
                **{k: v for k, v in entry.items() if k in Operation.__dataclass_fields__}
            )
            for entry in raw
        ]
        result.reverse()
        return result

    def restore(self, reg: RegistryAdapter, operation: Operation) -> None:
        """把被删除的值按原始类型写回原位置。"""
        reg.set_value(
            ViewKey(operation.view),
            operation.key_path,
            operation.value_name,
            operation.value_data,
            value_type=operation.value_type,
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
        # 原子写：先写临时文件再替换，避免中途崩溃留下半个 JSON
        tmp_path = self.log_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp_path.replace(self.log_path)


def _escape_reg_string(text: str) -> str:
    """.reg 字符串字面量转义：反斜杠与双引号。"""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _build_reg_file(
    hive_path: str,
    key_path: str,
    value_name: str | None,
    value_data: str,
    value_type: int = winreg.REG_SZ,
) -> str:
    """生成 Windows Registry Editor Version 5.00 格式的快照文本。

    REG_SZ / REG_EXPAND_SZ 以字符串语法写出（EXPAND_SZ 导入后类型退化为
    REG_SZ，属可接受近似）；REG_DWORD 用 dword: 语法；空 REG_NONE 用 hex(0):。
    """
    full_key = f"{hive_path}\\{key_path}" if key_path else hive_path
    if value_name is None:
        name_part = "@"
    else:
        name_part = f'"{_escape_reg_string(value_name)}"'
    if value_type == winreg.REG_DWORD:
        data_part = f"dword:{int(value_data):08x}"
    elif value_type == winreg.REG_NONE:
        data_part = "hex(0):" if not value_data else (
            "hex(0):" + ",".join(f"{b:02x}" for b in value_data.encode("utf-8"))
        )
    else:
        data_part = f'"{_escape_reg_string(value_data)}"'
    value_line = f"{name_part}={data_part}\r\n"
    return (
        "Windows Registry Editor Version 5.00\r\n"
        "\r\n"
        f"[{full_key}]\r\n"
        f"{value_line}"
    )
