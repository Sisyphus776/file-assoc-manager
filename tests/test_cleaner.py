"""清理器测试：备份先行、值名定位、未找到时零操作、失效定义清理。"""

import pytest

from file_assoc_manager.backup import BackupManager
from file_assoc_manager.cleaner import (
    progid_has_extras,
    remove_open_with_entry,
    remove_open_with_progid,
    remove_user_class_definition,
)
from file_assoc_manager.models import Association, RegistryView, Status
from file_assoc_manager.registry import ViewKey

from mock_registry import MockRegistryAdapter, mock_key


def make_reg():
    return MockRegistryAdapter(
        {
            ViewKey.USER_FILE_EXTS: mock_key(
                subkeys={
                    ".txt": mock_key(
                        subkeys={
                            "OpenWithList": mock_key(
                                values={
                                    "a": "notepad.exe",
                                    "b": "oldapp.exe",
                                    "MRUList": "ba",
                                }
                            ),
                            "OpenWithProgids": mock_key(
                                values={"txtfile": "", "ghostprog": ""}
                            ),
                        }
                    )
                }
            )
        }
    )


class TestRemoveOpenWithEntry:
    def test_removes_by_value_content(self, tmp_path):
        reg = make_reg()
        backup = BackupManager(data_dir=tmp_path)
        op = remove_open_with_entry(reg, backup, ".txt", "oldapp.exe")
        assert op is not None
        assert op.value_name == "b"
        values = reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList")
        # 删除 "b" 后 MRUList 同步从 "ba" 变为 "a"
        assert values == {"a": "notepad.exe", "MRUList": "a"}
        # 备份先行：目标值 + MRUList 各一条
        assert len(backup.list_operations()) == 2

    def test_mru_list_removes_all_occurrences(self, tmp_path):
        """脏 MRUList（如 "aba"）中删除的字母要全部剔除，不留悬挂引用。"""
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_FILE_EXTS: mock_key(
                    subkeys={
                        ".txt": mock_key(
                            subkeys={
                                "OpenWithList": mock_key(
                                    values={
                                        "a": "notepad.exe",
                                        "b": "oldapp.exe",
                                        "MRUList": "aba",
                                    }
                                )
                            }
                        )
                    }
                )
            }
        )
        backup = BackupManager(data_dir=tmp_path)
        remove_open_with_entry(reg, backup, ".txt", "oldapp.exe")
        values = reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList")
        assert values["MRUList"] == "aa"

    def test_mru_list_absent_is_tolerated(self, tmp_path):
        """OpenWithList 里没有 MRUList 时，删除照常进行且不报错。"""
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_FILE_EXTS: mock_key(
                    subkeys={
                        ".txt": mock_key(
                            subkeys={
                                "OpenWithList": mock_key(values={"a": "oldapp.exe"})
                            }
                        )
                    }
                )
            }
        )
        backup = BackupManager(data_dir=tmp_path)
        op = remove_open_with_entry(reg, backup, ".txt", "oldapp.exe")
        assert op is not None
        assert reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList") == {}
        assert len(backup.list_operations()) == 1

    def test_mru_list_restored_with_entry(self, tmp_path):
        """恢复时 MRUList 快照也应恢复原有顺序串。"""
        reg = make_reg()
        backup = BackupManager(data_dir=tmp_path)
        remove_open_with_entry(reg, backup, ".txt", "oldapp.exe")
        ops = backup.list_operations()
        for op in ops:
            backup.restore(reg, op)
        values = reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList")
        assert values == {"a": "notepad.exe", "b": "oldapp.exe", "MRUList": "ba"}

    def test_mrulist_is_never_removed(self, tmp_path):
        reg = make_reg()
        backup = BackupManager(data_dir=tmp_path)
        # 值内容与 MRUList 的值恰好相同也不删它
        assert remove_open_with_entry(reg, backup, ".txt", "ba") is None
        assert reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList")["MRUList"] == "ba"

    def test_not_found_yields_no_operation_and_no_backup(self, tmp_path):
        reg = make_reg()
        backup = BackupManager(data_dir=tmp_path)
        assert remove_open_with_entry(reg, backup, ".txt", "ghost.exe") is None
        assert len(backup.list_operations()) == 0
        assert list((tmp_path / "backups").glob("*")) == []

    def test_remove_open_with_progid(self, tmp_path):
        reg = make_reg()
        backup = BackupManager(data_dir=tmp_path)
        op = remove_open_with_progid(reg, backup, ".txt", "ghostprog")
        assert op is not None
        assert op.value_name == "ghostprog"
        values = reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithProgids")
        assert values == {"txtfile": ""}

    def test_progid_not_found_yields_none(self, tmp_path):
        reg = make_reg()
        backup = BackupManager(data_dir=tmp_path)
        assert remove_open_with_progid(reg, backup, ".txt", "nope") is None


