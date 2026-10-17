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
import re

from .models import Association, Status
from .registry import RegistryAdapter, ViewKey

_OPEN_COMMAND_VIEWS = (
    ViewKey.USER_CLASSES,
    ViewKey.SYSTEM_CLASSES_64,
    ViewKey.SYSTEM_CLASSES_32,
)

# 安装器误把 reg query 输出整行写进值的前缀，如 (Default)    REG_SZ    "..."
_REG_PREFIX = re.compile(r"^\(Default\)\s+REG_SZ\s+", re.IGNORECASE)


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
        if record.command is None:
            if not _progid_key_exists(reg, record.prog_id):
                # ProgID 键本身已不存在：真残留
                record.status = Status.INVALID
                record.reason = f"ProgID key does not exist: {record.prog_id}"
                return
            if _has_delegate_execute(reg, record.prog_id):
                # UWP 等现代应用走 DelegateExecute，没有传统打开命令
                record.status = Status.UNKNOWN
                record.reason = (
                    "Handled by a system component (DelegateExecute), "
                    "cannot check file path."
                )
                return
            record.status = Status.UNKNOWN
            record.reason = "ProgID has no open command."
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


def _progid_key_exists(reg: RegistryAdapter, prog_id: str) -> bool:
    """ProgID 键在任一 Classes 视图中是否存在。"""
    return any(reg.key_exists(view, prog_id) for view in _OPEN_COMMAND_VIEWS)


def _is_app_user_model_id(path: str) -> bool:
    """AppUserModelID 形如 PackageFamilyName!AppId（如
    Microsoft.WindowsNotepad_8wekyb3d8bbwe!App），不是文件路径。"""
    return "!" in path and not os.path.isabs(path)


# 无引号路径拼接时，遇到这些扩展名即视为路径完整（即使文件已不存在）。
_EXECUTABLE_EXTS = (".exe", ".com", ".bat", ".cmd", ".msi", ".psc1")

# 命令行占位参数，拼接遇到即停；单独的占位符不是程序路径。
_PLACEHOLDER_TOKENS = frozenset({"%1", "%*", "%2", "%3", "%4", "%L"})


def _extract_program_path(command: str) -> str | None:
    """从打开命令字符串中提取程序路径。

    处理引号包裹的路径、%VAR% 环境变量与 "%1" 等参数，并剥离安装器
    误写入的 reg query 输出前缀（如 `(Default)    REG_SZ    "..."`）。
    无引号且路径含空格时（如 D:\\Program Files\\...\\app.exe），
    从首 token 起逐个追加，取最长的「确实存在的文件」路径；
    遇到 %1 等占位符、或路径以可执行扩展名结尾即停。
    命令本身只是占位符（如 `"%1" %*`）时返回 None——
    这类 ProgID 由 shell 托管，没有可执行文件，属 unknown 而非 invalid。
    """
    command = os.path.expandvars(command.strip())
    command = _REG_PREFIX.sub("", command).strip()
    if not command:
        return None
    if command.startswith('"'):
        end = command.find('"', 1)
        candidate = command[1:end] if end != -1 else command[1:]
        return None if candidate.upper() in _PLACEHOLDER_TOKENS else candidate
    parts = command.split()
    best = parts[0]
    candidate = ""
    for token in parts:
        if token.upper() in _PLACEHOLDER_TOKENS:
            break
        if token.startswith(("-", "/")):
            # 参数开关（如 -arg /x）：无扩展名程序的路径到此为止
            break
        candidate = token if not candidate else candidate + " " + token
        if os.path.isfile(candidate):
            return candidate
        if candidate.lower().endswith(_EXECUTABLE_EXTS):
            # 可执行扩展名结尾说明路径已完整，即使文件不存在（已卸载）
            return candidate
        best = candidate
    return None if best.upper() in _PLACEHOLDER_TOKENS else best


def _resolve_by_name(reg: RegistryAdapter, name: str) -> str | None:
    """把裸程序名解析为绝对路径：App Paths 优先，PATH 兜底。"""
    for view in (ViewKey.SYSTEM_APP_PATHS_64, ViewKey.SYSTEM_APP_PATHS_32):
        found = reg.read_default(view, name)
        if found:
            return found
    return _search_path(name)


def _search_path(name: str) -> str | None:
    base_name, ext = os.path.splitext(name)
    if ext:
        # 已有扩展名，直接搜
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(directory, name)
            if os.path.isfile(candidate):
                return candidate
        return None
    # 无扩展名：按 PATHEXT 顺序补扩展名（.exe .com .bat .cmd ...）
    pathext = os.environ.get("PATHEXT", ".exe")
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        for suffix in pathext.split(os.pathsep):
            candidate = os.path.join(directory, base_name + suffix)
            if os.path.isfile(candidate):
                return candidate
    return None
