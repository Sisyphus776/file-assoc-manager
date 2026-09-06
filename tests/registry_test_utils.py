"""真实注册表测试公用工具。"""

import winreg


def delete_tree(hive: int, path: str) -> None:
    """递归删除注册表键树（仅测试清理用）；不存在时静默。"""
    try:
        key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return
    with key:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(key, index)
            except OSError:
                break
            delete_tree(hive, f"{path}\\{sub}")
            index += 1
    try:
        winreg.DeleteKey(hive, path)
    except FileNotFoundError:
        pass
