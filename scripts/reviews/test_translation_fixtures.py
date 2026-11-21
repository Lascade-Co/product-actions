"""Translation preview stays readable without exposing original review text."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

import digest_render_fixtures
from reviews_render import render
from translation_cases import REVIEW_CASES


class TranslationFixtureTests(unittest.TestCase):
    def test_mobile_review_fixture_exercises_a_successful_translation(self):
        model = digest_render_fixtures.mobile_fixture_models()["reviews"]
        review = model["apps"][0]["playstore_reviews"][0]
        _, html = render(model)
        self.assertTrue(review["translated_body"] in html, "Translated body must be visible")
        self.assertFalse(review["body"] in html, "Original body must not be visible")
        self.assertTrue("Translated from Spanish" in html, "Source language tag must be visible")
        self.assertFalse("Translation unavailable" in html, "Successful fixture must not show failure")

    def test_preview_includes_four_translated_reviews_and_untouched_english(self):
        _, html = render(digest_render_fixtures.translation_fixture_model())
        self.assertEqual(html.count("Translated from "), 4)
        for case in REVIEW_CASES:
            self.assertIn(case["body_en"], html)
            if case["title_en"]:
                self.assertIn(case["title_en"], html)
            if case["language"] != "en":
                self.assertNotIn(case["body"], html)
                if case["title"]:
                    self.assertNotIn(case["title"], html)
        self.assertNotIn("Non-English", html)

    def test_standard_render_command_writes_translation_preview_with_count_only_output(self):
        with tempfile.TemporaryDirectory() as directory, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            digest_render_fixtures.write_previews(directory)
            self.assertTrue((Path(directory) / "reviews-translated.html").exists())
            self.assertEqual(len(list(Path(directory).glob("*.html"))), 6)
        self.assertEqual(output.getvalue(), "Rendered 6 synthetic fixture previews\n")


if __name__ == "__main__":
    unittest.main()
