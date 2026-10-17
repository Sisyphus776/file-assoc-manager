# 文件关联管家第一版设计

## 1. 产品边界

工具以“诊断和可恢复维护”为核心，而不是强制接管 Windows 默认应用。所有自动修改限定在当前用户注册表范围，并在修改前创建备份。

## 2. 数据来源

主要读取位置：

- `HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\FileExts\\<extension>`：用户的打开方式、用户选择和关联历史；
- `HKCU\\Software\\Classes\\<ProgID>`：当前用户的 ProgID 定义；
- 系统级 `HKLM\Software\Classes`（64 位与 32 位视图）：第一版只读，用于补充解析命令。不使用 `HKCR`，因为它是合并视图，会把 `HKCU\Software\Classes` 的内容混入"系统级"结果。

## 3. 扫描模型

每条关联记录至少包含：

- 扩展名；
- 来源位置（用户级或系统级）；
- ProgID 或应用程序名；
- 解析后的打开命令；
- 目标程序路径（如果可解析）；
- 状态：`valid`、`invalid`、`unknown`；
- 无法判断时的原因。

解析命令字符串时有三类典型“不确定”场景不判为 `invalid`：
1. `ProgID` 键本身已不存在——这是真残留，判 `invalid`；
2. `ProgID` 键存在但无 `shell\open\command`（如 `DelegateExecute` 现代应用、或 shell 托管的 `exefile`）——判 `unknown`；
3. 命令被安装器误写入 `reg query` 的文本前缀（如 `(Default)    REG_SZ    "D:\..."`）——先剥离前缀再解析。

`OpenWithList` 中的值可能只是 `notepad.exe` 这样的文件名，必须通过 `Applications\\<exe>\\shell\\open\\command`、App Paths、PATH 等来源解析后再判断，不能直接对原始字符串调用文件存在检查。

## 4. 修改与恢复

清理流程：

1. 用户选择具体条目；
2. 读取并保存待修改键和值；
3. 写出 `.reg` 备份和 JSON 操作日志；
4. 执行最小范围的删除或更新；
5. 刷新 Shell，并重新扫描确认结果；
6. 提供按操作恢复的入口。

注册表没有跨键事务，因此对外表述为“备份 + 操作日志 + 可恢复”，不称为严格事务。

## 5. 默认应用限制

Windows 10/11 的 `UserChoice` 包含系统校验信息。工具不直接伪造或绕过该校验；当用户需要改变系统默认应用时，提供跳转 Windows 设置的入口，并区分“关联定义已更新”和“系统默认应用已确认”两种状态。

## 6. 实现顺序

1. 只读注册表适配层和扫描数据模型；
2. ProgID、命令行和程序路径解析；
3. 隔离测试；
4. 备份/恢复；
5. 选择性清理；
6. tkinter GUI；
7. PyInstaller 便携包和 Windows 10/11 实机验证。

## 7. 安全与隐私

- 默认不联网；
- 不收集文件名、路径或注册表内容；
- 不把真实注册表导出文件纳入版本库；
- 对高风险操作显示明确的扩展名、键路径和目标程序。
