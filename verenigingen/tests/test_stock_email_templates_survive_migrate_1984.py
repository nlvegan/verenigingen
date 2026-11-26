"""#1984: a staff edit of a stock Email Template survives `bench migrate`.

Migrate runs ``frappe.utils.fixtures.sync_fixtures`` (frappe/migrate.py) and then every
``after_migrate`` hook. Six stock templates used to ship as fixtures, so the sync put the
shipped text back over staff edits. Here the two real migrate steps are run: the app's actual
fixture sync, and the app's declared after_migrate hooks that deal with Email Templates.
"""

import json

import frappe
from frappe.utils.fixtures import sync_fixtures

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.tests.utils.paths import APP_ROOT
from verenigingen.tests.utils.stock_email_templates import _cleanup_stock_email_templates

FIXTURE_FILE = APP_ROOT / "verenigingen" / "fixtures" / "email_template.json"
MANAGED = (
    "expense_approval_request",
    "expense_approved",
    "expense_rejected",
    "donation_confirmation",
    "donation_payment_confirmation",
    "termination_overdue_notification",
)
EDITED = "STAFF EDITED SUBJECT {{ expense.name|e }}"


def _run_migrate_steps():
    """What `bench migrate` does to Email Templates: sync fixtures, then after_migrate hooks."""
    sync_fixtures("verenigingen")
    hooks = frappe.get_hooks("after_migrate", app_name="verenigingen")
    for path in hooks:
        if "email_template" in path:
            frappe.get_attr(path)()


class TestStockEmailTemplatesSurviveMigrate1984(VereningingenTestCase):
    @classmethod
    def tearDownClass(cls):
        _cleanup_stock_email_templates(MANAGED)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        _cleanup_stock_email_templates(MANAGED)

    def test_staff_edit_survives_migrate_for_every_managed_template(self):
        for name in MANAGED:
            frappe.db.set_value("Email Template", name, "subject", EDITED + name)

        _run_migrate_steps()

        for name in MANAGED:
            self.assertEqual(
                frappe.db.get_value("Email Template", name, "subject"),
                EDITED + name,
                f"{name}: migrate put the stock subject back over the staff edit",
            )

    def test_missing_managed_row_is_recreated_and_a_sibling_edit_is_kept(self):
        # Control with a real row: one edited sibling AND one deleted row in the same run.
        frappe.db.set_value("Email Template", "expense_approved", "subject", EDITED)
        frappe.delete_doc("Email Template", "donation_confirmation", force=True)

        _run_migrate_steps()

        self.assertTrue(frappe.db.exists("Email Template", "donation_confirmation"))
        self.assertTrue(frappe.db.get_value("Email Template", "donation_confirmation", "response_html"))
        self.assertEqual(frappe.db.get_value("Email Template", "expense_approved", "subject"), EDITED)

    def test_managed_templates_are_not_shipped_as_fixtures(self):
        shipped = {row["name"] for row in json.loads(FIXTURE_FILE.read_text())}
        self.assertEqual(shipped & set(MANAGED), set())
        # Control: the file is still read and still carries other rows.
        self.assertIn("payment_reminder_urgent", shipped)

    def test_a_migrate_hook_creates_the_managed_templates(self):
        hooks = [h for h in frappe.get_hooks("after_migrate", app_name="verenigingen") if "email_template" in h]
        self.assertTrue(hooks, "no after_migrate hook seeds the stock Email Templates")
