"""
#3172: a failed secondary field sync (Member -> User and friends) must leave an
Error Log row instead of vanishing into a stdlib logger, while still not
blocking the source document's own save.
"""

import frappe

from verenigingen.services.field_sync_service import FIELD_SYNC_CONFIG, _sync_to_target, sync_fields
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestFieldSyncFailureVisibility(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.fs_start = frappe.utils.now_datetime()
        self.fs_email = f"fieldsync3172.{frappe.generate_hash(length=6)}@test.local"
        self.fs_member = self.create_test_member(
            first_name="Fieldsync",
            last_name="Visible",
            email=self.fs_email,
            birth_date="1990-01-01",
        )
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": self.fs_email,
                "first_name": "Fieldsync",
                "send_welcome_email": 0,
            }
        ).insert(ignore_permissions=True)
        self.fs_member.user = user.name
        self.fs_member.save(ignore_permissions=True)

    def _fs_error_rows(self):
        # Error Log is MyISAM (non-transactional): scope by creation time and title.
        return frappe.get_all(
            "Error Log",
            filters={"creation": [">=", self.fs_start], "method": ["like", "%Field sync%"]},
            fields=["name", "method", "error"],
        )

    def _fs_change_first_name(self, value):
        member = frappe.get_doc("Member", self.fs_member.name)
        member.load_doc_before_save()
        member.first_name = value
        return member

    def test_failed_target_save_writes_error_log_and_does_not_raise(self):
        # 141 chars exceeds User.first_name's 140 limit: a real validation failure
        # on the TARGET save (the source is never saved here, so only the sync fails).
        member = self._fs_change_first_name("x" * 141)

        sync_fields(member)  # must not raise

        rows = self._fs_error_rows()
        self.assertTrue(rows, "a failed sync must leave an Error Log row")
        self.assertTrue(
            any(self.fs_member.name in r["method"] and "User" in r["method"] for r in rows),
            f"title must name source and target; got {[r['method'] for r in rows]}",
        )
        # Keyword form: title in `method`, diagnostics in `error`. A swapped
        # (message, title) call would put the label in `error` instead.
        row = next(r for r in rows if self.fs_member.name in r["method"])
        self.assertIn("Field sync failed", row["method"])
        self.assertIn("max characters allowed is 140", row["error"])
        self.assertIn("Traceback", row["error"])

    def test_successful_sync_writes_no_error_log(self):
        member = self._fs_change_first_name("Renamed")

        sync_fields(member)

        self.assertEqual(frappe.db.get_value("User", self.fs_email, "first_name"), "Renamed")
        self.assertEqual(self._fs_error_rows(), [])


class TestMemberSelfRenameSyncsCustomer(EnhancedTestCase):
    """#3182: a member saving their OWN record (portal session, member role only) must
    still sync full_name to the linked Customer.

    Customer.save() runs ERPNext's on_update -> create_primary_contact(), which calls
    frappe.set_value("Contact", ..., "is_primary_contact", 1): a permission-checked save
    the member's session cannot pass, so the sync failed for every portal rename.
    """

    def setUp(self):
        super().setUp()
        self.rn_start = frappe.utils.now_datetime()
        self.rn_email = f"selfrename3182.{frappe.generate_hash(length=6)}@test.local"
        self.rn_member = self.create_test_member(
            first_name="Selfrename",
            last_name="Portal",
            email=self.rn_email,
            birth_date="1990-01-01",
        )
        frappe.get_doc(
            {
                "doctype": "User",
                "email": self.rn_email,
                "first_name": "Selfrename",
                "send_welcome_email": 0,
                "roles": [{"role": "Verenigingen Member"}],
            }
        ).insert(ignore_permissions=True)
        self.rn_member.db_set("user", self.rn_email)

    def test_member_session_rename_updates_customer_name(self):
        customer = self.rn_member.customer
        self.assertTrue(customer, "precondition: the test member has a Customer")
        # Precondition for the failing path: with a primary contact, Customer.on_update
        # takes the frappe.set_value("Contact", ...) branch.
        self.assertTrue(
            frappe.db.get_value("Customer", customer, "customer_primary_contact"),
            "precondition: the Customer has a primary contact",
        )
        self.assertFalse(
            frappe.has_permission("Contact", "write", user=self.rn_email),
            "precondition: the member role cannot write Contact",
        )

        member = frappe.get_doc("Member", self.rn_member.name)
        member.load_doc_before_save()
        member.full_name = "Renamed Byself"
        # _sync_to_target, not sync_fields: sync_fields swallows any exception, and the
        # Customer row is written before on_update raises, so a swallowed failure would
        # still show the new name. Here a raise fails the test.
        with self.as_user(self.rn_email):
            _sync_to_target(member, "Customer", FIELD_SYNC_CONFIG["Member"]["Customer"])

        self.assertEqual(frappe.db.get_value("Customer", customer, "customer_name"), "Renamed Byself")
        rows = frappe.get_all(
            "Error Log",
            filters={"creation": [">=", self.rn_start], "method": ["like", "%Field sync%"]},
            fields=["method", "error"],
        )
        self.assertEqual(rows, [])
