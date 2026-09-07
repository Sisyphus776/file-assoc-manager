"""解析器测试：命令解析、解析链优先级、状态分类。"""

import os

from file_assoc_manager.models import Association, RegistryView, Status
from file_assoc_manager.registry import ViewKey
from file_assoc_manager.resolver import resolve

from mock_registry import MockRegistryAdapter, mock_key

USER = RegistryView.USER


def make_record(**kwargs):
    defaults = dict(
        extension=".txt",
        source="test",
        view=USER,
        prog_id=None,
        command=None,
        target_path=None,
        status=Status.UNKNOWN,
    )
    defaults.update(kwargs)
    return Association(**defaults)


def classes_tree(prog_id, command):
    """构造含 ProgID 打开命令的 Classes 树。"""
    return {
        prog_id: mock_key(
            subkeys={
                "shell": mock_key(
                    subkeys={"open": mock_key(subkeys={"command": mock_key(default=command)})}
                )
            }
        )
    }


class TestOpenCommandResolution:
    def test_user_classes_takes_priority(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(subkeys=classes_tree("prog1", '"C:\\user\\app.exe" "%1"')),
                ViewKey.SYSTEM_CLASSES_64: mock_key(subkeys=classes_tree("prog1", '"C:\\sys\\app.exe" "%1"')),
            }
        )
        record = make_record(prog_id="prog1")
        resolve(record, reg)
        assert record.command == '"C:\\user\\app.exe" "%1"'

    def test_falls_back_to_system_64(self):
        reg = MockRegistryAdapter(
            {ViewKey.SYSTEM_CLASSES_64: mock_key(subkeys=classes_tree("prog1", "C:\\sys64\\app.exe %1"))}
        )
        record = make_record(prog_id="prog1")
        resolve(record, reg)
        assert record.command == "C:\\sys64\\app.exe %1"

    def test_falls_back_to_system_32(self):
        reg = MockRegistryAdapter(
            {ViewKey.SYSTEM_CLASSES_32: mock_key(subkeys=classes_tree("prog1", '"C:\\sys32\\app.exe"'))}
        )
        record = make_record(prog_id="prog1")
        resolve(record, reg)
        assert record.command == '"C:\\sys32\\app.exe"'

    def test_missing_progid_becomes_unknown(self):
        record = make_record(prog_id="noprogress")
        resolve(record, MockRegistryAdapter())
        assert record.status == Status.UNKNOWN
        assert record.command is None


class TestExtractProgramPath:
    def test_quoted_path_with_args(self):
        record = make_record(prog_id="p", command=None)
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys=classes_tree("p", '"C:\\Program Files\\App\\app.exe" "%1" /x')
                )
            }
        )
        resolve(record, reg)
        assert record.target_path == "C:\\Program Files\\App\\app.exe"
        assert record.status == Status.INVALID  # 该路径不存在，但路径提取正确

    def test_unquoted_path(self):
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {ViewKey.USER_CLASSES: mock_key(subkeys=classes_tree("p", "C:\\win\\app.exe %1"))}
        )
        resolve(record, reg)
        assert record.target_path == "C:\\win\\app.exe"

    def test_unquoted_path_with_spaces_existing(self, tmp_path):
        """无引号且含空格：逐 token 拼接找到真实文件。"""
        exe = tmp_path / "Program Files" / "App" / "app.exe"
        exe.parent.mkdir(parents=True)
        exe.write_bytes(b"")
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys=classes_tree("p", f"{exe} --from x")
                )
            }
        )
        resolve(record, reg)
        assert record.target_path == str(exe)
        assert record.status == Status.VALID

    def test_unquoted_path_with_spaces_uninstalled(self):
        """路径不存在（程序已卸载）也要完整提取，不能截断到第一个空格。"""
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys=classes_tree(
                        "p",
                        'D:\\Program Files\\Tencent\\Androws\\AndrowsLauncher.exe '
                        '--from "13"',
                    )
                )
            }
        )
        resolve(record, reg)
        assert (
            record.target_path
            == "D:\\Program Files\\Tencent\\Androws\\AndrowsLauncher.exe"
        )
        assert record.status == Status.INVALID

    def test_env_var_expansion(self, monkeypatch):
        monkeypatch.setenv("TEST_APP_DIR", "C:\\envdir")
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys=classes_tree("p", '"%TEST_APP_DIR%\\app.exe" "%1"')
                )
            }
        )
        resolve(record, reg)
        assert record.target_path == "C:\\envdir\\app.exe"


