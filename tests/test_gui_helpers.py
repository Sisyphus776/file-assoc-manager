"""GUI 中可测的纯逻辑：清理资格判断、扩展名选项构建、当前默认查询。"""

from file_assoc_manager.gui import (
    build_all_extensions,
    can_clean,
    current_default_of,
    source_kind,
)
from file_assoc_manager.models import Association, RegistryView, Status

USER = RegistryView.USER


def rec(
    extension=".txt",
    source="",
    prog_id=None,
    command=None,
    target_path=None,
    status=Status.UNKNOWN,
    view=USER,
):
    return Association(
        extension=extension,
        source=source,
        view=view,
        prog_id=prog_id,
        command=command,
        target_path=target_path,
        status=status,
    )


class TestSourceKind:
    def test_open_with_list(self):
        record = rec(source=r"HKCU\...\FileExts\.txt\OpenWithList", command="n.exe")
        assert source_kind(record) == "Open with leftovers"

    def test_open_with_progids(self):
        record = rec(
            source=r"HKCU\...\FileExts\.txt\OpenWithProgids", prog_id="txtfile"
        )
        assert source_kind(record) == "Open with ProgIDs"

    def test_user_choice(self):
        record = rec(source=r"HKCU\...\FileExts\.txt\UserChoice", prog_id="txtfile")
        assert source_kind(record) == "System default"

    def test_user_classes(self):
        record = rec(source=r"HKCU\Software\Classes\.txt", prog_id="txtfile")
        assert source_kind(record) == "User association"

    def test_system_64(self):
        record = rec(source=r"HKCR\.txt", view=RegistryView.SYSTEM_64)
        assert source_kind(record) == "System association (64-bit)"

    def test_system_32(self):
        record = rec(source=r"HKCR\.txt", view=RegistryView.SYSTEM_32)
        assert source_kind(record) == "System association (32-bit)"


class TestCanClean:
    def test_open_with_list_is_cleanable(self):
        record = rec(
            source=r"HKCU\...\FileExts\.txt\OpenWithList", command="notepad.exe"
        )
        assert can_clean(record)

    def test_open_with_list_without_command_is_not(self):
        record = rec(source=r"HKCU\...\FileExts\.txt\OpenWithList", command=None)
        assert not can_clean(record)

    def test_open_with_progids_is_cleanable(self):
        record = rec(
            source=r"HKCU\...\FileExts\.txt\OpenWithProgids", prog_id="ghostprog"
        )
        assert can_clean(record)

    def test_user_choice_is_not_cleanable(self):
        record = rec(source=r"HKCU\...\FileExts\.txt\UserChoice", prog_id="txtfile")
        assert not can_clean(record)

    def test_classes_definition_is_not_cleanable(self):
        record = rec(source=r"HKCU\Software\Classes\.txt", prog_id="txtfile")
        assert not can_clean(record)

    def test_invalid_user_definition_is_cleanable(self):
        record = rec(
            source=r"HKCU\Software\Classes\.apk",
            prog_id="Androws.apk",
            status=Status.INVALID,
        )
        assert can_clean(record)

    def test_valid_user_definition_is_not_cleanable(self):
        record = rec(
            source=r"HKCU\Software\Classes\.txt",
            prog_id="txtfile",
            status=Status.VALID,
        )
        assert not can_clean(record)

    def test_unknown_user_definition_is_not_cleanable(self):
        record = rec(
            source=r"HKCU\Software\Classes\.bin",
            prog_id="binfile",
            status=Status.UNKNOWN,
        )
        assert not can_clean(record)

    def test_invalid_system_definition_is_not_cleanable(self):
        record = rec(
            source=r"HKCR\.apk",
            prog_id="Androws.apk",
            status=Status.INVALID,
            view=RegistryView.SYSTEM_64,
        )
        assert not can_clean(record)


class TestBuildAllExtensions:
    def test_dedup_case_insensitive_and_sorted(self):
        records = [rec(extension=".txt"), rec(extension=".TXT"), rec(extension=".apk")]
        assert build_all_extensions(records) == [".apk", ".txt"]


class TestCurrentDefault:
    def test_returns_progid_when_no_target(self):
        records = [
            rec(source=r"HKCU\...\FileExts\.txt\UserChoice", prog_id="txtfile"),
        ]
        assert current_default_of(records, ".txt") == "txtfile"

    def test_returns_target_path_when_available(self):
        records = [
            rec(source=r"HKCU\...\FileExts\.txt\UserChoice", prog_id="txtfile"),
            rec(source=r"HKCU\Software\Classes\txtfile", prog_id="txtfile",
                target_path=r"C:\Windows\notepad.exe"),
        ]
        assert current_default_of(records, ".txt") == r"C:\Windows\notepad.exe"

    def test_returns_none_without_user_choice(self):
        records = [rec(source=r"HKCU\Software\Classes\.txt", prog_id="txtfile")]
        assert current_default_of(records, ".txt") is None

    def test_case_insensitive_lookup(self):
        records = [
            rec(source=r"HKCU\...\FileExts\.TXT\UserChoice", prog_id="txtfile"),
        ]
        assert current_default_of(records, ".txt") == "txtfile"
