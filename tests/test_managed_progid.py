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


def make_exe(tmp_path, name="app.exe"):
    """创建真实存在的假可执行文件，返回路径字符串。"""
    exe = tmp_path / name
    exe.write_bytes(b"")
    return str(exe)


class TestRegister:
    def test_creates_command_and_default(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "markdown.exe")
        managed = manager.register(".md", exe)

        assert managed.prog_id == "FAM.markdown"
        assert (
            reg.read_default(
                ViewKey.USER_CLASSES, "FAM.markdown\\shell\\open\\command"
            )
            == f'"{exe}" "%1"'
        )
        assert reg.read_default(ViewKey.USER_CLASSES, ".md") == "FAM.markdown"

    def test_missing_program_path_is_rejected(self, tmp_path):
        _, manager = make_manager(tmp_path)
        with pytest.raises(ValueError, match="程序路径不存在"):
            manager.register(".md", str(tmp_path / "no_such.exe"))

    def test_extension_is_normalized(self, tmp_path):
        _, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "viewer.exe")
        assert manager.register("log", exe).extension == ".log"

    def test_previous_default_is_backed_up(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "editor.exe")
        manager.register(".txt", exe)

        # .txt 原有默认值 txtfile，注册前必须备份
        operations = manager.backup.list_operations()
        assert len(operations) == 1
        assert operations[0].key_path == ".txt"
        assert operations[0].value_name is None
        assert operations[0].value_data == "txtfile"

    def test_no_previous_default_no_backup(self, tmp_path):
        _, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "viewer.exe")
        manager.register(".log", exe)
        assert manager.backup.list_operations() == []

    def test_reregister_keeps_original_previous_default(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "editor.exe")
        manager.register(".txt", exe)
        # 重复注册：当前默认值已是 FAM.editor，不能把它当"原默认值"
        manager.register(".txt", exe)
        records = manager.list_managed()
        assert len(records) == 1
        assert records[0].previous_default == "txtfile"


class TestMultipleExtensions:
    """同一程序挂多个扩展名：各一条记录，各存各的原默认值。"""

    def test_two_extensions_two_records(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "player.exe")
        manager.register(".aaa", exe)
        manager.register(".bbb", exe)
        records = manager.list_managed()
        assert len(records) == 2
        assert {r.extension for r in records} == {".aaa", ".bbb"}
        assert all(r.prog_id == "FAM.player" for r in records)

    def test_unregister_one_keeps_key_tree(self, tmp_path):
        """撤掉一个扩展名后键树必须保留（另一个扩展名还在用）。"""
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "player.exe")
        m_aaa = manager.register(".aaa", exe)
        manager.register(".bbb", exe)

        manager.unregister(m_aaa.prog_id, ".aaa")
        assert reg.read_default(ViewKey.USER_CLASSES, ".aaa") is None
        assert reg.read_default(ViewKey.USER_CLASSES, ".bbb") == "FAM.player"
        # 键树仍在
        assert (
            reg.read_default(
                ViewKey.USER_CLASSES, "FAM.player\\shell\\open\\command"
            )
            is not None
        )
        assert [r.extension for r in manager.list_managed()] == [".bbb"]

    def test_unregister_last_removes_key_tree(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "player.exe")
        m = manager.register(".aaa", exe)
        manager.register(".bbb", exe)

        manager.unregister(m.prog_id, ".aaa")
        manager.unregister(m.prog_id, ".bbb")
        assert reg.list_subkeys(ViewKey.USER_CLASSES, "FAM.player") == []
        assert manager.list_managed() == []


class TestExtensionValidation:
    def test_dotdot_rejected(self, tmp_path):
        _, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path)
        with pytest.raises(ValueError):
            manager.register("..", exe)

    def test_path_separator_rejected(self, tmp_path):
        _, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path)
        with pytest.raises(ValueError):
            manager.register(r"a\b", exe)

    def test_empty_rejected(self, tmp_path):
        _, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path)
        with pytest.raises(ValueError):
            manager.register("", exe)

    def test_compound_extension_allowed(self, tmp_path):
        _, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path)
        assert manager.register(".tar.gz", exe).extension == ".tar.gz"


class TestUnregister:
    def test_restores_previous_default_and_removes_key(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "editor.exe")
        managed = manager.register(".txt", exe)

        manager.unregister(managed.prog_id)
        assert reg.read_default(ViewKey.USER_CLASSES, ".txt") == "txtfile"
        assert reg.list_subkeys(ViewKey.USER_CLASSES, "FAM.editor") == []
        assert manager.list_managed() == []

    def test_unregister_backs_up_command_and_current_default(self, tmp_path):
        """撤销前先备份 command 值与当前扩展名默认值。"""
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "editor.exe")
        managed = manager.register(".txt", exe)
        manager.unregister(managed.prog_id)

        ops = manager.backup.list_operations()
        # register 1 条（原默认值 txtfile）+ unregister 2 条（command + 当前默认）
        assert len(ops) == 3
        cmd_ops = [o for o in ops if o.key_path.endswith("shell\\open\\command")]
        assert len(cmd_ops) == 1
        assert cmd_ops[0].value_data == f'"{exe}" "%1"'
        ext_ops = [o for o in ops if o.key_path == ".txt"]
        # register 备份的 txtfile 与 unregister 备份的 FAM.editor
        assert {o.value_data for o in ext_ops} == {"txtfile", "FAM.editor"}

    def test_unregister_backup_allows_rebuild(self, tmp_path):
        """撤销后可用备份把 command 值写回，ProgID 键树随之重建。"""
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "editor.exe")
        managed = manager.register(".log", exe)
        manager.unregister(managed.prog_id)

        ops = manager.backup.list_operations()
        cmd_op = next(o for o in ops if o.key_path.endswith("shell\\open\\command"))
        manager.backup.restore(reg, cmd_op)
        assert (
            reg.read_default(
                ViewKey.USER_CLASSES, "FAM.editor\\shell\\open\\command"
            )
            == f'"{exe}" "%1"'
        )

    def test_extension_without_previous_default_is_cleared(self, tmp_path):
        reg, manager = make_manager(tmp_path)
        exe = make_exe(tmp_path, "viewer.exe")
        managed = manager.register(".log", exe)

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
        exe = make_exe(tmp_path, "wéird nàme!.exe")
        managed = manager.register(".x", exe)
        assert managed.prog_id.startswith("FAM.")
        # 非法字符被替换，ProgID 安全
        assert all(c.isalnum() or c in "_.-" for c in managed.prog_id[4:])
