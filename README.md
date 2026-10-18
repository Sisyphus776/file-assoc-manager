# 文件关联管家 / FileAssocManager

给被“右键 → 打开方式里一堆幽灵程序”困扰的 Windows 用户，也是给需要给绿色软件挂关联、又不想手改注册表的人。**只诊断和清理，不替换你的默认应用。**

For Windows users tired of ghost entries in "Open with", and for anyone who wants to associate portable apps without editing the registry by hand. **It diagnoses and cleans up — it does not hijack your default apps.**

---

## 中文

### 这是什么，不是什么

它扫描当前用户和系统两处的文件关联定义，把每条关联判成「有效 / 失效 / 无法判断」，让你看清右键菜单里那些打不开的条目从哪来，并在确认后逐条清理。任何一次删除都先落快照，可以恢复。

它**不是**默认应用替换器：不会伪造 `UserChoice` 校验，也不会强改系统级 `HKLM` 关联。想把 PDF 设成默认程序，仍然要走 Windows 设置。

### 能做什么

- 查看扩展名、ProgID、打开命令和解析出的程序路径；
- 把关联分为 `有效 / 失效 / 无法判断`，每条「无法判断」都给出原因；
- 判定失效时，若在同一安装目录下找到同名程序，给出「疑似新路径」提示（不改变失效判定）；
- 清理失效的「打开方式」残留：`OpenWithList` 条目、`OpenWithProgids` 条目、用户级失效关联定义；
- 每次修改前自动备份（`.reg` 快照 + JSON 操作日志），支持按条恢复；
- 为便携软件注册 `FAM.*` ProgID，撤销时还原注册前的默认值。

### 不能做什么

- 绕过 Windows 默认应用保护（`UserChoice`）—— 只读展示，不伪造哈希；
- 写入系统级 `HKLM` 关联 —— 系统级数据只读；
- 删除有效的打开方式条目 —— 只有判定为「失效」的条目才能勾选清理；
- 联网、云同步、规则订阅、目录加密。

### 三类结果怎么判

| 状态 | 判据 |
|---|---|
| 有效 | 从打开命令解析出绝对路径，且该文件确实存在 |
| 失效 | ProgID 键在三个视图都不存在；或解析出的程序文件不存在；或程序名不在 App Paths / PATH 中 |
| 无法判断 | UWP 应用、`DelegateExecute` 系统组件托管、ProgID 存在但没有打开命令、命令本身只是占位符 |

「无法判断」不等于「失效」，这类条目不可清理 —— 删了也会被系统重建。

### 清理边界

- 只删单个注册表值，不删键、不删 ProgID 键树；
- 只操作 `HKCU`；`HKLM` 全程只读；
- 删除 `OpenWithList` 条目时会同步剔除 `MRUList` 中的对应字母，避免悬挂引用；
- 每一条都可恢复，恢复是按条写回原值（含原始值类型）。

### 数据与备份

| 项 | 位置 |
|---|---|
| 操作日志 | `%APPDATA%\FileAssocManager\operations.json` |
| 值快照 | `%APPDATA%\FileAssocManager\backups\*.reg` |
| 台账 | `%APPDATA%\FileAssocManager\managed.json` |

- 操作日志**只保留最近 500 次**，超出的最老记录会连同其 `.reg` 快照一起删除；
- **便携模式**：若 `FileAssocManager.exe` 同目录下存在 `data\` 文件夹，则改用该目录存数据（拷走整个文件夹即可带走全部记录）；没有该目录时使用 `%APPDATA%`。

### 安全模型

- 不联网，不收集任何文件名、路径或注册表内容；
- 不需要管理员权限（只写 `HKCU`），发布包不含提权清单；
- 备份 + 操作日志 + 可恢复；注册表没有跨键事务，因此不宣称“事务性”；
- 高风险操作会列出每条明细（扩展名、键位置、目标程序）再让你确认。

### 当前状态

v0.4.0 已发布：只读扫描、失效检测、选择性清理（仅失效条目）、备份恢复、本工具创建的关联管理、中英双语 tkinter GUI、PyInstaller 便携包。发布包与 SHA-256 见 [Releases](../../releases)。

v0.4.0 的新增：

- 失效条目会尝试在同一安装目录下按文件名再找一层（最多 3 层），命中时在「疑似新路径」列给出提示；
- 扫描页新增「疑似新路径」列，行详情窗口同步展示；
- 判定结果不变，仍是「有效 / 失效 / 无法判断」三分类，提示只作参考。

v0.3.2 的改动：

- 表格列宽固定并加宽（路径列 280 → 560），水平滚动条现在真正可用；
- 双击任意行弹出「行详情」，完整路径与命令可直接查看、复制；
- 备份页与「我的关联」页的列宽同步调整。

v0.3.1 相对 v0.3.0 的修复：

- 占位符命令（如 `"%1" %*`）不再被误判为失效，改为「无法判断」；
- 识别安装器误写入的 `reg query` 文本（`(Default) REG_SZ ...`）并正确解析出路径；
- 备份页与「我的关联」页的勾选改用稳定键，列表刷新后不会作用到别的条目；
- 同一 ProgID 挂多个扩展名时各记一条台账，撤销其中一个不会留下悬空指针；
- ProgID 键不存在判为失效，键存在但没有打开命令判为无法判断；
- 注册关联时校验扩展名合法性（拒绝空值、路径分隔符与 `..`）；
- 操作日志只保留最近 500 条，并支持在 exe 同级放 `data/` 目录启用便携模式。

### 构建与测试

```bash
# 测试（需先按 CLAUDE.md 准备 .venv-win）
./.venv-win/Scripts/python.exe -m pytest

