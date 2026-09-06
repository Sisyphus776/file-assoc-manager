"""只读注册表适配层。

所有对注册表的访问必须经由 RegistryAdapter，禁止在扫描器/解析器中直接
调用 winreg。系统级键固定显式指定 WOW64 视图（见 CLAUDE.md 决策 1），
禁止依赖 winreg 的默认视图行为。

本模块默认只读：适配层不提供任何写入/删除方法。
"""

from abc import ABC, abstractmethod
from enum import Enum

import winreg


class ViewKey(Enum):
    """预定义的注册表视图根。

    每个成员映射到 (hive, 路径前缀, 附加访问标志)。
    """

    USER_FILE_EXTS = "user_file_exts"
    USER_CLASSES = "user_classes"
    SYSTEM_CLASSES_64 = "system_classes_64"
    SYSTEM_CLASSES_32 = "system_classes_32"
    SYSTEM_APP_PATHS_64 = "system_app_paths_64"
    SYSTEM_APP_PATHS_32 = "system_app_paths_32"


_WINREG_VIEWS: dict[ViewKey, tuple[int, str, int]] = {
    ViewKey.USER_FILE_EXTS: (
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts",
        0,
    ),
    ViewKey.USER_CLASSES: (winreg.HKEY_CURRENT_USER, r"Software\Classes", 0),
    ViewKey.SYSTEM_CLASSES_64: (
        winreg.HKEY_CLASSES_ROOT,
        "",
        winreg.KEY_WOW64_64KEY,
    ),
    ViewKey.SYSTEM_CLASSES_32: (
        winreg.HKEY_CLASSES_ROOT,
        "",
        winreg.KEY_WOW64_32KEY,
    ),
    ViewKey.SYSTEM_APP_PATHS_64: (
        winreg.HKEY_LOCAL_MACHINE,
        r"Software\Microsoft\Windows\CurrentVersion\App Paths",
        winreg.KEY_WOW64_64KEY,
    ),
    ViewKey.SYSTEM_APP_PATHS_32: (
        winreg.HKEY_LOCAL_MACHINE,
        r"Software\Microsoft\Windows\CurrentVersion\App Paths",
        winreg.KEY_WOW64_32KEY,
    ),
}


_WRITABLE_VIEWS = {ViewKey.USER_FILE_EXTS, ViewKey.USER_CLASSES}


def _assert_writable(view: ViewKey) -> None:
    """写入硬性校验：只允许 HKCU 用户视图。"""
    if view not in _WRITABLE_VIEWS:
        raise ValueError(f"拒绝写入系统级视图: {view}")


class RegistryAdapter(ABC):
    """注册表读取与受限写入接口，winreg 实现与内存 mock 实现可互换。

    写入仅允许 USER 视图（HKCU），见 AGENTS.md 约束 1、2。
    """

    @abstractmethod
    def list_subkeys(self, view: ViewKey, path: str) -> list[str]:
        """返回 path 下的子键名列表；path 不存在时返回空列表。"""

    @abstractmethod
    def read_default(self, view: ViewKey, path: str) -> str | None:
        """返回键的默认值；键不存在或默认值为空时返回 None。"""

    @abstractmethod
    def read_values(self, view: ViewKey, path: str) -> dict[str, str]:
        """返回键的命名值（name -> str）；键不存在时返回空字典。

        仅保留 REG_SZ / REG_EXPAND_SZ / REG_DWORD / REG_NONE 类型的值，
        其他类型（如 REG_BINARY）忽略。
        """

    @abstractmethod
    def set_value(self, view: ViewKey, path: str, name: str | None, value: str) -> None:
        """写入 REG_SZ 值（name 为 None 表示默认值），中间键自动创建。"""

    @abstractmethod
    def delete_value(self, view: ViewKey, path: str, name: str | None) -> None:
        """删除命名值（name 为 None 表示默认值）；键或值不存在时静默。"""

    @abstractmethod
    def delete_key(self, view: ViewKey, path: str) -> None:
        """删除空键；键不存在时静默。"""


def _join(base: str, path: str) -> str:
    return f"{base}\\{path}" if base and path else (base or path)


class WinRegAdapter(RegistryAdapter):
    """基于 winreg 的真实实现；写入仅限 USER 视图。"""

    def _open(self, view: ViewKey, path: str) -> winreg.HKEYType | None:
        hive, base, flags = _WINREG_VIEWS[view]
        full = _join(base, path)
        try:
            return winreg.OpenKey(hive, full, 0, winreg.KEY_READ | flags)
        except FileNotFoundError:
            return None

    def _create(self, view: ViewKey, path: str) -> winreg.HKEYType:
        _assert_writable(view)
        hive, base, _ = _WINREG_VIEWS[view]
        return winreg.CreateKey(hive, _join(base, path))

    def set_value(
        self, view: ViewKey, path: str, name: str | None, value: str
    ) -> None:
        key = self._create(view, path)
        with key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)

    def delete_value(self, view: ViewKey, path: str, name: str | None) -> None:
        _assert_writable(view)
        hive, base, flags = _WINREG_VIEWS[view]
        try:
            # 单独的 KEY_SET_VALUE 打开：受保护键（如 UserChoice）
            # 的 PermissionError 在此传播，不静默吞掉。
            key = winreg.OpenKey(
                hive, _join(base, path), 0, winreg.KEY_SET_VALUE | flags
            )
        except FileNotFoundError:
            return
        with key:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass

    def delete_key(self, view: ViewKey, path: str) -> None:
        _assert_writable(view)
        hive, base, _ = _WINREG_VIEWS[view]
        try:
            winreg.DeleteKey(hive, _join(base, path))
        except FileNotFoundError:
            pass

    def list_subkeys(self, view: ViewKey, path: str) -> list[str]:
        key = self._open(view, path)
        if key is None:
            return []
        with key:
            result, i = [], 0
            while True:
                try:
                    result.append(winreg.EnumKey(key, i))
                    i += 1
                except OSError:
                    return result

    def read_default(self, view: ViewKey, path: str) -> str | None:
        key = self._open(view, path)
        if key is None:
            return None
        with key:
            # 键存在但无默认值时 QueryValueEx 抛 FileNotFoundError，
            # 与键本身不存在的语义同为「没有默认值」。
            try:
                value, _ = winreg.QueryValueEx(key, None)
            except FileNotFoundError:
                return None
            if value is None:
                return None
            return str(value)

    def read_values(self, view: ViewKey, path: str) -> dict[str, str]:
        key = self._open(view, path)
        if key is None:
            return {}
        with key:
            result, i = {}, 0
            while True:
                try:
                    name, value, value_type = winreg.EnumValue(key, i)
                except OSError:
                    return result
                i += 1
                if name and value_type in (
                    winreg.REG_SZ,
                    winreg.REG_EXPAND_SZ,
                    winreg.REG_DWORD,
                    winreg.REG_NONE,
                ):
                    result[name] = "" if value is None else str(value)
