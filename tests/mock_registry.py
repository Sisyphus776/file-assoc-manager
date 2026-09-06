"""内存版注册表适配层，测试专用（见 CLAUDE.md 测试策略）。"""

from dataclasses import dataclass, field

from file_assoc_manager.registry import RegistryAdapter, ViewKey, _assert_writable


@dataclass
class MockKey:
    subkeys: dict[str, "MockKey"] = field(default_factory=dict)
    values: dict[str, str] = field(default_factory=dict)
    default: str | None = None


def mock_key(default=None, values=None, subkeys=None):
    """便捷构造：mock_key(default="txtfile", subkeys={"shell": ...})。"""
    return MockKey(default=default, values=values or {}, subkeys=subkeys or {})


class MockRegistryAdapter(RegistryAdapter):
    """每个 ViewKey 一棵独立树，未设置的视图视为不存在。"""

    def __init__(self, trees: dict[ViewKey, MockKey] | None = None):
        self.trees = trees or {}

    def _lookup(self, view: ViewKey, path: str) -> MockKey | None:
        root = self.trees.get(view)
        if root is None:
            return None
        node = root
        if not path:
            return node
        for part in path.split("\\"):
            node = node.subkeys.get(part)
            if node is None:
                return None
        return node

    def list_subkeys(self, view: ViewKey, path: str) -> list[str]:
        node = self._lookup(view, path)
        return list(node.subkeys) if node else []

    def read_default(self, view: ViewKey, path: str) -> str | None:
        node = self._lookup(view, path)
        return node.default if node else None

    def read_values(self, view: ViewKey, path: str) -> dict[str, str]:
        node = self._lookup(view, path)
        return dict(node.values) if node else {}

    def _ensure(self, view: ViewKey, path: str) -> MockKey:
        """创建（或返回已有的）path 节点链。"""
        _assert_writable(view)
        if view not in self.trees:
            self.trees[view] = MockKey()
        node = self.trees[view]
        for part in path.split("\\"):
            node = node.subkeys.setdefault(part, MockKey())
        return node

    def set_value(
        self, view: ViewKey, path: str, name: str | None, value: str
    ) -> None:
        node = self._ensure(view, path)
        if name is None:
            node.default = value
        else:
            node.values[name] = value

    def delete_value(
        self, view: ViewKey, path: str, name: str | None
    ) -> None:
        _assert_writable(view)
        node = self._lookup(view, path)
        if node:
            if name is None:
                node.default = None
            else:
                node.values.pop(name, None)

    def delete_key(self, view: ViewKey, path: str) -> None:
        _assert_writable(view)
        root = self.trees.get(view)
        if root is None or not path:
            return
        parts = path.split("\\")
        parent = self._lookup(view, "\\".join(parts[:-1]))
        if parent:
            parent.subkeys.pop(parts[-1], None)
