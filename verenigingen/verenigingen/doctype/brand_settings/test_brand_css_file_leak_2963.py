"""#2963: the brand tests that write brand_colors.css must put the site file back.

Runs the real writer classes in-process (a nested unittest run, so their class cleanups
fire) and inspects the file afterwards. Each case first proves the writer was reached,
because a file that is absent after a run that never wrote it proves nothing.
"""

import io
import os
import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.site_file_snapshot import brand_colors_css_path
from verenigingen.utils import brand_css_generator
from verenigingen.verenigingen.doctype.brand_settings import (
    test_brand_settings,
    test_brand_settings_endpoints,
)

WRITER_CLASSES = (
    test_brand_settings.TestBrandSettingsIntegration,
    test_brand_settings_endpoints.TestBrandCSSEndpoints,
    test_brand_settings_endpoints.TestBrandDefaultsAndDerivation,
)


class TestBrandCssFileLeak2963(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.css_path = brand_colors_css_path()
        self.addCleanup(self._put_brand_css_back_2963, self.css_path, self._bytes_or_none_2963(self.css_path))

    @staticmethod
    def _bytes_or_none_2963(path):
        if not os.path.exists(path):
            return None
        with open(path, "rb") as handle:
            return handle.read()

    @staticmethod
    def _put_brand_css_back_2963(path, original):
        if original is None:
            if os.path.exists(path):
                os.remove(path)
        else:
            with open(path, "wb") as handle:
                handle.write(original)

    def _run_writer_class_2963(self, writer_class):
        """Run one writer class for real; return (tests run, writes of brand_colors.css)."""
        writes = []
        real_write = brand_css_generator.write_css_file

        def spy_write(file_path, content):
            writes.append(file_path)
            return real_write(file_path, content)

        brand_css_generator.write_css_file = spy_write
        try:
            suite = unittest.TestLoader().loadTestsFromTestCase(writer_class)
            result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
        finally:
            brand_css_generator.write_css_file = real_write
        self.assertTrue(
            result.wasSuccessful(), f"{writer_class.__name__} failed: {result.failures + result.errors}"
        )
        css_writes = [p for p in writes if p.endswith("brand_colors.css")]
        return result.testsRun, css_writes

    def test_file_absent_before_is_absent_after(self):
        wrote_somewhere = 0
        for writer_class in WRITER_CLASSES:
            if os.path.exists(self.css_path):
                os.remove(self.css_path)
            ran, css_writes = self._run_writer_class_2963(writer_class)
            self.assertGreater(ran, 0)
            wrote_somewhere += len(css_writes)
            self.assertFalse(
                os.path.exists(self.css_path),
                f"{writer_class.__name__} left {self.css_path} behind ({len(css_writes)} writes)",
            )
        # Control: at least the Brand Settings save path really wrote the file.
        self.assertGreater(wrote_somewhere, 0, "no writer reached brand_colors.css; the guard saw nothing")

    def test_file_present_before_is_restored_byte_for_byte(self):
        sentinel = b"/* #2963 sentinel: not what the generator emits */\n"
        for writer_class in WRITER_CLASSES:
            with open(self.css_path, "wb") as handle:
                handle.write(sentinel)
            self._run_writer_class_2963(writer_class)
            self.assertEqual(
                self._bytes_or_none_2963(self.css_path),
                sentinel,
                f"{writer_class.__name__} did not restore the pre-existing file",
            )
