# 文件关联管家（FileAssocManager）— Claude Code 工作规范

项目定位、目标与非目标见 README.md 与 docs/design.md；通用开发约束沿用 AGENTS.md（默认只读、只写 HKCU、备份先行、不绕过 UserChoice）。本文件只补充 Claude Code 环境下新增的决策。

## 环境约定

- 唯一验证环境：项目内 `.venv-win/`（由 `D:\Anaconda\envs\py313` = Python 3.13.14 创建，64 位）。
- 全部测试在 WSL 里通过 interop 调用 Windows Python 运行（winreg 是真实模块）：
  ```bash
  cd /mnt/d/AgentWorkPlace/code/file-assoc-manager && ./.venv-win/Scripts/python.exe -m pytest
  ```
- 不要改动 WSL 系统 Python（无 pip/venv），不要在 WSL 侧安装 Python 包。
- `.venv-win/`、构建产物、真实注册表导出文件、`work/` 不入库。
- 构建与打包一体化（含 Tcl/Tk 数据源修复与 zip+SHA-256 生成）：
  ```bash
  pwsh.exe -NoProfile -File 'D:\AgentWorkPlace\code\file-assoc-manager\build.ps1'
  ```
  版本号单一事实源是 pyproject.toml，build.ps1 自动读取。

## 新增技术决策

1. **WOW64 双视图（第一阶段就实现）**：注册表适配层统一收口所有打开系统级键的调用，显式传 `KEY_WOW64_64KEY` / `KEY_WOW64_32KEY`，禁止依赖 winreg 默认视图；系统级视图固定用 `HKLM\Software\Classes` 双视图（不能用 `HKCR`——它是合并视图，会把 `HKCU\Software\Classes` 的内容混入"系统级"结果）。数据模型必须带 `registry_view` 字段（用户级/64位/32位）。
2. **不复用「文件默认大师」（qianli-wang/default-app）的代码**：其核心是删除并伪造 UserChoice 哈希，踩本项目红线，且其哈希算法无效。仅借鉴其「规则 JSON + PATH 扫描匹配」思路。
3. **分发与误报**（打包阶段执行，决策现在固定）：one-folder；禁用 UPX；无管理员清单（工具只写 HKCU，不请求提权）；zip 附 SHA-256；README 写 Defender 白名单步骤；构建产物不上传 VirusTotal；代码签名第一版不做（EV 证书成本高，必要时再议）。
4. **GUI 验证由用户实机操作**，Claude 不做界面视觉验证。

## 测试策略

- 纯逻辑测试：mock 注册表适配层，构造双视图注册表树，验证合并与状态分类。
- 真实适配层测试：只读写 `HKCU\Software\FileAssocManagerTest` 测试子键，测试结束清理；绝不读改真实用户关联数据。
- 每条关联记录状态三分类：valid / invalid / unknown（unknown 必须给出原因）。

## 开发顺序

按 docs/design.md 第 6 节：只读适配层与扫描模型 → 解析器 → 测试 → 备份/恢复 → 选择性清理 → GUI → 打包。
