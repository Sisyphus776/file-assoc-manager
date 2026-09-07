# 文件关联管家 / FileAssocManager

面向 Windows 10/11 的便携式文件关联查看与维护工具。无联网、无安装、只操作当前用户设置、任何修改可备份可恢复。

A portable file association manager for Windows 10/11. Offline, no installation, HKCU-only, and every change is backed up and recoverable.

---

## 中文

### 当前阶段

已完成 v0.3.0：只读扫描、失效检测、选择性清理（打开方式残留 + 失效的用户关联定义）、备份恢复、本工具创建的关联管理、中英双语 tkinter GUI（可切换）、PyInstaller 便携包。发布包见 [Releases](../../releases)。

### 目标

- 查看当前用户的扩展名、ProgID 和打开命令；
- 识别明确失效、有效和无法判断的关联；
- 在用户确认后选择性清理打开方式残留；
- 修改前自动备份，并支持恢复；
- 管理由本工具创建的 ProgID（为便携软件注册关联）。

### 非目标

- 绕过 Windows 默认应用保护；
- 自动修改系统级 `HKLM` 关联；
- 在线规则空间、云同步、目录加密等附加功能；
- 保证 PDF 等受保护格式可以被静默设为默认程序。

### 构建与测试

```bash
# 测试（需先按 CLAUDE.md 准备 .venv-win）
./.venv-win/Scripts/python.exe -m pytest

# 构建与打包
pwsh.exe -NoProfile -File build.ps1
```

---

## English

### Status

v0.3.0 released: read-only scanning, broken-association detection, selective cleanup (open-with leftovers + invalid user association definitions), backup & restore, managed ProgIDs for portable apps, bilingual (Chinese/English) tkinter GUI, PyInstaller portable build. See [Releases](../../releases) for downloads.

### Goals

- Inspect the current user's extensions, ProgIDs and open commands;
- Classify associations as valid / invalid / unknown;
- Selectively clean "Open With" leftovers after user confirmation;
- Back up before every change, with one-click restore;
- Register associations for portable apps via tool-managed ProgIDs.

### Non-goals

- Bypassing Windows default-app protection (UserChoice);
- Writing system-level `HKLM` associations;
- Online rule sharing, cloud sync, folder encryption;
- Silently setting protected formats (e.g. PDF) as default.

### Build & Test

```bash
# Test (prepare .venv-win first, see CLAUDE.md)
./.venv-win/Scripts/python.exe -m pytest

# Build & package
pwsh.exe -NoProfile -File build.ps1
```

---

详细设计见 [`docs/design.md`](docs/design.md)。Detailed design: [`docs/design.md`](docs/design.md) (Chinese).
