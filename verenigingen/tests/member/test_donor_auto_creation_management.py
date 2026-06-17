"""
Real-integration tests for the whitelisted endpoints in
``verenigingen/api/donor_auto_creation_management.py`` (was ~30% covered).

Every endpoint returns an ``OperationResult``; the @frappe.whitelist /
security decorators serialize it to the nested dict schema even for in-process
calls, so results are accessed as dicts:
  - success: ``result["success"]`` True, payload under ``result["data"]``
  - failure: ``result["success"]`` False, details under ``result["error"]``
    (``result["error"]["errors"]`` / ``["message"]``).

Tests create real Customer / Donor / Customer Group records (no business-logic
mocking) and run as Administrator (the @critical_api / @high_security_api
decorators authorize the Administrator in test context).

Environment note: a freshly-provisioned test site can lack a Company (hence no
Income GL accounts and no Territory root). The "would actually create a donor"
path needs a configured donations GL account, so the eligibility/simulation
tests exercise the reachable guard / early-return branches and assert the
condition flags rather than processing a real auto-creation end to end. The
GL-heavy ``bulk_process_pending_payments`` is tested only for its no-account
guard and its empty-result path (it must not process payments without an
account, and completes cleanly when there are no matching payments).
"""

import frappe

from verenigingen.api import donor_auto_creation_management as mgmt
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorAutoCreationManagement(VereningingenTestCase):
    """Exercise the donor auto-creation management endpoints end to end."""

    def setUp(self):
        super().setUp()
        self._ensure_territory()
        self._settings_backup = {
            "auto_create_donors": frappe.db.get_single_value("Verenigingen Settings", "auto_create_donors"),
            "donations_gl_account": frappe.db.get_single_value(
                "Verenigingen Settings", "donations_gl_account"
            ),
            "donor_customer_groups": frappe.db.get_single_value(
                "Verenigingen Settings", "donor_customer_groups"
            ),
            "minimum_donation_amount": frappe.db.get_single_value(
                "Verenigingen Settings", "minimum_donation_amount"
            ),
        }

    def tearDown(self):
        for field, value in self._settings_backup.items():
            frappe.db.set_single_value("Verenigingen Settings", field, value)
        super().tearDown()

    @staticmethod
    def _ensure_territory():
        if not frappe.db.exists("Territory", "All Territories"):
            t = frappe.new_doc("Territory")
            t.territory_name = "All Territories"
            t.is_group = 1
            t.insert()
            frappe.db.commit()

    def _make_customer(self, customer_group="Donors"):
        if not frappe.db.exists("Customer Group", customer_group):
            cg = frappe.new_doc("Customer Group")
            cg.customer_group_name = customer_group
            cg.parent_customer_group = None
            cg.is_group = 0
            cg.insert()
            self.track_doc("Customer Group", cg.name)
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"AutoCust {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.customer_group = customer_group
        customer.territory = "All Territories"
        customer.insert()
        self.track_doc("Customer", customer.name)
        return customer

    # ----------------------------------------------------------- get_auto_creation_dashboard

    def test_get_auto_creation_dashboard_shape(self):
        result = mgmt.get_auto_creation_dashboard()
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("settings", data)
        self.assertIn("statistics", data)
        self.assertIn("recent_creations", data)
        self.assertIn("eligible_groups", data)
        self.assertIn("enabled", data["settings"])

    def test_get_auto_creation_dashboard_reflects_enabled_flag(self):
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        result = mgmt.get_auto_creation_dashboard()
        self.assertTrue(result["success"])
        self.assertTrue(result["data"]["settings"]["enabled"])

    # ----------------------------------------------------------- update_auto_creation_settings

    def _require_saveable_settings(self):
        # update_auto_creation_settings calls settings.save(); the Verenigingen
        # Settings singleton has mandatory `company`/`creation_user` fields that
        # a Company-less fresh test site cannot satisfy. Skip cleanly there.
        if not frappe.get_all("Company", limit=1):
            self.skipTest("No Company configured; Verenigingen Settings is not saveable")

    def test_update_auto_creation_settings_roundtrip(self):
        self._require_saveable_settings()
        result = mgmt.update_auto_creation_settings(
            enabled=1,
            eligible_customer_groups="Donors",
            minimum_amount=25,
        )
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["enabled"])
        self.assertEqual(data["eligible_customer_groups"], "Donors")
        self.assertEqual(float(data["minimum_amount"]), 25.0)
        self.assertEqual(frappe.db.get_single_value("Verenigingen Settings", "minimum_donation_amount"), 25.0)

    def test_update_auto_creation_settings_disable(self):
        self._require_saveable_settings()
        result = mgmt.update_auto_creation_settings(enabled=0)
        self.assertTrue(result["success"])
        self.assertFalse(result["data"]["enabled"])

    # ----------------------------------------------------------- get_donations_gl_accounts

    def test_get_donations_gl_accounts_shape(self):
        result = mgmt.get_donations_gl_accounts()
        self.assertTrue(result["success"])
        self.assertIn("accounts", result["data"])
        self.assertIsInstance(result["data"]["accounts"], list)

    # ----------------------------------------------------------- get_customer_groups

    def test_get_customer_groups_includes_donors(self):
        self._make_customer()  # ensures a leaf "Donors" group exists
        result = mgmt.get_customer_groups()
        self.assertTrue(result["success"])
        names = [g["name"] for g in result["data"]["groups"]]
        self.assertIn("Donors", names)
        for g in result["data"]["groups"]:
            self.assertIn("customer_count", g)

    # ----------------------------------------------------------- check_test_accounts

    def test_check_test_accounts_shape(self):
        result = mgmt.check_test_accounts()
        self.assertTrue(result["success"])
        for key in ("income_accounts", "receivable_accounts", "customer_groups", "all_account_types"):
            self.assertIn(key, result["data"])

    # ----------------------------------------------------------- get_recent_error_logs

    def test_get_recent_error_logs_shape(self):
        # Generate a recent Error Log so the per-error detail path runs.
        frappe.log_error("donor-auto-creation test marker", "Test Marker")
        result = mgmt.get_recent_error_logs()
        self.assertTrue(result["success"])
        self.assertIn("errors", result["data"])
        self.assertIsInstance(result["data"]["errors"], list)

    # ----------------------------------------------------------- test_customer_eligibility

    def test_customer_eligibility_disabled_short_circuits(self):
        # Underlying checker returns {would_create, conditions}; disabled -> stop.
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 0)
        result = mgmt.test_customer_eligibility(
            customer_name=f"NOPE-{frappe.generate_hash(length=6)}", amount=100
        )
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("would_create", data)
        self.assertFalse(data["would_create"])
        self.assertFalse(data["conditions"]["auto_creation_enabled"])

    def test_customer_eligibility_real_customer_reports_conditions(self):
        # Enabled but no GL account -> stops at the account check.
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", None)
        customer = self._make_customer()
        result = mgmt.test_customer_eligibility(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("would_create", data)
        self.assertFalse(data["conditions"]["donations_account_configured"])

    # ----------------------------------------------------------- simulate_auto_creation

    def test_simulate_auto_creation_customer_not_found(self):
        result = mgmt.simulate_auto_creation(
            customer_name=f"GHOST-{frappe.generate_hash(length=6)}", amount=100
        )
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["would_create"])
        self.assertFalse(data["conditions"]["customer_exists"])

    def test_simulate_auto_creation_disabled(self):
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 0)
        customer = self._make_customer()
        result = mgmt.simulate_auto_creation(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["would_create"])
        self.assertFalse(data["conditions"]["auto_creation_enabled"])

    def test_simulate_auto_creation_no_donations_account(self):
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", None)
        customer = self._make_customer()
        result = mgmt.simulate_auto_creation(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["would_create"])
        self.assertTrue(data["conditions"]["auto_creation_enabled"])
        self.assertFalse(data["conditions"]["donations_account_configured"])

    def test_simulate_auto_creation_group_not_eligible(self):
        # Enabled + a (fake) account configured, but the customer's group is not
        # in the eligible list -> simulation stops at the group check.
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", "Donations - FAKE")
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Some Other Group")
        customer = self._make_customer(customer_group="Donors")
        result = mgmt.simulate_auto_creation(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["would_create"])
        self.assertFalse(data["conditions"]["customer_group_eligible"])

    # ----------------------------------------------------------- bulk_process_pending_payments

    def test_bulk_process_pending_payments_requires_account(self):
        # No donations account configured and none passed -> guarded failure,
        # without touching any Payment Entries.
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", None)
        result = mgmt.bulk_process_pending_payments()
        self.assertFalse(result["success"])
        self.assertTrue(result["error"]["errors"])

    def test_bulk_process_pending_payments_no_matching_payments(self):
        # With a non-existent donations account specified, no Payment Entry can
        # match (paid_to == account is never true), so the processor does zero
        # *account-relevant* work.
        #
        # NOTE: result["data"]["processed"] counts every submitted Receive/Customer
        # Payment Entry the processor iterates over (the account match is applied
        # inside the loop, not in the DB filter), so it is NOT zero on a site that
        # has unrelated submitted payments from sibling tests. The meaningful,
        # pollution-proof signals are: nothing was created, and no per-payment
        # detail was recorded (details are only appended for payments whose
        # paid_to matches the account — impossible for a non-existent account).
        result = mgmt.bulk_process_pending_payments(donations_account="Donations - FAKE")
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["created"], 0)
        self.assertEqual(data["errors"], 0)
        self.assertEqual(data["details"], [])
