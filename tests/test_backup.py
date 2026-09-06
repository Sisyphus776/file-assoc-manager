"""备份管理器测试：.reg 快照内容、JSON 日志、恢复、视图限制。"""

import json

import pytest

from file_assoc_manager.backup import BackupManager
from file_assoc_manager.registry import ViewKey

from mock_registry import MockRegistryAdapter

EXPECTED_HEAD = "Windows Registry Editor Version 5.00\r\n\r\n"


def make_backup(tmp_path):
    return BackupManager(data_dir=tmp_path)


class TestRegSnapshot:
    def test_snapshot_content(self, tmp_path):
        backup = make_backup(tmp_path)
        op = backup.record_removal(
            ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList", "a", "notepad.exe", ".txt"
        )
        content = open(op.backup_file, encoding="utf-16", newline="").read()
        assert content == (
            EXPECTED_HEAD
            + r"[HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion"
            + r"\Explorer\FileExts\.txt\OpenWithList]"
            + "\r\n"
            + '"a"="notepad.exe"\r\n'
        )

    def test_snapshot_escapes_quotes_and_backslashes(self, tmp_path):
        backup = make_backup(tmp_path)
        op = backup.record_removal(
            ViewKey.USER_CLASSES, "prog\\shell\\open\\command", "b", '"C:\\app\\x.exe"'
        )
        content = open(op.backup_file, encoding="utf-16", newline="").read()
        assert '"b"="\\"C:\\\\app\\\\x.exe\\""\r\n' in content

    def test_system_view_is_rejected(self, tmp_path):
        backup = make_backup(tmp_path)
        with pytest.raises(ValueError):
            backup.record_removal(ViewKey.SYSTEM_CLASSES_64, ".x", "a", "v")

    def test_snapshot_is_utf16_with_bom(self, tmp_path):
        backup = make_backup(tmp_path)
        op = backup.record_removal(
            ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList", "a", "notepad.exe"
        )
        raw = open(op.backup_file, "rb").read(4)
        assert raw[:2] in (b"\xff\xfe",)  # UTF-16 LE BOM


class TestOperationLog:
    def test_log_appends_and_lists_newest_first(self, tmp_path):
        backup = make_backup(tmp_path)
        backup.record_removal(
            ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList", "a", "notepad.exe"
        )
        backup.record_removal(
            ViewKey.USER_FILE_EXTS, ".md\\OpenWithList", "a", "oldapp.exe", ".md"
        )
        operations = backup.list_operations()
        assert len(operations) == 2
        assert operations[0].value_data == "oldapp.exe"  # 倒序，新的在前

    def test_log_fields_roundtrip(self, tmp_path):
        backup = make_backup(tmp_path)
        backup.record_removal(
            ViewKey.USER_FILE_EXTS, ".txt\\OpenWithProgids", "txtfile", "", ".txt"
        )
        op = backup.list_operations()[0]
        assert op.extension == ".txt"
        assert op.view == ViewKey.USER_FILE_EXTS.value
        assert op.key_path == ".txt\\OpenWithProgids"
        assert op.value_name == "txtfile"
        assert op.value_data == ""

    def test_corrupt_log_returns_empty(self, tmp_path):
        backup = make_backup(tmp_path)
        backup.data_dir.mkdir(parents=True, exist_ok=True)
        backup.log_path.write_text("{broken", encoding="utf-8")
        assert backup.list_operations() == []


class TestRestore:
    def test_restore_writes_value_back(self, tmp_path):
        reg = MockRegistryAdapter()
        reg.set_value(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList", "x", "keep")
        backup = make_backup(tmp_path)
        op = backup.record_removal(
            ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList", "a", "notepad.exe"
        )
        reg.delete_value(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList", "a")
        assert "a" not in reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList")

        backup.restore(reg, op)
        values = reg.read_values(ViewKey.USER_FILE_EXTS, ".txt\\OpenWithList")
        assert values["a"] == "notepad.exe"
        assert values["x"] == "keep"


class TestDataDir:
    def test_default_uses_appdata(self, monkeypatch, tmp_path):
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert str(BackupManager().data_dir) == str(tmp_path / "FileAssocManager")
