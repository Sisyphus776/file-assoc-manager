"""国际化：代码内以英文为 key，按当前语言取译文。

语言来源优先级：配置文件 config.json > 系统 UI 语言检测（中文系 → zh，
其他 → en）。检测在 Windows 上走 GetUserDefaultUILanguage。
"""

import ctypes
import json
import os
from pathlib import Path

LANGUAGES = {"zh": "中文", "en": "English"}
DEFAULT_LANGUAGE = "zh"

# 中文译文表；en 时 key 即译文，无需表。
ZH_TABLE: dict[str, str] = {
    # 窗口与通用
    "File Association Manager": "文件关联管家",
    # 标签页
    "Scan Results": "扫描结果",
    "Backup & Restore": "备份与恢复",
    "My Associations": "我的关联",
    # 扫描页
    "Filter:": "筛选:",
    "All": "全部",
    "Invalid": "失效",
    "Unknown": "无法判断",
    "Valid": "有效",
    "Rescan": "重新扫描",
    "Scanning...": "扫描中...",
    "Scan failed": "扫描失败",
    "{count} records": "{count} 条记录",
    "Clean checked items": "清理勾选条目",
    "Select All": "全选",
    "Clear": "清空",
    "Only 'Open With' leftovers can be cleaned; system definitions and UserChoice are read-only.": (
        "仅「打开方式残留」类条目可清理；系统定义与 UserChoice 只读展示"
    ),
    # 扫描页表头与状态
    "Extension": "扩展名",
    "Source": "来源",
    "Status": "状态",
    "ProgID": "ProgID",
    "Program Path": "程序路径",
    "Note": "说明",
    "User level": "用户级",
    "System 64-bit": "系统64位",
    "System 32-bit": "系统32位",
    # 备份恢复页
    "Restore checked items": "恢复勾选条目",
    "Operation log: {path}": "操作记录来自 {path}",
    "Time": "时间",
    "Key Path": "键路径",
    "Value Name": "值名",
    "Value Data": "值内容",
    "(default value)": "(默认值)",
    # 我的关联页
    "Extension:": "扩展名:",
    "Pick format...": "选择格式...",
    "Program path:": "程序路径:",
    "Browse...": "浏览...",
    "Register association": "注册关联",
    "Previous default": "注册前默认值",
    "Unregister checked": "撤销勾选关联",
    "Undo restores the previous default and removes the tool-created ProgID.": (
        "撤销会恢复注册前的默认值并删除本工具创建的 ProgID"
    ),
    "(none)": "(无)",
    # 格式选择器
    "Select file format": "选择文件格式",
    "Search:": "搜索:",
    "Name": "名称",
    "OK": "确定",
    "Cancel": "取消",
    "{ext} current default: not set": "{ext} 当前默认：未设置",
    "{ext} current default: {program}": "{ext} 当前默认：{program}",
    # 弹窗文案
    "Please check items first.": "请先勾选条目。",
    "Please check the items to clean first.": "请先勾选要清理的条目",
    "Please check the operation records to restore first.": "请先勾选要恢复的操作记录",
    "Please check the associations to unregister first.": "请先勾选要撤销的关联",
    "None of the checked items can be cleaned (only 'Open With' leftovers).": (
        "勾选的条目都不属于可清理的来源（仅「打开方式残留」可清理）"
    ),
    "Confirm Cleanup": "确认清理",
    "Will clean {clean} item(s), skip {skip} item(s) that cannot be cleaned.\n"
    "Each item is backed up before removal and can be restored anytime.\n\nProceed?": (
        "将清理 {clean} 条，跳过 {skip} 条（不可清理的来源）。\n"
        "每条清理前自动备份，可随时恢复。\n\n确认执行？"
    ),
    "Cleanup partially failed": "部分清理失败",
    "Cleanup complete": "清理完成",
    "Cleaned {count} item(s).": "已清理 {count} 条",
    "Cleanup failed": "清理失败",
    "Confirm Restore": "确认恢复",
    "Will restore {count} operation record(s) (writing values back).\n\nProceed?": (
        "将恢复 {count} 条操作记录（把值写回原位置）。\n\n确认执行？"
    ),
    "Restore failed": "恢复失败",
    "Restore complete": "恢复完成",
    "Restored {count} item(s).": "已恢复 {count} 条",
    "Confirm Unregister": "确认撤销",
    "Will unregister {count} association(s) (restoring previous defaults).\n\nProceed?": (
        "将撤销 {count} 条关联（恢复注册前的默认值）。\n\n确认执行？"
    ),
    "Unregister failed": "撤销失败",
    "Unregister complete": "撤销完成",
    "Unregistered {count} association(s).": "已撤销 {count} 条关联",
    "Please fill in the extension and program path (or use 'Pick format...').": (
        "请填写扩展名和程序路径（可点「选择格式...」）"
    ),
    "Register failed": "注册失败",
    "Select program": "选择程序",
    "Executables": "可执行程序",
    "All files": "所有文件",
    # 语言切换
    "Language:": "语言:",
    # reason 整句（resolver 生成英文，中文界面翻译）
    "No usable program path in open command.": "打开命令无法解析出程序路径",
    "Handled by a system component (DelegateExecute), cannot check file path.": (
        "由系统组件处理（DelegateExecute），无法按文件路径判断"
    ),
    "UWP app, cannot check file path.": "UWP 应用，无法按文件路径判断",
    # 格式分组与常见格式名（选择器用）
    "Documents": "文档",
    "Images": "图片",
    "Audio": "音频",
    "Video": "视频",
    "Archives": "压缩",
    "Code & Web": "代码与网页",
    "Word Document": "Word 文档",
    "Word 97-2003": "Word 97-2003",
    "PDF Document": "PDF 文档",
    "Plain Text": "纯文本",
    "Markdown": "Markdown",
    "Excel Spreadsheet": "Excel 表格",
    "PowerPoint Presentation": "PowerPoint 演示",
    "CSV Table": "CSV 表格",
    "RTF Document": "RTF 文档",
    "JPEG Image": "JPEG 图片",
    "PNG Image": "PNG 图片",
    "GIF Image": "GIF 图片",
    "BMP Image": "BMP 图片",
    "SVG Vector": "SVG 矢量图",
    "WebP Image": "WebP 图片",
    "ICO Icon": "ICO 图标",
    "TIFF Image": "TIFF 图片",
    "MP3 Audio": "MP3 音频",
    "WAV Audio": "WAV 音频",
    "FLAC Lossless Audio": "FLAC 无损音频",
    "AAC Audio": "AAC 音频",
    "M4A Audio": "M4A 音频",
    "OGG Audio": "OGG 音频",
    "MP4 Video": "MP4 视频",
    "MKV Video": "MKV 视频",
    "AVI Video": "AVI 视频",
    "MOV Video": "MOV 视频",
    "WMV Video": "WMV 视频",
    "FLV Video": "FLV 视频",
    "WebM Video": "WebM 视频",
    "ZIP Archive": "ZIP 压缩包",
    "RAR Archive": "RAR 压缩包",
    "7Z Archive": "7Z 压缩包",
    "TAR Archive": "TAR 归档",
    "GZ Archive": "GZ 压缩",
    "Python Script": "Python 脚本",
    "C Source File": "C 源文件",
    "Java Source File": "Java 源文件",
    "JSON Data": "JSON 数据",
    "XML Document": "XML 文档",
    "HTML Page": "HTML 网页",
    "CSS Stylesheet": "CSS 样式",
    "JavaScript": "JavaScript",
    "SQL Script": "SQL 脚本",
}

