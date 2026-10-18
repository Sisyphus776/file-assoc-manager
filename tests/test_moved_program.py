"""疑似路径变更提示（suggested_path）的测试。"""

from file_assoc_manager.models import Association, RegistryView, Status
from file_assoc_manager.registry import ViewKey
from file_assoc_manager.resolver import resolve

from mock_registry import MockRegistryAdapter, mock_key


def tree_with_command(command):
    """构造一个只在 64 位系统视图里定义了打开命令的 ProgID。"""
    return {
        ViewKey.SYSTEM_CLASSES_64: mock_key(
            subkeys={
                "Test.Prog": mock_key(
                    subkeys={
                        "shell": mock_key(
                            subkeys={
                                "open": mock_key(
                                    subkeys={"command": mock_key(default=command)}
                                )
                            }
                        )
                    }
                )
            }
        )
    }


def resolve_command(command):
    record = Association(
        extension=".txt",
        source="test",
        view=RegistryView.USER,
        prog_id="Test.Prog",
        command=None,
        target_path=None,
        status=Status.UNKNOWN,
    )
    resolve(record, MockRegistryAdapter(tree_with_command(command)))
    return record


def test_finds_program_moved_into_version_dir(tmp_path):
    install = tmp_path / "QQMusic"
    version = install / "QQMusic2271.14.13.06"
    version.mkdir(parents=True)
    moved = version / "QQMusic.exe"
    moved.write_bytes(b"")

    old = install / "QQMusic.exe"          # 不存在
    record = resolve_command(f'"{old}" "%1"')

    assert record.status == Status.INVALID
    assert record.target_path == str(old)
    assert record.suggested_path == str(moved)
    assert "Program file not found" in record.reason


def test_no_hint_when_nothing_found(tmp_path):
    install = tmp_path / "App"
    install.mkdir()
    (install / "other.exe").write_bytes(b"")

    record = resolve_command(f'"{install / "missing.exe"}" "%1"')
    assert record.status == Status.INVALID
    assert record.suggested_path is None


def test_no_hint_when_parent_dir_missing(tmp_path):
    ghost = tmp_path / "not-installed" / "app.exe"
    record = resolve_command(f'"{ghost}" "%1"')
    assert record.status == Status.INVALID
    assert record.suggested_path is None


def test_valid_record_carries_no_hint(tmp_path):
    exe = tmp_path / "app.exe"
    exe.write_bytes(b"")
    record = resolve_command(f'"{exe}" "%1"')
    assert record.status == Status.VALID
    assert record.suggested_path is None


def test_hint_respects_depth_limit(tmp_path):
    """超过下探深度（3 层）不再提示，避免过慢或过度猜测。"""
    deep = tmp_path / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    (deep / "target.exe").write_bytes(b"")

    record = resolve_command(f'"{tmp_path / "target.exe"}" "%1"')
    assert record.status == Status.INVALID
    assert record.suggested_path is None
