"""
Regression test for #374: update_personal_details()'s nested birth-date
validation swallows its own deliberate `frappe.throw(_("Birth date cannot be
in the future"))` inside a bare `except Exception`, replacing it with the
generic `"Please enter a valid birth date"` message.

An existing test (test_page_personal_details_coverage.py::
test_update_rejects_future_birth_date) only asserts the exception TYPE
(ValidationError) and passes either way -- it does not catch this defect
because both the specific and the generic message raise the same type. This
test asserts the MESSAGE, which is what actually distinguishes "your date is
malformed" from "your date is in the future" for the person submitting the
form.
"""

import frappe
from frappe.utils import add_years, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestPersonalDetailsSwallowedThrow374(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self._original_dev_mode = frappe.conf.get("developer_mode")
        frappe.conf["developer_mode"] = 1

        self.member = self.create_test_member(
            first_name="Pers",
            last_name="Vandenberg",
            birth_date="1990-01-01",
        )
        self.user = self.member.email
        if not frappe.db.exists("User", self.user):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": self.user,
                    "first_name": "Pers",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert(ignore_permissions=True)
        self.member.db_set("user", self.user)
        self.member.db_set("first_name", "Pers")
        self.member.db_set("last_name", "Vandenberg")
        self.member.db_set("application_status", "Active")
        self.member.reload()

    def tearDown(self):
        if self._original_dev_mode is None:
            frappe.conf.pop("developer_mode", None)
        else:
            frappe.conf["developer_mode"] = self._original_dev_mode
        super().tearDown()

    def test_future_birth_date_message_says_future_not_generic_invalid(self):
        from verenigingen.templates.pages.personal_details import update_personal_details

        future = add_years(today(), 1)
        with self.as_user(self.user):
            frappe.local.form_dict = frappe._dict(
                {"first_name": "Jan", "last_name": "Vandenberg", "birth_date": future}
            )
            try:
                with self.assertRaises(frappe.ValidationError) as ctx:
                    update_personal_details()
            finally:
                frappe.local.form_dict = frappe._dict()

        # The body's own specific refusal ("cannot be in the future") must
        # reach the caller -- not the generic "please enter a valid birth
        # date" message the surrounding `except Exception` currently
        # substitutes, which tells the member their input is malformed when
        # it was actually just too late.
        self.assertIn("cannot be in the future", str(ctx.exception))
