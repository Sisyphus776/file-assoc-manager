# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置（入库，构建时不要用临时命令行参数）
#
# 决策见 CLAUDE.md「分发与误报」：
# - one-folder 目录包（非 one-file）
# - 禁用 UPX（加壳显著增加杀软误报率）
# - 无管理员提权清单（工具只写 HKCU，不需要管理员）
# - 无控制台窗口

import os
import sys

# venv 没有 Anaconda 的 Library 目录，PyInstaller 会顺 PATH 找到
# base 环境的 tcl86t.dll（8.6.15），与当前 Python 的 tkinter 版本
# 可能不匹配，打包结果启动即崩。这里从运行构建的解释器动态定位。
_tcl_bin = os.path.join(sys.base_prefix, "Library", "bin")

a = Analysis(
    ["run_app.py"],
    pathex=["src"],
    binaries=[
        (os.path.join(_tcl_bin, "tcl86t.dll"), "."),
        (os.path.join(_tcl_bin, "tk86t.dll"), "."),
    ],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileAssocManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FileAssocManager",
)
