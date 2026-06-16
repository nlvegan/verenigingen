# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
"""Tests for the Brand Settings DocType (theme/branding color math, validation, CSS/IO).

Pure color helpers are exercised directly on a fresh in-memory doc instance with known
inputs/outputs. Lifecycle/IO methods are exercised as real integration against the Single
doc on the test site.
"""

import os

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.brand_settings.brand_settings import (
    get_active_brand_settings,
    get_organization_logo,
)


class TestBrandSettingsHelpers(EnhancedTestCase):
    """Pure color-math + validation helpers — no DB writes needed."""

    def setUp(self):
        super().setUp()
        # A fresh, unsaved in-memory instance is enough for the pure helpers.
        self.doc = frappe.new_doc("Brand Settings")

    # ------------------------------------------------------------------
    # is_valid_hex_color
    # ------------------------------------------------------------------

    def test_is_valid_hex_color_accepts_six_digit(self):
        self.assertTrue(self.doc.is_valid_hex_color("#ff0000"))
        self.assertTrue(self.doc.is_valid_hex_color("#FFFFFF"))
        self.assertTrue(self.doc.is_valid_hex_color("#000000"))

    def test_is_valid_hex_color_accepts_three_digit(self):
        self.assertTrue(self.doc.is_valid_hex_color("#fff"))
        self.assertTrue(self.doc.is_valid_hex_color("#0a3"))

    def test_is_valid_hex_color_rejects_bad_input(self):
        self.assertFalse(self.doc.is_valid_hex_color(""))
        self.assertFalse(self.doc.is_valid_hex_color(None))
        self.assertFalse(self.doc.is_valid_hex_color("ff0000"))  # no #
        self.assertFalse(self.doc.is_valid_hex_color("#ff00"))  # wrong length (4)
        self.assertFalse(self.doc.is_valid_hex_color("#ff00000"))  # wrong length (7)
        self.assertFalse(self.doc.is_valid_hex_color("#gggggg"))  # non-hex chars

    # ------------------------------------------------------------------
    # get_color_brightness / get_contrasting_text_color
    # ------------------------------------------------------------------

    def test_brightness_white_and_black(self):
        self.assertEqual(self.doc.get_color_brightness("#ffffff"), 255.0)
        self.assertEqual(self.doc.get_color_brightness("#000000"), 0.0)

    def test_brightness_three_digit_expands(self):
        self.assertEqual(self.doc.get_color_brightness("#fff"), 255.0)

    def test_brightness_invalid_returns_default_medium(self):
        self.assertEqual(self.doc.get_color_brightness(None), 128)
        self.assertEqual(self.doc.get_color_brightness("nothex"), 128)
        self.assertEqual(self.doc.get_color_brightness("#zzzzzz"), 128)

    def test_contrasting_text_color(self):
        # Light background -> dark text
        self.assertEqual(self.doc.get_contrasting_text_color("#ffffff"), "#000000")
        # Dark background -> light text
        self.assertEqual(self.doc.get_contrasting_text_color("#000000"), "#ffffff")

    def test_contrasting_text_color_boundary(self):
        # brightness exactly 128 -> not < 128 -> dark text
        # #808080 brightness = 128.0
        self.assertEqual(self.doc.get_color_brightness("#808080"), 128.0)
        self.assertEqual(self.doc.get_contrasting_text_color("#808080"), "#000000")

    # ------------------------------------------------------------------
    # mix_colors
    # ------------------------------------------------------------------

    def test_mix_colors_fifty_fifty(self):
        # red + blue at 0.5 = #7f007f (int truncation)
        self.assertEqual(self.doc.mix_colors("#ff0000", "#0000ff"), "#7f007f")

    def test_mix_colors_full_ratio_returns_color1(self):
        self.assertEqual(self.doc.mix_colors("#ff0000", "#0000ff", 1.0), "#ff0000")

    def test_mix_colors_zero_ratio_returns_color2(self):
        self.assertEqual(self.doc.mix_colors("#ff0000", "#0000ff", 0.0), "#0000ff")

    def test_mix_colors_handles_three_digit(self):
        # #fff + #000 at 0.5 -> #7f7f7f
        self.assertEqual(self.doc.mix_colors("#fff", "#000", 0.5), "#7f7f7f")

    def test_mix_colors_invalid_inputs_fall_back(self):
        # Invalid color1 -> returns color2
        self.assertEqual(self.doc.mix_colors("bad", "#0000ff"), "#0000ff")
        # Invalid color2 -> returns color1
        self.assertEqual(self.doc.mix_colors("#ff0000", None), "#ff0000")

    # ------------------------------------------------------------------
    # tint_color
    # ------------------------------------------------------------------

    def test_tint_color_subtle(self):
        # tint white with red at 0.05 -> mostly white with slight red push
        result = self.doc.tint_color("#ffffff", "#ff0000", 0.05)
        self.assertTrue(self.doc.is_valid_hex_color(result))
        # Equivalent to mix_colors(tint, base, strength)
        self.assertEqual(result, self.doc.mix_colors("#ff0000", "#ffffff", 0.05))

    # ------------------------------------------------------------------
    # generate_background_layers
    # ------------------------------------------------------------------

    def test_generate_background_layers_with_no_brand_colors(self):
        # Clear brand colors -> tint_color(base, None/"", ...) returns base unchanged
        self.doc.primary_color = ""
        self.doc.secondary_color = ""
        self.doc.background_primary_color = ""
        self.doc.background_secondary_color = ""
        layers = self.doc.generate_background_layers()
        self.assertEqual(set(layers.keys()), {"workspace", "container", "cards"})
        # With no primary/secondary color, tint_color falls back to the base (defaults)
        self.assertEqual(layers["workspace"], "#ffffff")
        self.assertEqual(layers["cards"], "#ffffff")

    def test_generate_background_layers_with_brand_colors(self):
        self.doc.primary_color = "#cf3131"
        self.doc.secondary_color = "#01796f"
        self.doc.background_primary_color = "#ffffff"
        self.doc.background_secondary_color = "#f8f9fa"
        layers = self.doc.generate_background_layers()
        for key in ("workspace", "container", "cards"):
            self.assertTrue(self.doc.is_valid_hex_color(layers[key]), f"{key}={layers[key]}")
        # Workspace should be tinted (no longer pure white)
        self.assertNotEqual(layers["workspace"], "#ffffff")

    # ------------------------------------------------------------------
    # auto_calculate_derived_colors (pure transform on in-memory doc)
    # ------------------------------------------------------------------

    def test_auto_calculate_derived_colors_fills_defaults(self):
        self.doc.primary_color = "#cf3131"
        self.doc.secondary_color = "#01796f"
        self.doc.accent_color = "#663399"
        self.doc.auto_calculate_derived_colors()

        # Hover = base mixed 85% toward black
        self.assertEqual(self.doc.primary_hover_color, self.doc.mix_colors("#cf3131", "#000000", 0.85))
        # Button text auto-contrast
        self.assertEqual(self.doc.primary_button_text_color, self.doc.get_contrasting_text_color("#cf3131"))
        # Semantic + text/bg defaults populated
        self.assertEqual(self.doc.success_color, "#28a745")
        self.assertEqual(self.doc.warning_color, "#ffc107")
        self.assertEqual(self.doc.error_color, "#dc3545")
        self.assertEqual(self.doc.info_color, "#17a2b8")
        self.assertEqual(self.doc.text_primary_color, "#333333")
        self.assertEqual(self.doc.background_primary_color, "#ffffff")
        # Derived backgrounds present and valid
        self.assertTrue(self.doc.is_valid_hex_color(self.doc.list_page_background_color))
        self.assertTrue(self.doc.is_valid_hex_color(self.doc.card_container_background_color))

    # ------------------------------------------------------------------
    # validate_colors / validate
    # ------------------------------------------------------------------

    def test_validate_colors_accepts_valid(self):
        self.doc.primary_color = "#cf3131"
        self.doc.secondary_color = "#01796f"
        # Should not raise
        self.doc.validate_colors()

    def test_validate_colors_rejects_bad_hex(self):
        self.doc.primary_color = "not-a-color"
        with self.assertRaises(frappe.ValidationError):
            self.doc.validate_colors()

    def test_validate_active_settings_is_noop(self):
        # Single doctype - method intentionally does nothing, must not raise
        self.assertIsNone(self.doc.validate_active_settings())


