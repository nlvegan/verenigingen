"""A logged-in non-admin gets real brand CSS from get_brand_css_inline on a site with no
static brand_colors.css (#2962).

Before the fix the file-less fallback called generate_brand_css(), which is
@high_security_api(ADMIN), so the endpoint's own try/except turned the refusal into
{"success": False}. Probe shortcut: the colours are written with set_single_value (no hooks, so
no static file is generated) and the caller is switched with frappe.set_user, not a login.
"""

import os

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.utils.site_file_snapshot import (
    brand_colors_css_path,
    restore_file_state_on_class_cleanup,
)
from verenigingen.verenigingen.doctype.brand_settings.brand_settings import (
    generate_brand_css,
    get_brand_css_inline,
)

_COLOUR_2962 = "#0a1b2c"


class TestBrandCssInlineNonAdmin2962(EnhancedTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        restore_file_state_on_class_cleanup(cls, brand_colors_css_path())

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        path = brand_colors_css_path()
        if os.path.exists(path):
            os.remove(path)
        self._original_colour_2962 = frappe.db.get_single_value("Brand Settings", "primary_color")
        frappe.db.set_single_value("Brand Settings", "primary_color", _COLOUR_2962)
        for key in ("brand_settings_css", "active_brand_settings"):
            frappe.cache().delete_value(key)
        self.plain_user_2962 = self.create_test_user_with_roles(
            "brand-css-2962@example.com", ["Verenigingen Auditor"]
        )
        email = getattr(self.plain_user_2962, "name", self.plain_user_2962)
        # Auditor passes the endpoint's own MEDIUM gate (rule 5) but is not an admin, so the
        # admin-only fallback is what refuses it. A bare Member never reaches the fallback.
        self.assertNotIn("System Manager", frappe.get_roles(email))

    def tearDown(self):
        frappe.set_user("Administrator")
        frappe.db.set_single_value("Brand Settings", "primary_color", self._original_colour_2962)
        for key in ("brand_settings_css", "active_brand_settings"):
            frappe.cache().delete_value(key)
        super().tearDown()

    def _as_plain_user_2962(self):
        frappe.set_user(getattr(self.plain_user_2962, "name", self.plain_user_2962))

    def test_non_admin_gets_css_when_static_file_absent(self):
        self.assertFalse(os.path.exists(brand_colors_css_path()))
        self._as_plain_user_2962()
        result = get_brand_css_inline()
        self.assertTrue(result["success"], result)
        self.assertIn(f"--brand-primary: {_COLOUR_2962}", result["css"])

    def test_admin_only_generator_stays_admin_only(self):
        """Control: the fix must not widen generate_brand_css to a non-admin."""
        self._as_plain_user_2962()
        with self.assertRaises(frappe.PermissionError):
            generate_brand_css()
