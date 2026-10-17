# 构建脚本（入库）：设置 Tcl/Tk 数据源后执行 PyInstaller
#
# .venv-win 是 venv，没有 Anaconda 的 Library\tcl 数据；
# 不设 TCL_LIBRARY/TK_LIBRARY 时 PyInstaller 会 fallback 搜到系统里
# 其他 Tcl（如 msys64 8.6.15），与 tkinter 期望的 8.6.13 冲突，
# 打包结果启动即崩溃。
$ErrorActionPreference = 'Stop'

$root = 'D:\AgentWorkPlace\code\file-assoc-manager'
$python = "$root\.venv-win\Scripts\python.exe"

# 从 venv 的 base_prefix 动态定位 Anaconda 环境的 Tcl/Tk 数据目录，
# 避免硬编码绝对路径（换机器时只要 venv 可解析即可）。
$basePrefix = & $python -c "import sys; print(sys.base_prefix)"
$tclLib = Join-Path $basePrefix 'Library\lib\tcl8.6'
$tkLib = Join-Path $basePrefix 'Library\lib\tk8.6'
if (-not (Test-Path $tclLib)) { throw "tcl not found: $tclLib" }
if (-not (Test-Path $tkLib)) { throw "tk not found: $tkLib" }

$env:TCL_LIBRARY = $tclLib
$env:TK_LIBRARY = $tkLib

& $python -m PyInstaller --clean --noconfirm FileAssocManager.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

# 打包分发 zip：README/LICENSE 复制进构建目录，压缩并生成 SHA-256。
# 版本号从 pyproject.toml 读取，与包元数据保持单一事实源。
$pyproject = Get-Content "$root\pyproject.toml" -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "version not found in pyproject.toml"
}
$version = $Matches[1]
$appDir = "$root\dist\FileAssocManager"
Copy-Item "$root\README.txt", "$root\LICENSE" -Destination $appDir -Force
$zipPath = "$root\dist\FileAssocManager-v$version-win-x64.zip"
Compress-Archive -Path "$appDir" -DestinationPath $zipPath -Force
$hash = (Get-FileHash $zipPath -Algorithm SHA256).Hash.ToLower()
Set-Content -Path "$zipPath.sha256" -Value "$hash  FileAssocManager-v$version-win-x64.zip" -Encoding ascii
Write-Output "BUILD OK"
Write-Output "zip: $zipPath"
Write-Output "sha256: $hash"
