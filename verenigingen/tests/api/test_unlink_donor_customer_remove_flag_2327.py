"""
#2327: ``unlink_donor_customer(remove_customer=...)`` over HTTP.

A form/API client sends the flag as a string, and ``"0"`` is truthy in Python, so the endpoint
used to ATTEMPT the Customer delete for ``remove_customer="0"``. Driven through the real WSGI app
(README rule 21, ``wsgi_http_session``) as
a Verenigingen Administrator. Where that profile may not delete a Customer, an attempted delete
shows up as a refusal (``DONOR_CUSTOMER_UNLINK_ERROR``, unlink rolled back); where it may, it
really removes the Customer (the data-loss path). The test reads which applies.

Donors/Customers are committed because the WSGI child is another DB connection; removed afterwards.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.api.test_unlink_donor_customer_remove_flag_2327
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.wsgi_http_session import (
    CommittedLoginUsersMixin,
    api_path,
    operation_result,
    run_wsgi_cases,
)

ENDPOINT = api_path("verenigingen.api.donor_customer_management.unlink_donor_customer")


class TestUnlinkDonorCustomerRemoveFlag2327(CommittedLoginUsersMixin, EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.admin = self._create_login_users(admin="Verenigingen Administrator")["admin"]
        # Whether this profile may delete a Customer depends on the site's Custom DocPerm rows
        # (measured: no on test_site_1, which has them), so read it instead of assuming it.
        with self.set_user(self.admin):
            self.admin_can_delete = bool(frappe.has_permission("Customer", "delete"))
        self._donors = []
        self.addCleanup(self._cleanup_donors)

    def _cleanup_donors(self):
        frappe.db.rollback()
        for donor, customer in self._donors:
            for doctype, name in (("Donor", donor), ("Customer", customer)):
                if name and frappe.db.exists(doctype, name):
                    frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
        frappe.db.commit()

    def _create_linked_donor(self):
        donor = frappe.new_doc("Donor")
        donor.donor_name = f"Flag2327 {frappe.generate_hash(length=6)}"
        donor.donor_type = "Individual"
        donor.donor_email = f"f{frappe.generate_hash(length=6)}@example.com"
        donor.flags.enable_customer_sync_in_test = True  # sync is gated off in tests otherwise
        donor.save()
        donor.reload()
        customer = donor.customer
        self.assertTrue(customer, "Donor.save is expected to create and link a Customer")
        self._donors.append((donor.name, customer))
        frappe.db.set_value("Customer", customer, "donor", donor.name)
        frappe.db.commit()
        return donor.name, customer

    def _case(self, name, user, donor, flag):
        return {
            "name": name,
            "endpoint": ENDPOINT,
            "login": {"usr": user, "pwd": self.password},
            "csrf": "valid",
            "json": {"donor_name": donor, "remove_customer": flag},
        }

    def _state(self, donor, customer):
        frappe.db.rollback()  # fresh snapshot of what the child committed
        return {
            "customer_exists": bool(frappe.db.exists("Customer", customer)),
            "donor_customer": frappe.db.get_value("Donor", donor, "customer"),
        }

    def test_zero_string_unlinks_without_attempting_a_delete(self):
        """"0"/"false"/0 unlink and keep the Customer (without the fix, "0" attempts the delete)."""
        cases, linked = [], {}
        for flag in ("0", "false", 0):
            key = f"flag-{flag!r}"
            linked[key] = self._create_linked_donor()
            cases.append(self._case(key, self.admin, linked[key][0], flag))
        out = run_wsgi_cases(*cases)
        for key, (donor, customer) in linked.items():
            result = operation_result(out[key])
            self.assertTrue(result["success"], (key, result))
            self.assertEqual(result["data"], {"customer_unlinked": True, "customer_name": customer}, key)
            state = self._state(donor, customer)
            self.assertTrue(state["customer_exists"], f"{key}: Customer deleted by a false flag")
            self.assertFalse(state["donor_customer"], key)

    def test_one_string_still_attempts_the_delete(self):
        """Control: "1" attempts the delete: refused (rolled back) or performed, per the caller's permission."""
        donor, customer = self._create_linked_donor()
        if not self.admin_can_delete:
            self.expectErrorLog("Donor Customer Unlink Error")
        result = operation_result(run_wsgi_cases(self._case("one", self.admin, donor, "1"))["one"])
        state = self._state(donor, customer)
        if self.admin_can_delete:
            self.assertTrue(result["success"], result)
            self.assertTrue(result["data"]["customer_deleted"], result)
            self.assertFalse(state["customer_exists"])
            self.assertFalse(state["donor_customer"])
        else:
            self.assertFalse(result["success"], result)
            self.assertEqual(result["error"]["code"], "DONOR_CUSTOMER_UNLINK_ERROR")
            # The PermissionError carries no text; the message must still say what went wrong.
            self.assertIn("PermissionError", result["error"]["message"])
            self.assertTrue(state["customer_exists"])
            self.assertEqual(state["donor_customer"], customer)  # half-unlink rolled back (#2304)