class TestBrandSettingsModuleHelpers(EnhancedTestCase):
    """Module-level duplicated helpers inside generate_brand_css (nested) are covered via
    the integration path; here we cover the whitelisted read endpoints."""

    def test_get_active_brand_settings_returns_dict(self):
        result = get_active_brand_settings()
        self.assertIsInstance(result, dict)
        # Always carries the core brand keys (either from doc or defaults)
        for key in ("primary_color", "secondary_color", "accent_color"):
            self.assertIn(key, result)
            self.assertTrue(str(result[key]).startswith("#"))

    def test_get_active_brand_settings_cache_roundtrip(self):
        frappe.cache().delete_key("active_brand_settings")
        first = get_active_brand_settings()
        # The first call must populate the cache.
        self.assertIsNotNone(frappe.cache().get_value("active_brand_settings"))

        original = frappe.db.get_single_value("Brand Settings", "primary_color")
        sentinel = "#abcdef" if original != "#abcdef" else "#fedcba"
        try:
            # Mutate the Single directly: db.set_single_value bypasses the
            # on_update cache invalidation, so a fresh read WOULD differ...
            frappe.db.set_single_value("Brand Settings", "primary_color", sentinel)
            self.assertEqual(frappe.db.get_single_value("Brand Settings", "primary_color"), sentinel)
            # ...but the second call must still return the pre-mutation value,
            # proving it is actually served from cache rather than re-read. The
            # old test compared two unchanged calls and proved nothing.
            second = get_active_brand_settings()
            self.assertEqual(second.get("primary_color"), first.get("primary_color"))
            self.assertNotEqual(second.get("primary_color"), sentinel)
        finally:
            frappe.db.set_single_value("Brand Settings", "primary_color", original)
            frappe.cache().delete_key("active_brand_settings")

    def test_get_organization_logo_returns_none_or_url(self):
        frappe.cache().delete_key("organization_logo")
        result = get_organization_logo()
        # Either a public/file URL string or None — must not crash
        self.assertTrue(result is None or isinstance(result, str))


