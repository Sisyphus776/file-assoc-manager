"""清理器测试：备份先行、值名定位、未找到时零操作。"""

from file_assoc_manager.backup import BackupManager
from file_assoc_manager.cleaner import remove_open_with_entry, remove_open_with_progid
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
        assert values == {"a": "notepad.exe", "MRUList": "ba"}
        # 备份先行：.reg 快照与日志都已生成
        assert len(backup.list_operations()) == 1

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
