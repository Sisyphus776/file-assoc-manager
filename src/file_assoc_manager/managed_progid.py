"""本工具创建的 ProgID 管理。

为便携程序在 HKCU\\Software\\Classes 下注册 FAM.<程序名> 形式的
ProgID；撤销时恢复注册前该扩展名的默认值，并递归删除自己的键。

撤销只信任 managed.json 中的记录，不提供按任意 ProgID 名删除的能力
（防止误删用户自己的关联定义）。
"""

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .backup import BackupManager
from .registry import RegistryAdapter, ViewKey

PROGID_PREFIX = "FAM."

# 扩展名合法形态：.aaa / .tar.gz 等；不允许路径分隔符与 ".."
_EXT_RE = re.compile(r"^\.[A-Za-z0-9][A-Za-z0-9._-]*$")


def _validate_extension(extension: str) -> str:
    """规范化并校验扩展名，返回带点小写形式；非法时抛 ValueError。"""
    ext = extension.strip().lower()
    if not ext.startswith("."):
        ext = "." + ext
    if not _EXT_RE.match(ext) or ".." in ext:
        raise ValueError(f"非法扩展名: {extension!r}（应形如 .aaa）")
    return ext


@dataclass
class ManagedProgId:
    prog_id: str
    extension: str
    program_path: str
    previous_default: str | None  # 注册前该扩展名的默认值；None 表示原本无


class ProgIdManager:
    def __init__(self, reg: RegistryAdapter, backup: BackupManager):
        self.reg = reg
        self.backup = backup
        self.managed_path = Path(backup.data_dir) / "managed.json"

    def register(self, extension: str, program_path: str) -> ManagedProgId:
        """注册便携程序的关联；重复注册同一扩展名时保留最初的原默认值。

        同一程序可挂多个扩展名（各一条台账记录，各存各的 previous_default）。
        program_path 必须是实际存在的可执行文件路径，否则抛出 ValueError。
        """
        if not os.path.isfile(program_path):
            raise ValueError(f"程序路径不存在: {program_path}")
        ext = _validate_extension(extension)
        prog_id = PROGID_PREFIX + _sanitize_stem(program_path)
        records = _load(self.managed_path)

        existing = next(
            (r for r in records if r.prog_id == prog_id and r.extension == ext),
            None,
        )
        if existing is not None:
            previous = existing.previous_default
            records.remove(existing)
        else:
            previous = self.reg.read_default(ViewKey.USER_CLASSES, ext)
            if previous is not None:
                self.backup.record_removal(
                    ViewKey.USER_CLASSES, ext, None, previous, ext
                )

        self.reg.set_value(
            ViewKey.USER_CLASSES,
            f"{prog_id}\\shell\\open\\command",
            None,
            f'"{program_path}" "%1"',
        )
        self.reg.set_value(ViewKey.USER_CLASSES, ext, None, prog_id)

        managed = ManagedProgId(prog_id, ext, program_path, previous)
        records.append(managed)
        _save(self.managed_path, records)
        return managed

    def list_managed(self) -> list[ManagedProgId]:
        return _load(self.managed_path)

    def unregister(self, prog_id: str, extension: str | None = None) -> None:
        """撤销本工具创建的关联：恢复扩展名原默认值。

        同一 ProgID 挂了多个扩展名时，只移除 extension 指定的那条记录；
        最后一个扩展名移除后才备份 command 值并删除 ProgID 键树。
        """
        records = _load(self.managed_path)
        match = next(
            (
                r
                for r in records
                if r.prog_id == prog_id
                and (extension is None or r.extension == extension)
            ),
            None,
        )
        if match is None:
            raise ValueError(f"不是本工具管理的 ProgID: {prog_id}")

        # 备份当前扩展名默认值（将被恢复或删除）
        current_default = self.reg.read_default(ViewKey.USER_CLASSES, match.extension)
        if current_default is not None:
            self.backup.record_removal(
                ViewKey.USER_CLASSES,
                match.extension,
                None,
                current_default,
                match.extension,
            )

        if match.previous_default is not None:
            self.reg.set_value(
                ViewKey.USER_CLASSES,
                match.extension,
                None,
                match.previous_default,
            )
        else:
            self.reg.delete_value(ViewKey.USER_CLASSES, match.extension, None)

        records.remove(match)
        if not any(r.prog_id == prog_id for r in records):
            # 最后一个扩展名：备份 command 值后递归删除键树
            cmd = self.reg.read_default(
                ViewKey.USER_CLASSES, f"{match.prog_id}\\shell\\open\\command"
            )
            if cmd is not None:
                self.backup.record_removal(
                    ViewKey.USER_CLASSES,
                    f"{match.prog_id}\\shell\\open\\command",
                    None,
                    cmd,
                    match.extension,
                )
            _delete_key_tree(self.reg, ViewKey.USER_CLASSES, match.prog_id)

        _save(self.managed_path, records)


def _sanitize_stem(program_path: str) -> str:
    stem = os.path.splitext(os.path.basename(program_path))[0]
    return re.sub(r"[^A-Za-z0-9_.-]", "_", stem)


def _delete_key_tree(reg: RegistryAdapter, view: ViewKey, path: str) -> None:
    """递归删除键树。仅用于本工具自己创建的 ProgID 键。"""
    for sub in reg.list_subkeys(view, path):
        _delete_key_tree(reg, view, f"{path}\\{sub}")
    reg.delete_key(view, path)


def _load(path: Path) -> list[ManagedProgId]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    fields = ManagedProgId.__dataclass_fields__
    return [ManagedProgId(**{k: v for k, v in e.items() if k in fields}) for e in raw]


def _save(path: Path, records: list[ManagedProgId]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # 原子写：先写临时文件再替换，避免中途崩溃留下半个 JSON
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)