class TestBrandSettingsIntegration(EnhancedTestCase):
    """Real integration against the Single Brand Settings doc."""

    def setUp(self):
        super().setUp()
        self._as_admin()

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def _as_admin(self):
        frappe.set_user("Administrator")

    def _save_with_colors(self, primary, secondary, accent):
        doc = frappe.get_single("Brand Settings")
        doc.primary_color = primary
        doc.secondary_color = secondary
        doc.accent_color = accent
        doc.save()
        return doc

    def test_save_runs_full_lifecycle_and_derives_colors(self):
        doc = self._save_with_colors("#cf3131", "#01796f", "#663399")
        doc.reload()
        # before_save -> auto_calculate_derived_colors ran
        self.assertEqual(doc.primary_hover_color, doc.mix_colors("#cf3131", "#000000", 0.85))
        self.assertEqual(doc.primary_button_text_color, doc.get_contrasting_text_color("#cf3131"))
        self.assertTrue(doc.is_valid_hex_color(doc.list_page_background_color))

    def test_save_with_invalid_color_raises(self):
        doc = frappe.get_single("Brand Settings")
        doc.primary_color = "#zzzzzz"
        with self.assertRaises(frappe.ValidationError):
            doc.save()

    def test_on_update_generates_static_css_file(self):
        from verenigingen.utils.brand_css_generator import get_brand_css_file_path

        self._save_with_colors("#123456", "#654321", "#0a0a0a")
        css_path = get_brand_css_file_path()
        self.assertTrue(os.path.exists(css_path), f"CSS file not generated at {css_path}")
        with open(css_path, "r") as f:
            css = f.read()
        self.assertIn("#123456", css.lower())

    def test_get_active_brand_settings_reflects_saved_doc(self):
        self._save_with_colors("#aabbcc", "#112233", "#445566")
        frappe.cache().delete_key("active_brand_settings")
        result = get_active_brand_settings()
        self.assertEqual(result.get("primary_color"), "#aabbcc")
