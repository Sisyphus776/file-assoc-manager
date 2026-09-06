"""国际化测试：翻译表完整性、翻译函数、语言检测、配置往返。"""

import pytest

from file_assoc_manager import i18n
from file_assoc_manager.i18n import (
    ZH_TABLE,
    detect_language_from_id,
    load_language,
    save_language,
    set_language,
    t,
    translate_reason,
)


class TestTableIntegrity:
    def test_all_values_non_empty(self):
        for key, value in ZH_TABLE.items():
            assert key, "key 不能为空"
            assert value, f"缺少中文译文: {key}"

    def test_placeholders_align_between_key_and_translation(self):
        """{count} 这类占位符在 key 与译文中必须一一对应。"""
        for key, value in ZH_TABLE.items():
            key_placeholders = {p.split("}")[0] for p in key.split("{")[1:]}
            zh_placeholders = {p.split("}")[0] for p in value.split("{")[1:]}
            assert key_placeholders == zh_placeholders, f"占位符不一致: {key}"


class TestTranslate:
    def test_zh_lookup(self):
        set_language("zh")
        assert t("Rescan") == "重新扫描"

    def test_en_returns_key(self):
        set_language("en")
        assert t("Rescan") == "Rescan"

    def test_format_kwargs(self):
        set_language("zh")
        assert t("{count} records", count=5) == "5 条记录"


class TestDetect:
    @pytest.mark.parametrize("language_id", [0x0804, 0x0C04, 0x1004, 0x1404])
    def test_chinese_locales(self, language_id):
        assert detect_language_from_id(language_id) == "zh"

    @pytest.mark.parametrize("language_id", [0x0409, 0x0411, 0x0412])
    def test_other_locales(self, language_id):
        assert detect_language_from_id(language_id) == "en"


class TestReasonTranslation:
    def test_full_sentence(self):
        set_language("zh")
        assert (
            translate_reason("UWP app, cannot check file path.")
            == "UWP 应用，无法按文件路径判断"
        )

    def test_prefix_with_argument(self):
        set_language("zh")
        assert (
            translate_reason(r"Program file not found: C:\x.exe")
            == r"程序文件不存在: C:\x.exe"
        )

    def test_unknown_reason_unchanged(self):
        set_language("zh")
        assert translate_reason("Something new.") == "Something new."

    def test_en_keeps_original(self):
        set_language("en")
        assert (
            translate_reason("UWP app, cannot check file path.")
            == "UWP app, cannot check file path."
        )


class TestConfig:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "config.json"
        save_language(path, "en")
        assert load_language(path) == "en"

    def test_load_missing_file_falls_back_to_detect(self, tmp_path, monkeypatch):
        monkeypatch.setattr(i18n, "detect_language", lambda: "zh")
        assert load_language(tmp_path / "missing.json") == "zh"

    def test_load_corrupt_file_falls_back_to_detect(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        path.write_text("{broken", encoding="utf-8")
        monkeypatch.setattr(i18n, "detect_language", lambda: "zh")
        assert load_language(path) == "zh"

    def test_load_invalid_language_falls_back_to_detect(self, tmp_path, monkeypatch):
        path = tmp_path / "config.json"
        save_language(path, "fr")
        monkeypatch.setattr(i18n, "detect_language", lambda: "zh")
        assert load_language(path) == "zh"
