# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt
#
# Complementary coverage for the Brand Settings module-level endpoints and the
# owl-theme sync surface, which test_brand_settings.py leaves largely untested.
#
# Covered here WITH REAL ASSERTIONS:
#   - generate_brand_css(): deprecated wrapper still returns the brand CSS
#     (with the :root custom properties + portal scoping) and emits a warning
#   - get_brand_css_inline(): success envelope carrying the CSS string
#   - force_rebuild_css(): clears caches + regenerates the static file, reports
#     a non-zero css_length
#   - check_owl_theme_integration(): not-installed branch on a site without the
#     Owl Theme app
#   - sync_to_owl_theme(): no-op early return when Owl Theme is absent
#   - sync_brand_settings_to_owl_theme(): success envelope (sync is a no-op when
#     owl theme absent, but the wrapper still reports success)
#   - create_default_brand_settings(): returns False because the Single already
#     exists on the test site
#   - auto_calculate_derived_colors: respects a user's manual hover override
#
# These run against the REAL Single Brand Settings doc. The save()/force_rebuild
# paths regenerate the tracked public/css/email_brand.css file; the test runner
# restores it via `git checkout` after this module (handled by the orchestrator),
# and tests here avoid asserting on that file's on-disk content.

import warnings

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.brand_settings.brand_settings import (
    check_owl_theme_integration,
    create_default_brand_settings,
    force_rebuild_css,
    generate_brand_css,
    get_brand_css_inline,
    sync_brand_settings_to_owl_theme,
)

OWL_INSTALLED = frappe.db.exists("DocType", "Owl Theme Settings")


class TestBrandCSSEndpoints(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_generate_brand_css_returns_brand_css_and_warns(self):
        """The deprecated generate_brand_css() still returns usable CSS carrying the
        brand custom properties, and emits a DeprecationWarning."""
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            css = generate_brand_css()
            self.assertTrue(any(issubclass(w.category, DeprecationWarning) for w in caught))

        self.assertIsInstance(css, str)
        self.assertGreater(len(css), 0)
        # Whichever path produced it (static file or inline fallback), it must
        # define the brand primary custom property as a CSS variable.
        self.assertIn("--brand-primary", css)
        self.assertIn(":root", css)

    def test_get_brand_css_inline_success_envelope(self):
        """get_brand_css_inline returns a success envelope with the CSS string."""
        result = get_brand_css_inline()
        self.assertTrue(result["success"])
        self.assertIn("--brand-primary", result["css"])
        self.assertIn("timestamp", result)

    def test_force_rebuild_css_regenerates_file(self):
        """force_rebuild_css clears caches, regenerates the static file and reports a
        non-empty css_length."""
        # Seed caches so we can prove they get cleared.
        frappe.cache().set_value("brand_settings_css", "stale")
        frappe.cache().set_value("active_brand_settings", {"primary_color": "#000000"})

        result = force_rebuild_css()

        self.assertTrue(result["success"])
        self.assertGreater(result["css_length"], 0)
        # The brand css cache key was cleared as part of the rebuild.
        self.assertIsNone(frappe.cache().get_value("brand_settings_css"))


class TestBrandOwlThemeSync(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_check_owl_theme_integration_reports_installed_flag(self):
        """check_owl_theme_integration reports whether the Owl Theme app is present.

        On a site WITHOUT owl_theme it returns installed=False with a clear message;
        WITH it, installed=True. We assert it matches the actual DocType presence."""
        result = check_owl_theme_integration()
        self.assertEqual(result["installed"], bool(OWL_INSTALLED))
        if not OWL_INSTALLED:
            self.assertIn("not installed", result["message"].lower())

    def test_sync_to_owl_theme_noop_when_absent(self):
        """When Owl Theme is absent, sync_to_owl_theme returns early without raising."""
        if OWL_INSTALLED:
            self.skipTest("Owl Theme installed on this site; the no-op branch is not exercised.")
        doc = frappe.get_single("Brand Settings")
        # Must not raise (early return on missing DocType).
        self.assertIsNone(doc.sync_to_owl_theme())

    def test_sync_brand_settings_to_owl_theme_envelope(self):
        """The whitelisted manual-sync wrapper returns a success envelope.

        With owl theme absent the underlying sync is a no-op, but the wrapper
        still reports success (it only fails on an unexpected exception)."""
        result = sync_brand_settings_to_owl_theme()
        self.assertIn("success", result)
        self.assertTrue(result["success"])


class TestBrandDefaultsAndDerivation(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    def test_create_default_brand_settings_returns_false_when_exists(self):
        """Brand Settings is a Single that already exists on the test site, so the
        creator is a no-op returning False."""
        self.assertFalse(create_default_brand_settings())

    def test_creates_defaults_on_a_genuinely_fresh_site(self):
        """#889: frappe.db.exists("Brand Settings", "Brand Settings") is always
        truthy for a Single (dt == dn short-circuits in frappe.db.exists), so
        create_default_brand_settings()'s "already exists" guard can never see
        a fresh, unconfigured site -- it always returns False, even when the
        singleton has never actually been saved. Simulate a genuinely fresh
        site by clearing tabSingles for Brand Settings directly, bypassing the
        ORM, then assert the create branch actually runs.
        """
        backup_rows = frappe.db.sql(
            "SELECT field, value FROM tabSingles WHERE doctype = %s",
            "Brand Settings",
            as_dict=True,
        )
        frappe.db.sql("DELETE FROM tabSingles WHERE doctype = %s", "Brand Settings")
        try:
            self.assertFalse(
                frappe.db.get_singles_dict("Brand Settings"),
                "test setup must start from a genuinely empty Single",
            )

            result = create_default_brand_settings()

            self.assertTrue(
                result,
                "create_default_brand_settings() must create defaults on a fresh site",
            )
            settings = frappe.get_single("Brand Settings")
            self.assertEqual(settings.primary_color, "#cf3131")
            self.assertEqual(settings.primary_button_text_color, "#ffffff")
            self.assertEqual(settings.secondary_button_text_color, "#ffffff")
            self.assertEqual(settings.accent_button_text_color, "#ffffff")
        finally:
            frappe.db.sql("DELETE FROM tabSingles WHERE doctype = %s", "Brand Settings")
            for row in backup_rows:
                frappe.db.sql(
                    "INSERT INTO tabSingles (doctype, field, value) VALUES (%s, %s, %s)",
                    ("Brand Settings", row.field, row.value),
                )

    def test_auto_calculate_preserves_manual_hover_override(self):
        """If a user manually set a hover color (different from the auto value), a
        re-run of auto_calculate_derived_colors must NOT overwrite it.

        This pins the doc_before_save comparison branch: the derived value is only
        applied when the field still equals the previously-saved value."""
        doc = frappe.get_single("Brand Settings")
        # Establish a known persisted baseline.
        doc.primary_color = "#cf3131"
        doc.save()
        doc.reload()

        # User manually overrides the hover to a custom value and saves.
        custom_hover = "#abcdef"
        doc.primary_hover_color = custom_hover
        doc.save()
        doc.reload()

        # The manual override survived the before_save auto-calculation.
        self.assertEqual(doc.primary_hover_color, custom_hover)
