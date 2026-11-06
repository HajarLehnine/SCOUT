import unittest
from pathlib import Path

from localization import LANGUAGES, LANGUAGE_NAMES, is_rtl, translate
from streamlit.testing.v1 import AppTest


class LocalizationTests(unittest.TestCase):
    def test_supported_languages_have_native_selector_labels(self):
        self.assertEqual(len(LANGUAGES), 14)
        self.assertEqual(set(LANGUAGES), set(LANGUAGE_NAMES))
        self.assertEqual(LANGUAGES[0], "English")
        self.assertEqual(LANGUAGE_NAMES["Arabic"], "العربية")

    def test_translation_falls_back_without_mutating_unknown_source_text(self):
        original_title = "Original market outlook"
        self.assertEqual(translate(original_title, "French"), original_title)

    def test_translates_interface_and_formats_placeholders(self):
        self.assertEqual(translate("Market", "French"), "Marché")
        self.assertIn(
            "7",
            translate("Run ID: {id} · {created}", "French", id=7, created="today"),
        )

    def test_rtl_is_enabled_only_for_arabic(self):
        self.assertTrue(is_rtl("Arabic"))
        self.assertFalse(is_rtl("English"))
        self.assertFalse(is_rtl("Hebrew"))

    def test_streamlit_selector_defaults_to_english_and_keeps_selection_on_rerun(self):
        app_path = Path(__file__).resolve().parents[1] / "app.py"
        app_test = AppTest.from_file(str(app_path), default_timeout=15).run()

        selector = app_test.selectbox(key="ui_language")
        self.assertEqual(selector.value, "English")
        self.assertEqual(len(selector.options), 14)

        selector.set_value("French").run()
        self.assertEqual(app_test.session_state["ui_language"], "French")
        self.assertEqual(
            next(button.label for button in app_test.button if button.key == "mira-enter"),
            "Accéder à SCOUT →",
        )
        self.assertFalse(app_test.exception)


if __name__ == "__main__":
    unittest.main()