def make_def_record(**kwargs):
    """构造用户级失效关联定义记录。"""
    defaults = dict(
        extension=".apk",
        source=r"HKCU\Software\Classes\.apk",
        view=RegistryView.USER,
        prog_id="Androws.apk",
        command=None,
        target_path=None,
        status=Status.INVALID,
    )
    defaults.update(kwargs)
    return Association(**defaults)


def make_def_reg():
    """用户级失效定义：.apk → Androws.apk → 命令指向不存在路径。"""
    return MockRegistryAdapter(
        {
            ViewKey.USER_CLASSES: mock_key(
                subkeys={
                    ".apk": mock_key(default="Androws.apk"),
                    "Androws.apk": mock_key(
                        subkeys={
                            "shell": mock_key(
                                subkeys={
                                    "open": mock_key(
                                        subkeys={
                                            "command": mock_key(
                                                default='"C:\\gone\\Androws.exe" "%1"'
                                            )
                                        }
                                    )
                                }
                            )
                        }
                    ),
                }
            )
        }
    )


class TestRemoveUserClassDefinition:
    def test_removes_default_with_backup_and_keeps_progid_tree(self, tmp_path):
        reg = make_def_reg()
        backup = BackupManager(data_dir=tmp_path)
        op = remove_user_class_definition(reg, backup, make_def_record())
        assert op is not None
        assert reg.read_default(ViewKey.USER_CLASSES, ".apk") is None
        assert len(backup.list_operations()) == 1
        # ProgID 键树未被删除
        assert (
            reg.read_default(ViewKey.USER_CLASSES, r"Androws.apk\shell\open\command")
            == '"C:\\gone\\Androws.exe" "%1"'
        )

    def test_restore_brings_default_back(self, tmp_path):
        reg = make_def_reg()
        backup = BackupManager(data_dir=tmp_path)
        op = remove_user_class_definition(reg, backup, make_def_record())
        backup.restore(reg, op)
        assert reg.read_default(ViewKey.USER_CLASSES, ".apk") == "Androws.apk"

    def test_missing_progid_is_rejected(self, tmp_path):
        record = make_def_record(prog_id=None)
        with pytest.raises(ValueError):
            remove_user_class_definition(
                make_def_reg(), BackupManager(data_dir=tmp_path), record
            )

    def test_registry_default_already_gone_returns_none(self, tmp_path):
        """记录有 prog_id 但注册表里默认值已不存在：返回 None，零操作。"""
        reg = MockRegistryAdapter(
            {ViewKey.USER_CLASSES: mock_key(subkeys={".zzz": mock_key()})}
        )
        record = make_def_record(
            extension=".zzz", source=r"HKCU\Software\Classes\.zzz"
        )
        backup = BackupManager(data_dir=tmp_path)
        assert remove_user_class_definition(reg, backup, record) is None
        assert len(backup.list_operations()) == 0

    def test_rejects_valid_status(self, tmp_path):
        record = make_def_record(status=Status.VALID)
        with pytest.raises(ValueError):
            remove_user_class_definition(make_def_reg(), BackupManager(data_dir=tmp_path), record)

    def test_rejects_unknown_status(self, tmp_path):
        record = make_def_record(status=Status.UNKNOWN)
        with pytest.raises(ValueError):
            remove_user_class_definition(make_def_reg(), BackupManager(data_dir=tmp_path), record)

    def test_rejects_system_view(self, tmp_path):
        record = make_def_record(view=RegistryView.SYSTEM_64)
        with pytest.raises(ValueError):
            remove_user_class_definition(make_def_reg(), BackupManager(data_dir=tmp_path), record)

    def test_rejects_mismatched_source(self, tmp_path):
        record = make_def_record(source=r"HKCU\Software\Classes\.docx")
        with pytest.raises(ValueError):
            remove_user_class_definition(make_def_reg(), BackupManager(data_dir=tmp_path), record)


class TestProgidHasExtras:
    def test_shellex_detected(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={"p": mock_key(subkeys={"shellex": mock_key()})}
                )
            }
        )
        assert progid_has_extras(reg, "p")

    def test_defaulticon_detected(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={"p": mock_key(subkeys={"DefaultIcon": mock_key()})}
                )
            }
        )
        assert progid_has_extras(reg, "p")

    def test_shell_edit_detected(self):
        """shell 下存在 open 之外的子键（如 edit/print）也算附加功能。"""
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={"p": mock_key(subkeys={"shell": mock_key(subkeys={"edit": mock_key()})})}
                )
            }
        )
        assert progid_has_extras(reg, "p")

    def test_only_open_returns_false(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={"p": mock_key(subkeys={"shell": mock_key(subkeys={"open": mock_key()})})}
                )
            }
        )
        assert not progid_has_extras(reg, "p")

    def test_detected_in_system_view(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.SYSTEM_CLASSES_64: mock_key(
                    subkeys={"p": mock_key(subkeys={"PreviewHandlers": mock_key()})}
                )
            }
        )
        assert progid_has_extras(reg, "p")

    def test_missing_progid_returns_false(self):
        assert not progid_has_extras(MockRegistryAdapter(), "ghost")