# 构建与打包
pwsh.exe -NoProfile -File build.ps1
```

---

## English

### What it is, and what it is not

It scans file association definitions for the current user and for the system, classifies every entry as **valid / invalid / unknown**, shows where the dead "Open with" entries come from, and cleans them up individually after you confirm. Every removal is snapshotted first and can be restored.

It is **not** a default-app replacer: it does not forge the `UserChoice` hash and does not touch system-level `HKLM` associations. Setting PDF as your default still goes through Windows Settings.

### Features

- Inspect extensions, ProgIDs, open commands and the resolved executable path;
- Classify every association as valid / invalid / unknown, with a stated reason for each unknown;
- When a path is missing, look for the same executable inside the same install folder and show a "suggested path" hint (the entry stays invalid);
- Clean invalid "Open with" leftovers: `OpenWithList` entries, `OpenWithProgids` entries, and invalid user-level association definitions;
- Back up before every change (`.reg` snapshot + JSON operation log) and restore any single item;
- Register `FAM.*` ProgIDs for portable apps, restoring the previous default on undo.

### Non-goals

- Bypassing Windows default-app protection (`UserChoice`) — read-only display, no forged hashes;
- Writing system-level `HKLM` associations — read-only;
- Removing valid "Open with" entries — only entries judged invalid can be cleaned;
- Networking, cloud sync, rule subscriptions, folder encryption.

### How classification works

| Status | Rule |
|---|---|
| valid | An absolute path is resolved from the open command and the file exists |
| invalid | The ProgID key is absent from all three views, or the resolved executable is missing, or the bare program name is not found via App Paths / PATH |
| unknown | UWP apps, `DelegateExecute` system handlers, ProgIDs without an open command, or commands that are only a placeholder |

Unknown is not invalid: such entries cannot be cleaned, and deleting them would only let Windows recreate them.

### Cleanup boundaries

- Deletes individual values only — never keys or ProgID trees;
- Writes to `HKCU` only; `HKLM` is read-only throughout;
- Removing an `OpenWithList` entry also strips the corresponding letter from `MRUList`;
- Every removal is restorable, preserving the original value type.

### Data and backups

| Item | Location |
|---|---|
| Operation log | `%APPDATA%\FileAssocManager\operations.json` |
| Value snapshots | `%APPDATA%\FileAssocManager\backups\*.reg` |
| Managed ProgID ledger | `%APPDATA%\FileAssocManager\managed.json` |

- The operation log **keeps the most recent 500 entries**; older records and their `.reg` snapshots are pruned;
- **Portable mode**: if a `data\` folder exists next to `FileAssocManager.exe`, it is used instead (copy the whole folder to carry all records); otherwise `%APPDATA%` is used.

### Security model

- Offline; collects no file names, paths or registry contents;
- No administrator rights required (HKCU only), no elevation manifest in the build;
- Backup + operation log + restore; registry has no cross-key transactions, so this is not advertised as transactional;
- Destructive operations list every affected item (extension, key location, target program) before you confirm.

### Status

v0.4.0 is released: read-only scanning, broken-association detection, selective cleanup (invalid entries only), backup & restore, managed associations for portable apps, bilingual tkinter GUI, PyInstaller portable build. See [Releases](../../releases) for downloads and SHA-256.

New in v0.4.0:

- Invalid entries now get a "suggested path" hint when the same executable is found inside the same install folder (up to 3 levels deep);
- The scan page has a dedicated column for it, and the row-details window shows it too;
- The classification stays valid / invalid / unknown — the hint is informational only.

Changes in v0.3.2:

- Column widths are fixed and wider (path column 280 → 560), so the horizontal scrollbar finally works;
- Double-click any row to open a details window with the full path and command, ready to copy;
- The backup and managed pages got the same width treatment.

Fixes in v0.3.1 over v0.3.0:

- Placeholder commands (e.g. `"%1" %*`) are no longer reported as invalid;
- Installer-written `reg query` text (`(Default) REG_SZ ...`) is stripped before parsing;
- Checkbox state on the backup and managed pages uses stable keys, so a rebuilt list no longer applies an action to a different row;
- One ProgID can back several extensions without leaving dangling pointers on undo;
- A missing ProgID key is invalid; a ProgID without an open command is unknown;
- Extension input is validated on registration (no empty values, path separators or `..`);
- The operation log keeps the latest 500 entries, and portable mode is enabled by a `data/` folder next to the executable.

### Build & Test

```bash
# Test (prepare .venv-win first, see CLAUDE.md)
./.venv-win/Scripts/python.exe -m pytest

# Build & package
pwsh.exe -NoProfile -File build.ps1
```

---

详细设计见 [`docs/design.md`](docs/design.md)。Detailed design: [`docs/design.md`](docs/design.md) (Chinese).
