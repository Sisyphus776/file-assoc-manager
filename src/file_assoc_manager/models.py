"""扫描数据模型。"""

from dataclasses import dataclass
from enum import Enum


class RegistryView(Enum):
    """关联记录的注册表来源视图。

    WOW64 重定向导致同一个键在 64 位与 32 位视图各有内容，
    必须区分展示，否则用户无法理解为何同一扩展名出现两条。
    """

    USER = "user"
    SYSTEM_64 = "system_64"
    SYSTEM_32 = "system_32"


class Status(Enum):
    """关联记录的有效性三分类（见 docs/design.md 第 3 节）。"""

    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


@dataclass
class Association:
    """一条文件关联记录。

    extension   扩展名，如 ".txt"（保留扫描到的原始大小写）
    source      来源键路径，如 r"HKCU\\Software\\Classes\\.txt"
    view        来源视图（用户级 / 系统 64 位 / 系统 32 位）
    prog_id     关联的 ProgID；OpenWithList 条目为 None
    command     解析出的打开命令原文；无法解析为 None
    target_path 解析出的程序绝对路径；无法解析为 None
    status      有效性分类
    reason      status 为 INVALID / UNKNOWN 时的原因
    """

    extension: str
    source: str
    view: RegistryView
    prog_id: str | None
    command: str | None
    target_path: str | None
    status: Status
    reason: str | None = None
    # 精确路径不存在时，在同一安装目录内找到的同名程序（仅作提示，不改变判定）
    suggested_path: str | None = None
