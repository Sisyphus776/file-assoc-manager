"""真实适配层测试：只在 HKCU\\Software\\Classes 下的假扩展名键
FileAssocManagerTest.zzz 上读写，测试结束删除，绝不触碰真实关联数据。
"""

import winreg

import pytest

from file_assoc_manager.registry import ViewKey, WinRegAdapter
from registry_test_utils import delete_tree

TEST_HIVE = winreg.HKEY_CURRENT_USER
TEST_BASE = r"Software\Classes"
TEST_KEY = "FileAssocManagerTest.zzz"


@pytest.fixture(autouse=True)
def clean_test_key():
    delete_tree(TEST_HIVE, f"{TEST_BASE}\\{TEST_KEY}")  # 清理上次残留
    yield
    delete_tree(TEST_HIVE, f"{TEST_BASE}\\{TEST_KEY}")  # 清理本次写入


def _create_sample():
    key = winreg.CreateKey(TEST_HIVE, f"{TEST_BASE}\\{TEST_KEY}")
    winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "testprog")
    winreg.SetValueEx(key, "ProgId", 0, winreg.REG_SZ, "testprog2")
    winreg.SetValueEx(key, "Empty", 0, winreg.REG_NONE, b"")
    sub = winreg.CreateKey(key, r"shell\open\command")
    winreg.SetValueEx(sub, None, 0, winreg.REG_SZ, 'C:\\fake\\app.exe "%1"')
    sub.Close()
    key.Close()


class TestWinRegAdapter:
    def test_read_and_list_roundtrip(self):
        _create_sample()
        reg = WinRegAdapter()
        assert reg.read_default(ViewKey.USER_CLASSES, TEST_KEY) == "testprog"
        assert reg.read_values(ViewKey.USER_CLASSES, TEST_KEY) == {
            "ProgId": "testprog2",
            "Empty": "",
        }
        assert reg.list_subkeys(ViewKey.USER_CLASSES, TEST_KEY) == ["shell"]
        assert (
            reg.read_default(ViewKey.USER_CLASSES, rf"{TEST_KEY}\shell\open\command")
            == 'C:\\fake\\app.exe "%1"'
        )

    def test_missing_key_returns_empty(self):
        reg = WinRegAdapter()
        assert reg.read_default(ViewKey.USER_CLASSES, "NoSuchKey.zzz") is None
        assert reg.read_values(ViewKey.USER_CLASSES, "NoSuchKey.zzz") == {}
        assert reg.list_subkeys(ViewKey.USER_CLASSES, "NoSuchKey.zzz") == []

    def test_key_without_default_value(self):
        """真实注册表：键存在但无默认值时 QueryValueEx(None) 抛
        FileNotFoundError，适配层必须归一为 None。"""
        key = winreg.CreateKey(TEST_HIVE, f"{TEST_BASE}\\{TEST_KEY}")
        winreg.SetValueEx(key, "Only", 0, winreg.REG_SZ, "v")
        key.Close()
        reg = WinRegAdapter()
        assert reg.read_default(ViewKey.USER_CLASSES, TEST_KEY) is None
        assert reg.read_values(ViewKey.USER_CLASSES, TEST_KEY) == {"Only": "v"}

    def test_system_views_do_not_see_user_classes(self):
        """系统级视图基于 HKLM\\Software\\Classes（而非合并视图 HKCR），
        HKCU\\Software\\Classes 的内容不得出现在系统视图——验证视图隔离。"""
        _create_sample()
        reg = WinRegAdapter()
        assert reg.read_default(ViewKey.SYSTEM_CLASSES_64, TEST_KEY) is None
        assert reg.read_default(ViewKey.SYSTEM_CLASSES_32, TEST_KEY) is None
        # 用户级视图仍然可读
        assert reg.read_default(ViewKey.USER_CLASSES, TEST_KEY) == "testprog"


class TestWriteMethods:
    def test_set_value_roundtrip(self):
        reg = WinRegAdapter()
        reg.set_value(ViewKey.USER_CLASSES, TEST_KEY, "ProgId", "testprog")
        assert reg.read_values(ViewKey.USER_CLASSES, TEST_KEY) == {"ProgId": "testprog"}

    def test_set_default_value(self):
        reg = WinRegAdapter()
        reg.set_value(ViewKey.USER_CLASSES, TEST_KEY, None, "defprog")
        assert reg.read_default(ViewKey.USER_CLASSES, TEST_KEY) == "defprog"

    def test_delete_value(self):
        reg = WinRegAdapter()
        reg.set_value(ViewKey.USER_CLASSES, TEST_KEY, "Temp", "v")
        reg.delete_value(ViewKey.USER_CLASSES, TEST_KEY, "Temp")
        assert reg.read_values(ViewKey.USER_CLASSES, TEST_KEY) == {}

    def test_delete_missing_value_is_silent(self):
        reg = WinRegAdapter()
        reg.delete_value(ViewKey.USER_CLASSES, TEST_KEY, "NeverExisted")  # 不抛异常

    def test_delete_key_after_emptying(self):
        reg = WinRegAdapter()
        reg.set_value(ViewKey.USER_CLASSES, rf"{TEST_KEY}\Sub", "x", "v")
        reg.delete_value(ViewKey.USER_CLASSES, rf"{TEST_KEY}\Sub", "x")
        reg.delete_key(ViewKey.USER_CLASSES, rf"{TEST_KEY}\Sub")
        assert reg.list_subkeys(ViewKey.USER_CLASSES, TEST_KEY) == []

    def test_typed_roundtrip_preserves_type(self):
        """带类型写入后，read_values_typed 能取回原始 winreg 类型。"""
        reg = WinRegAdapter()
        reg.set_value(ViewKey.USER_CLASSES, TEST_KEY, "Dw", "42",
                      value_type=winreg.REG_DWORD)
        reg.set_value(ViewKey.USER_CLASSES, TEST_KEY, "Sz", "hello")
        typed = reg.read_values_typed(ViewKey.USER_CLASSES, TEST_KEY)
        assert typed["Dw"] == ("42", winreg.REG_DWORD)
        assert typed["Sz"] == ("hello", winreg.REG_SZ)
        # 便捷接口行为不变
        assert reg.read_values(ViewKey.USER_CLASSES, TEST_KEY) == {
            "Dw": "42",
            "Sz": "hello",
        }

    def test_system_view_write_is_rejected(self):
        """写入系统级视图必须被硬性拒绝，这是项目的核心安全红线。"""
        reg = WinRegAdapter()
        with pytest.raises(ValueError):
            reg.set_value(ViewKey.SYSTEM_CLASSES_64, "NoTouch", "a", "v")
        with pytest.raises(ValueError):
            reg.delete_value(ViewKey.SYSTEM_CLASSES_64, "NoTouch", "a")
        with pytest.raises(ValueError):
            reg.delete_key(ViewKey.SYSTEM_CLASSES_64, "NoTouch")
