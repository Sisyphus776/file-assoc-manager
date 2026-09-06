"""ProgID 管理器测试：注册、重复注册、撤销、恢复原默认值。"""

import pytest

from file_assoc_manager.backup import BackupManager
from file_assoc_manager.managed_progid import ProgIdManager
from file_assoc_manager.registry import ViewKey

from mock_registry import MockRegistryAdapter, mock_key


def make_manager(tmp_path):
    reg = MockRegistryAdapter(
        {
            ViewKey.USER_CLASSES: mock_key(
                subkeys={".txt": mock_key(default="txtfile")}
            )
        }
    )
    return reg, ProgIdManager(reg, BackupManager(data_dir=tmp_path))


class TestRegister:
    def test_creates_command_and_default(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        managed = manager.register(".md", "D:\\apps\\markdown.exe")

        assert managed.prog_id == "FAM.markdown"
        assert (
            reg.read_default(
                ViewKey.USER_CLASSES, "FAM.markdown\\shell\\open\\command"
            )
            == '"D:\\apps\\markdown.exe" "%1"'
        )
        assert reg.read_default(ViewKey.USER_CLASSES, ".md") == "FAM.markdown"

    def test_extension_is_normalized(self, tmp_path):
        _, manager = make_manager(tmp_path)
        assert manager.register("log", "C:\\x\\viewer.exe").extension == ".log"

    def test_previous_default_is_backed_up(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        manager.register(".txt", "D:\\apps\\editor.exe")

        # .txt 原有默认值 txtfile，注册前必须备份
        operations = manager.backup.list_operations()
        assert len(operations) == 1
        assert operations[0].key_path == ".txt"
        assert operations[0].value_name is None
        assert operations[0].value_data == "txtfile"

    def test_no_previous_default_no_backup(self, tmp_path):
        _, manager = make_manager(tmp_path)
        manager.register(".log", "C:\\x\\viewer.exe")
        assert manager.backup.list_operations() == []

    def test_reregister_keeps_original_previous_default(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        manager.register(".txt", "D:\\apps\\editor.exe")
        # 重复注册：当前默认值已是 FAM.editor，不能把它当"原默认值"
        manager.register(".txt", "D:\\apps\\editor.exe")
        records = manager.list_managed()
        assert len(records) == 1
        assert records[0].previous_default == "txtfile"


class TestUnregister:
    def test_restores_previous_default_and_removes_key(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        managed = manager.register(".txt", "D:\\apps\\editor.exe")

        manager.unregister(managed.prog_id)
        assert reg.read_default(ViewKey.USER_CLASSES, ".txt") == "txtfile"
        assert reg.list_subkeys(ViewKey.USER_CLASSES, "FAM.editor") == []
        assert manager.list_managed() == []

    def test_extension_without_previous_default_is_cleared(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        managed = manager.register(".log", "C:\\x\\viewer.exe")

        manager.unregister(managed.prog_id)
        assert reg.read_default(ViewKey.USER_CLASSES, ".log") is None

    def test_unregister_unknown_progid_raises(self, tmp_path):
        _, manager = make_manager(tmp_path)
        with pytest.raises(ValueError):
            manager.unregister("FAM.never_registered")

    def test_unregister_plain_progid_raises(self, tmp_path):
        """不是本工具管理记录的 ProgID（即使带 FAM. 前缀）也不能删。"""
        _, manager = make_manager(tmp_path)
        with pytest.raises(ValueError):
            manager.unregister("txtfile")


class TestSanitizeStem:
    def test_stem_from_path(self, tmp_path):
        _, manager = make_manager(tmp_path)
        managed = manager.register(".x", "C:\\my apps\\wéird nàme!.exe")
        assert managed.prog_id.startswith("FAM.")
        # 非法字符被替换，ProgID 安全
        assert all(c.isalnum() or c in "_.-" for c in managed.prog_id[4:])