# 带参数 reason 的前缀翻译（完整句见 ZH_TABLE）
_REASON_PREFIXES_ZH = {
    "Program file not found: ": "程序文件不存在: ",
    "Program not found or not in PATH: ": "程序不存在或不在 PATH 中: ",
}

_current_language = DEFAULT_LANGUAGE


def get_language() -> str:
    return _current_language


def set_language(language: str) -> None:
    global _current_language
    if language in LANGUAGES:
        _current_language = language


def t(key: str, **kwargs) -> str:
    """取译文；en 时返回 key 本身，zh 时查表。支持 {name} 占位。"""
    text = ZH_TABLE.get(key, key) if _current_language == "zh" else key
    if kwargs:
        text = text.format(**kwargs)
    return text


def detect_language_from_id(language_id: int) -> str:
    """按 Windows 语言 ID 判断：主语言码 0x04 表示中文系
    （0x0804 简体 / 0x0C04 繁体 / 0x1004 新加坡）。"""
    return "zh" if (language_id & 0xFF) == 0x04 else "en"


def detect_language() -> str:
    """按系统 UI 语言检测：中文系 → zh，其他 → en。"""
    try:
        language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except Exception:
        return DEFAULT_LANGUAGE
    return detect_language_from_id(language_id)


def load_language(config_path: Path) -> str:
    """启动时确定语言：配置文件 > 系统检测。"""
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if data.get("language") in LANGUAGES:
                return data["language"]
        except (json.JSONDecodeError, OSError):
            pass
    return detect_language()


def save_language(config_path: Path, language: str) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps({"language": language}), encoding="utf-8"
    )


def translate_reason(reason: str) -> str:
    """reason 是 resolver 生成的英文原文；中文界面按前缀/整句翻译，
    未知文案保持原样。"""
    if _current_language == "en" or not reason:
        return reason
    translated = ZH_TABLE.get(reason)
    if translated is not None:
        return translated
    for prefix, zh_prefix in _REASON_PREFIXES_ZH.items():
        if reason.startswith(prefix):
            return zh_prefix + reason[len(prefix):]
    return reason