class TestStatusClassification:
    def test_existing_file_is_valid(self, tmp_path):
        exe = tmp_path / "app.exe"
        exe.write_bytes(b"")
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {ViewKey.USER_CLASSES: mock_key(subkeys=classes_tree("p", f'"{exe}" "%1"'))}
        )
        resolve(record, reg)
        assert record.status == Status.VALID
        assert record.target_path == str(exe)

    def test_missing_file_is_invalid(self):
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys=classes_tree("p", '"C:\\definitely\\missing.exe" "%1"')
                )
            }
        )
        resolve(record, reg)
        assert record.status == Status.INVALID
        assert "not found" in record.reason

    def test_bare_name_resolved_via_app_paths(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(subkeys=classes_tree("p", "myapp.exe %1")),
                ViewKey.SYSTEM_APP_PATHS_64: mock_key(
                    subkeys={"myapp.exe": mock_key(default="C:\\tools\\myapp.exe")}
                ),
            }
        )
        record = make_record(prog_id="p")
        resolve(record, reg)
        assert record.status == Status.VALID
        assert record.target_path == "C:\\tools\\myapp.exe"

    def test_bare_name_resolved_via_path(self, tmp_path, monkeypatch):
        fake = tmp_path / "fakeapp.exe"
        fake.write_bytes(b"")
        monkeypatch.setenv("PATH", str(tmp_path))
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {ViewKey.USER_CLASSES: mock_key(subkeys=classes_tree("p", "fakeapp.exe %1"))}
        )
        resolve(record, reg)
        assert record.status == Status.VALID
        assert record.target_path == str(fake)

    def test_unresolvable_bare_name_is_invalid(self, monkeypatch):
        monkeypatch.setenv("PATH", "")
        record = make_record(prog_id="p")
        reg = MockRegistryAdapter(
            {ViewKey.USER_CLASSES: mock_key(subkeys=classes_tree("p", "ghostapp.exe %1"))}
        )
        resolve(record, reg)
        assert record.status == Status.INVALID


class TestModernApps:
    def test_delegate_execute_progid_is_unknown(self):
        """UWP ProgID：shell\\open\\command 只有 DelegateExecute 值，无命令。"""
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={
                        "AppX123": mock_key(
                            subkeys={
                                "shell": mock_key(
                                    subkeys={
                                        "open": mock_key(
                                            subkeys={
                                                "command": mock_key(
                                                    values={"DelegateExecute": "{GUID}"}
                                                )
                                            }
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
            }
        )
        record = make_record(prog_id="AppX123")
        resolve(record, reg)
        assert record.status == Status.UNKNOWN
        assert "DelegateExecute" in record.reason

    def test_app_user_model_id_is_unknown_not_invalid(self):
        """OpenWithList 里的 AppUserModelID（含 ! 的包名）不是文件路径。"""
        record = make_record(
            prog_id=None, command="Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"
        )
        resolve(record, MockRegistryAdapter())
        assert record.status == Status.UNKNOWN
        assert "UWP" in record.reason


class TestOpenWithListEntry:
    def test_applications_key_takes_priority(self):
        reg = MockRegistryAdapter(
            {
                ViewKey.USER_CLASSES: mock_key(
                    subkeys={
                        "Applications": mock_key(
                            subkeys={
                                "oldapp.exe": mock_key(
                                    subkeys={
                                        "shell": mock_key(
                                            subkeys={
                                                "open": mock_key(
                                                    subkeys={
                                                        "command": mock_key(
                                                            default='"C:\\old\\oldapp.exe" "%1"'
                                                        )
                                                    }
                                                )
                                            }
                                        )
                                    }
                                )
                            }
                        )
                    }
                )
            }
        )
        record = make_record(prog_id=None, command="oldapp.exe")
        resolve(record, reg)
        # command 保持原始裸名（清理器按它定位），解析结果只在 target_path
        assert record.command == "oldapp.exe"
        assert record.target_path == "C:\\old\\oldapp.exe"
        assert record.status == Status.INVALID  # 路径不存在

    def test_no_applications_key_keeps_bare_name(self, tmp_path, monkeypatch):
        fake = tmp_path / "portable.exe"
        fake.write_bytes(b"")
        monkeypatch.setenv("PATH", str(tmp_path))
        record = make_record(prog_id=None, command="portable.exe")
        resolve(record, MockRegistryAdapter())
        assert record.status == Status.VALID
        assert record.target_path == str(fake)
