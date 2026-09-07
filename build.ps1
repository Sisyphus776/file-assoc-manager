# 构建脚本（入库）：设置 Tcl/Tk 数据源后执行 PyInstaller
#
# .venv-win 是 venv，没有 Anaconda 的 Library\tcl 数据；
# 不设 TCL_LIBRARY/TK_LIBRARY 时 PyInstaller 会 fallback 搜到系统里
# 其他 Tcl（如 msys64 8.6.15），与 tkinter 期望的 8.6.13 冲突，
# 打包结果启动即崩溃。
$ErrorActionPreference = 'Stop'

$tclLib = 'D:\Anaconda\envs\py313\Library\lib\tcl8.6'
$tkLib = 'D:\Anaconda\envs\py313\Library\lib\tk8.6'
if (-not (Test-Path $tclLib)) { throw "tcl not found: $tclLib" }
if (-not (Test-Path $tkLib)) { throw "tk not found: $tkLib" }

$env:TCL_LIBRARY = $tclLib
$env:TK_LIBRARY = $tkLib

& 'D:\AgentWorkPlace\code\file-assoc-manager\.venv-win\Scripts\python.exe' `
    -m PyInstaller --clean --noconfirm FileAssocManager.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

# 打包分发 zip：README/LICENSE 复制进构建目录，压缩并生成 SHA-256。
# 版本号与 pyproject.toml 保持一致，升级时两处同步改。
$version = '0.2.1'
$root = 'D:\AgentWorkPlace\code\file-assoc-manager'
$appDir = "$root\dist\FileAssocManager"
Copy-Item "$root\README.txt", "$root\LICENSE" -Destination $appDir -Force
$zipPath = "$root\dist\FileAssocManager-v$version-win-x64.zip"
Compress-Archive -Path "$appDir" -DestinationPath $zipPath -Force
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$zipPath.sha256" -Value "$hash  FileAssocManager-v$version-win-x64.zip" -Encoding ascii
Write-Output "BUILD OK"
Write-Output "zip: $zipPath"
Write-Output "sha256: $hash"
