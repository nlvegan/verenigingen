"""
Tests for the /brand_css page controller
(verenigingen.templates.pages.brand_css).

This page serves the generated brand CSS as text/css. It is a guest-accessible
route used by other portal templates (referenced via context.brand_css =
"/brand_css"). The controller reads a pre-generated static CSS file when it
exists, otherwise falls back to generating CSS on the fly.
"""

import os

import frappe

from verenigingen.templates.pages import brand_css
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPageBrandCss(EnhancedTestCase):
    """Exercise the brand_css page controller's real behavior."""

    def test_get_context_sets_css_content_and_headers(self):
        """get_context populates css_content and sets css response headers."""
        context = frappe._dict()
        result = brand_css.get_context(context)

        # Returns the same context object
        self.assertIs(result, context)

        # CSS content is present, non-empty, and timestamp-stamped for cache debugging.
        self.assertTrue(context.css_content)
        self.assertIn("/* Generated at", context.css_content)
        self.assertEqual(context.no_cache, 1)

        # Response headers force no-cache so brand changes propagate immediately.
        self.assertEqual(frappe.response.content_type, "text/css; charset=utf-8")
        self.assertEqual(frappe.response.headers["Cache-Control"], "no-cache, no-store, must-revalidate")
        self.assertEqual(frappe.response.headers["Pragma"], "no-cache")

    def test_get_context_reads_static_file_when_present(self):
        """When the static brand CSS file exists, its content is served verbatim."""
        from verenigingen.utils.brand_css_generator import get_brand_css_file_path

        css_path = get_brand_css_file_path()
        if not os.path.exists(css_path):
            self.skipTest("Static brand CSS file not present on this site")

        with open(css_path, "r") as f:
            file_css = f.read()

        context = frappe._dict()
        brand_css.get_context(context)

        # The static file body must appear inside the served (timestamp-prefixed) content.
        self.assertIn(file_css, context.css_content)

    def test_serve_brand_css_returns_css_string(self):
        """The whitelisted serve_brand_css returns CSS text and sets content type."""
        result = brand_css.serve_brand_css()
        self.assertIsInstance(result, str)
        self.assertIn("/* Generated at", result)
        self.assertEqual(frappe.response.content_type, "text/css; charset=utf-8")

    def test_serve_brand_css_guest_accessible(self):
        """serve_brand_css is allow_guest=True and works without a privileged user."""
        # Create a low-privilege scratch user (no admin roles) and confirm it still serves.
        with self.as_role("Verenigingen Member"):
            result = brand_css.serve_brand_css()
        self.assertIsInstance(result, str)
        self.assertTrue(result.strip())
