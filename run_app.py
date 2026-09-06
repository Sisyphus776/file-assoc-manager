"""PyInstaller 打包入口（顶层脚本）。

包内 main.py 使用相对导入，不能直接作为 PyInstaller 入口脚本；
本文件以绝对导入方式启动 GUI，仅用于打包，开发运行仍用：
python -m file_assoc_manager.main
"""

from file_assoc_manager.gui import main

if __name__ == "__main__":
    main()
