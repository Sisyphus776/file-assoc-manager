"""真实注册表全流程：造脏数据 -> 备份 -> 删除 -> 恢复 -> 验证。

只在 HKCU 的 FileExts 假扩展名键 FileAssocManagerTest.zzz 上操作，
测试结束删除，绝不触碰真实关联数据。
"""

import winreg

import pytest

from file_assoc_manager.backup import BackupManager
from file_assoc_manager.cleaner import (
    remove_open_with_entry,
    remove_user_class_definition,
)
from file_assoc_manager.managed_progid import ProgIdManager
from file_assoc_manager.models import Association, RegistryView, Status
from file_assoc_manager.registry import ViewKey, WinRegAdapter
from registry_test_utils import delete_tree

TEST_HIVE = winreg.HKEY_CURRENT_USER
TEST_BASE = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts"
TEST_KEY = "FileAssocManagerTest.zzz"
# ProgID 测试产生的键也一并清理
PROGID_TEST_KEY = r"Software\Classes\FAM.famtestapp"
DEF_TEST_PROGID = r"Software\Classes\FAMdeftest"
CLASSES_TEST_KEY = rf"Software\Classes\.{TEST_KEY}"


@pytest.fixture(autouse=True)
def clean_test_key():
    for path in (
        f"{TEST_BASE}\\{TEST_KEY}",
        CLASSES_TEST_KEY,
        PROGID_TEST_KEY,
        DEF_TEST_PROGID,
    ):
        delete_tree(TEST_HIVE, path)
    yield
    for path in (
        f"{TEST_BASE}\\{TEST_KEY}",
        CLASSES_TEST_KEY,
        PROGID_TEST_KEY,
        DEF_TEST_PROGID,
    ):
        delete_tree(TEST_HIVE, path)


class TestRealFlow:
    def test_backup_remove_restore_cycle(self, tmp_path):
        reg = WinRegAdapter()
        backup = BackupManager(data_dir=tmp_path)

        # 造脏数据：OpenWithList 里塞一个幽灵程序
        path = f"{TEST_KEY}\\OpenWithList"
        reg.set_value(ViewKey.USER_FILE_EXTS, path, "a", "ghostapp.exe")

        # 删除：备份先行
        op = remove_open_with_entry(reg, backup, TEST_KEY, "ghostapp.exe")
        assert op is not None
        assert "a" not in reg.read_values(ViewKey.USER_FILE_EXTS, path)
        assert list((tmp_path / "backups").glob("*.reg"))

        # 恢复：值回到原位置
        backup.restore(reg, op)
        assert reg.read_values(ViewKey.USER_FILE_EXTS, path)["a"] == "ghostapp.exe"

    def test_remove_missing_entry_is_safe(self, tmp_path):
        reg = WinRegAdapter()
        backup = BackupManager(data_dir=tmp_path)
        assert remove_open_with_entry(reg, backup, TEST_KEY, "nothing.exe") is None
        assert len(backup.list_operations()) == 0


class TestRealProgIdFlow:
    def test_register_and_unregister_cycle(self, tmp_path):
        reg = WinRegAdapter()
        manager = ProgIdManager(reg, BackupManager(data_dir=tmp_path))
        exe = tmp_path / "famtestapp.exe"
        exe.write_bytes(b"")

        managed = manager.register(
            ".FileAssocManagerTest.zzz", str(exe)
        )
        assert (
            reg.read_default(ViewKey.USER_CLASSES, ".FileAssocManagerTest.zzz")
            == "FAM.famtestapp"
        )
        assert (
            reg.read_default(
                ViewKey.USER_CLASSES, r"FAM.famtestapp\shell\open\command"
            )
            == f'"{exe}" "%1"'
        )

        manager.unregister(managed.prog_id)
        assert (
            reg.read_default(ViewKey.USER_CLASSES, ".FileAssocManagerTest.zzz")
            is None
        )
        assert reg.read_default(ViewKey.USER_CLASSES, "FAM.famtestapp") is None
        assert manager.list_managed() == []


class TestRealDefinitionFlow:
    def test_clean_and_restore_invalid_user_definition(self, tmp_path):
        """真实注册表：造失效定义 → 清理默认值 → 键树保留 → 恢复。"""
        reg = WinRegAdapter()
        backup = BackupManager(data_dir=tmp_path)
        ext = ".FileAssocManagerTest.zzz"
        reg.set_value(ViewKey.USER_CLASSES, ext, None, "FAMdeftest")
        reg.set_value(
            ViewKey.USER_CLASSES,
            r"FAMdeftest\shell\open\command",
            None,
            '"C:\\gone\\app.exe" "%1"',
        )

        record = Association(
            extension=ext,
            source=rf"HKCU\Software\Classes\{ext}",
            view=RegistryView.USER,
            prog_id="FAMdeftest",
            command=None,
            target_path=None,
            status=Status.INVALID,
        )
        op = remove_user_class_definition(reg, backup, record)
        assert op is not None
        assert reg.read_default(ViewKey.USER_CLASSES, ext) is None
        # ProgID 键树保留（只删指针）
        assert (
            reg.read_default(ViewKey.USER_CLASSES, r"FAMdeftest\shell\open\command")
            == '"C:\\gone\\app.exe" "%1"'
        )

        backup.restore(reg, op)
        assert reg.read_default(ViewKey.USER_CLASSES, ext) == "FAMdeftest"

    def test_clean_valid_definition_is_rejected_on_real_registry(self, tmp_path):
        """真实注册表上的拒绝路径：状态不是失效必须抛异常。"""
        reg = WinRegAdapter()
        backup = BackupManager(data_dir=tmp_path)
        record = Association(
            extension=".FileAssocManagerTest.zzz",
            source=r"HKCU\Software\Classes\.FileAssocManagerTest.zzz",
            view=RegistryView.USER,
            prog_id="FAMdeftest",
            command=None,
            target_path=None,
            status=Status.VALID,
        )
        with pytest.raises(ValueError):
            remove_user_class_definition(reg, backup, record)
        assert backup.list_operations() == []
