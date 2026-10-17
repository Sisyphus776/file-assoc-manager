"""扫描器测试：FileExts 枚举、Classes 枚举、WOW64 双视图。"""

from file_assoc_manager.models import RegistryView, Status
from file_assoc_manager.registry import ViewKey
from file_assoc_manager.scanner import scan

from mock_registry import MockRegistryAdapter, mock_key


def make_file_exts(**extensions):
    """构造 FileExts 树，每个扩展名参数为 MockKey。"""
    return mock_key(subkeys=extensions)


class TestFileExts:
    def test_user_choice_record(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_FILE_EXTS: make_file_exts(
                    **{
                        ".txt": mock_key(
                            subkeys={
                                "UserChoice": mock_key(values={"ProgId": "txtfile", "Hash": "abc"})
                            }
                        )
                    }
                )
            }
        )
        records = scan(reg)
        assert len(records) == 1
        r = records[0]
        assert r.extension == ".txt"
        assert r.prog_id == "txtfile"
        assert r.view == RegistryView.USER
        assert r.source.endswith(r"FileExts\.txt\UserChoice")

    def test_open_with_list_skips_mrulist_and_empty(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_FILE_EXTS: make_file_exts(
                    **{
                        ".txt": mock_key(
                            subkeys={
                                "OpenWithList": mock_key(
                                    values={"a": "notepad.exe", "b": "", "MRUList": "a"}
                                )
                            }
                        )
                    }
                )
            }
        )
        records = scan(reg)
        assert len(records) == 1
        assert records[0].command == "notepad.exe"
        assert records[0].prog_id is None

    def test_open_with_progids_records_each_progid(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_FILE_EXTS: make_file_exts(
                    **{
                        ".txt": mock_key(
                            subkeys={
                                "OpenWithProgids": mock_key(values={"txtfile": "", "other": ""})
                            }
                        )
                    }
                )
            }
        )
        records = scan(reg)
        assert {r.prog_id for r in records} == {"txtfile", "other"}

    def test_extension_without_choice_or_lists_yields_no_record(self):
        reg = MockRegistryAdapter(
            {ViewKey.USER_FILE_EXTS: make_file_exts(**{".txt": mock_key()})}
        )
        assert scan(reg) == []


class TestClasses:
    def test_only_extension_keys_are_scanned(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={
                        ".txt": mock_key(default="txtfile"),
                        "txtfile": mock_key(default=None),
                    }
                )
            }
        )
        records = scan(reg)
        assert len(records) == 1
        assert records[0].extension == ".txt"
        assert records[0].prog_id == "txtfile"
        assert records[0].source == r"HKCU\Software\Classes\.txt"

    def test_extension_without_default_value(self):
        reg = MockRegistryAdapter({ViewKey.USER_CLASSES: mock_key(subkeys={".xyz": mock_key()})})
        records = scan(reg)
        assert len(records) == 1
        assert records[0].prog_id is None

    def test_system_view_without_default_is_skipped(self):
        """系统视图中无默认值的扩展名键只是注册占位，不产生记录。"""
        reg = MockRegistryAdapter(
            {
                ViewKey.SYSTEM_CLASSES_64: mock_key(subkeys={".xyz": mock_key()}),
                ViewKey.SYSTEM_CLASSES_32: mock_key(subkeys={".xyz": mock_key()}),
            }
        )
        assert scan(reg) == []

    def test_user_view_without_default_is_kept(self):
        """用户级无默认值仍保留（可能是问题迹象）。"""
        reg = MockRegistryAdapter(
            {ViewKey.USER_CLASSES: mock_key(subkeys={".xyz": mock_key()})}
        )
        records = scan(reg)
        assert len(records) == 1


class TestWow64DualView:
    def test_same_extension_in_both_views_yields_two_records(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.SYSTEM_CLASSES_64: mock_key(subkeys={".pdf": mock_key(default="pdf64")}),
                ViewKey.SYSTEM_CLASSES_32: mock_key(subkeys={".pdf": mock_key(default="pdf32")}),
            }
        )
        records = scan(reg)
        assert len(records) == 2
        by_view = {r.view: r for r in records}
        assert by_view[RegistryView.SYSTEM_64].prog_id == "pdf64"
        assert by_view[RegistryView.SYSTEM_32].prog_id == "pdf32"

    def test_extension_in_one_view_only(self):
        reg = MockRegistryAdapter(
            {ViewKey.SYSTEM_CLASSES_32: mock_key(subkeys={".legacy": mock_key(default="oldprog")})}
        )
        records = scan(reg)
        assert len(records) == 1
        assert records[0].view == RegistryView.SYSTEM_32
        assert records[0].source == r"HKLM\Software\Classes\.legacy"

    def test_records_are_not_merged_across_sources(self):
        """FileExts 的 OpenWithProgids 与 Classes 默认值指向同一 ProgID
        时也必须是两条记录：来源不同，语义不同。"""
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_FILE_EXTS: make_file_exts(
                    **{
                        ".txt": mock_key(
                            subkeys={"OpenWithProgids": mock_key(values={"txtfile": ""})}
                        )
                    }
                ),
                ViewKey.USER_CLASSES: mock_key(subkeys={".txt": mock_key(default="txtfile")}),
            }
        )
        records = scan(reg)
        assert len(records) == 2
        assert all(r.status == Status.UNKNOWN for r in records)
