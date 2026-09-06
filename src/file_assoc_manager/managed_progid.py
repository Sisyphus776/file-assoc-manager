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
        """注册便携程序的关联；重复注册同一程序时保留最初的原默认值。"""
        ext = extension if extension.startswith(".") else f".{extension}"
        prog_id = PROGID_PREFIX + _sanitize_stem(program_path)
        records = _load(self.managed_path)

        existing = next((r for r in records if r.prog_id == prog_id), None)
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

    def unregister(self, prog_id: str) -> None:
        """撤销本工具创建的关联：恢复扩展名原默认值并删除 ProgID 键。"""
        records = _load(self.managed_path)
        match = next((r for r in records if r.prog_id == prog_id), None)
        if match is None:
            raise ValueError(f"不是本工具管理的 ProgID: {prog_id}")

        if match.previous_default is not None:
            self.reg.set_value(
                ViewKey.USER_CLASSES,
                match.extension,
                None,
                match.previous_default,
            )
        else:
            self.reg.delete_value(ViewKey.USER_CLASSES, match.extension, None)

        _delete_key_tree(self.reg, ViewKey.USER_CLASSES, match.prog_id)
        _save(self.managed_path, [r for r in records if r.prog_id != prog_id])


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
    return [ManagedProgId(**entry) for entry in raw]


def _save(path: Path, records: list[ManagedProgId]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
