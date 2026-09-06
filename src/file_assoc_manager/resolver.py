"""关联解析器。

把扫描到的 ProgID / 程序名解析为打开命令与程序路径，并做有效性分类。

解析链（见 docs/design.md 第 3 节）：
- ProgID          -> 用户级 Classes -> 系统 64 位视图 -> 系统 32 位视图，
                     读 \\shell\\open\\command 默认值
- OpenWithList 裸名 -> Classes\\Applications\\<name> 的打开命令；
                     仍解析不出路径时走 App Paths 与 PATH 搜索

注册表字符串不可信（可能是裸文件名、环境变量或缺失），
只有解析出绝对路径并验证文件存在才算 valid。
"""

import os

from .models import Association, Status
from .registry import RegistryAdapter, ViewKey

_OPEN_COMMAND_VIEWS = (
    ViewKey.USER_CLASSES,
    ViewKey.SYSTEM_CLASSES_64,
    ViewKey.SYSTEM_CLASSES_32,
)


def resolve_all(records: list[Association], reg: RegistryAdapter) -> None:
    """就地填充每条记录的命令、路径与状态。"""
    for record in records:
        resolve(record, reg)


def resolve(record: Association, reg: RegistryAdapter) -> None:
    # command 字段永远保持注册表原始值（清理器按它定位待删条目）；
    # Applications 键的命令只用于解析路径，不覆盖 command。
    path_source: str | None = record.command
    if record.prog_id is not None:
        record.command = _read_open_command(reg, record.prog_id)
        if record.command is None and _has_delegate_execute(reg, record.prog_id):
            # UWP 等现代应用走 DelegateExecute，没有传统打开命令
            record.status = Status.UNKNOWN
            record.reason = (
                "Handled by a system component (DelegateExecute), "
                "cannot check file path."
            )
            return
        path_source = record.command
    elif record.command:
        # OpenWithList 的裸程序名：优先 Applications 键的命令定义
        app_cmd = _read_open_command(reg, f"Applications\\{record.command}")
        if app_cmd:
            path_source = app_cmd

    path = _extract_program_path(path_source) if path_source else None
    record.target_path = path

    if path is None:
        record.status = Status.UNKNOWN
        record.reason = "No usable program path in open command."
    elif _is_app_user_model_id(path):
        record.status = Status.UNKNOWN
        record.reason = "UWP app, cannot check file path."
    elif os.path.isabs(path):
        if os.path.isfile(path):
            record.status = Status.VALID
        else:
            record.status = Status.INVALID
            record.reason = f"Program file not found: {path}"
    else:
        resolved = _resolve_by_name(reg, path)
        if resolved:
            record.target_path = resolved
            record.status = Status.VALID
        else:
            record.status = Status.INVALID
            record.reason = f"Program not found or not in PATH: {path}"


def _read_open_command(reg: RegistryAdapter, prog_id: str) -> str | None:
    """按 用户级 -> 系统 64 位 -> 系统 32 位 顺序读打开命令。"""
    for view in _OPEN_COMMAND_VIEWS:
        command = reg.read_default(view, f"{prog_id}\\shell\\open\\command")
        if command:
            return command
    return None


def _has_delegate_execute(reg: RegistryAdapter, prog_id: str) -> bool:
    """UWP 应用的 ProgID 没有 shell\\open\\command，而是 DelegateExecute 值。"""
    for view in _OPEN_COMMAND_VIEWS:
        values = reg.read_values(view, f"{prog_id}\\shell\\open\\command")
        if "DelegateExecute" in values:
            return True
    return False


def _is_app_user_model_id(path: str) -> bool:
    """AppUserModelID 形如 PackageFamilyName!AppId（如
    Microsoft.WindowsNotepad_8wekyb3d8bbwe!App），不是文件路径。"""
    return "!" in path and not os.path.isabs(path)


def _extract_program_path(command: str) -> str | None:
    """从打开命令字符串中提取程序路径。

    处理引号包裹的路径、%VAR% 环境变量与 "%1" 等参数。
    不校验文件是否存在。
    """
    command = os.path.expandvars(command.strip())
    if not command:
        return None
    if command.startswith('"'):
        end = command.find('"', 1)
        return command[1:end] if end != -1 else command[1:]
    return command.split(None, 1)[0]


def _resolve_by_name(reg: RegistryAdapter, name: str) -> str | None:
    """把裸程序名解析为绝对路径：App Paths 优先，PATH 兜底。"""
    for view in (ViewKey.SYSTEM_APP_PATHS_64, ViewKey.SYSTEM_APP_PATHS_32):
        found = reg.read_default(view, name)
        if found:
            return found
    return _search_path(name)


def _search_path(name: str) -> str | None:
    if not os.path.splitext(name)[1]:
        name += ".exe"
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = os.path.join(directory, name)
        if os.path.isfile(candidate):
            return candidate
    return None
