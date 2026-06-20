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

    # ----------------------------------------------------- helpers (GL infra)

    def _income_account(self):
        """A real income GL account on this site, or None if the test site has
        none provisioned (Company-less fresh site)."""
        infra = self.ensure_erpnext_infrastructure()
        return infra.get("income_account"), infra.get("company"), infra.get("cash_account")

    def _infra(self):
        return self.ensure_erpnext_infrastructure()

    # --------------------------------------------- get_donations_gl_accounts (real data)

    def test_get_donations_gl_accounts_returns_real_income_accounts(self):
        """REGRESSION: the endpoint must surface the site's income accounts.

        ERPNext stores income accounts under account_type == "Income Account"
        (there is no "Income" account_type). Before the fix the endpoint filtered
        on "Income" and therefore returned an EMPTY list on every site that has
        income accounts, silently breaking the donations-account selector.
        """
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        result = mgmt.get_donations_gl_accounts()
        self.assertTrue(result["success"])
        names = [a["name"] for a in result["data"]["accounts"]]
        self.assertIn(
            income_account,
            names,
            "get_donations_gl_accounts dropped a real Income Account",
        )

    def test_check_test_accounts_lists_income_accounts(self):
        """REGRESSION mirror: check_test_accounts' income_accounts list must
        include a real income account (same wrong "Income" filter as above)."""
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        result = mgmt.check_test_accounts()
        self.assertTrue(result["success"])
        income_names = [a["name"] for a in result["data"]["income_accounts"]]
        self.assertIn(income_account, income_names)

    # --------------------------------------------- simulate_auto_creation happy path

    def test_simulate_auto_creation_all_conditions_met(self):
        """The full 'would_create' branch: enabled + real GL account + eligible
        group + sufficient amount + no existing donor -> would_create True with a
        populated donor_data preview (no Donor is actually written)."""
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        customer = self._make_customer(customer_group="Donors")
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", income_account)
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Donors")
        frappe.db.set_single_value("Verenigingen Settings", "minimum_donation_amount", 10)

        donor_count_before = frappe.db.count("Donor")
        result = mgmt.simulate_auto_creation(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertTrue(data["would_create"])
        self.assertTrue(data["conditions"]["customer_group_eligible"])
        self.assertTrue(data["conditions"]["amount_sufficient"])
        self.assertFalse(data["conditions"]["donor_already_exists"])
        # Preview reflects the customer; trigger amount echoes the input.
        self.assertEqual(data["donor_data"]["customer"], customer.name)
        self.assertEqual(float(data["donor_data"]["creation_trigger_amount"]), 100.0)
        self.assertEqual(data["donor_data"]["customer_sync_status"], "Auto-Created")
        # Simulation must NOT persist a Donor.
        self.assertEqual(frappe.db.count("Donor"), donor_count_before)

    def test_simulate_auto_creation_amount_below_minimum(self):
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        customer = self._make_customer(customer_group="Donors")
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", income_account)
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Donors")
        frappe.db.set_single_value("Verenigingen Settings", "minimum_donation_amount", 500)
        result = mgmt.simulate_auto_creation(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["would_create"])
        self.assertFalse(data["conditions"]["amount_sufficient"])

    def test_simulate_auto_creation_donor_already_exists(self):
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        customer = self._make_customer(customer_group="Donors")
        # Pre-create a Donor linked to the customer so the existence guard trips.
        donor = frappe.new_doc("Donor")
        donor.donor_name = customer.customer_name
        donor.donor_type = "Individual"
        donor.donor_email = f"existing.{frappe.generate_hash(length=6)}@example.com"
        donor.customer = customer.name
        donor.flags.ignore_customer_sync = True
        donor.insert()
        self.track_doc("Donor", donor.name)

        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", income_account)
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Donors")
        frappe.db.set_single_value("Verenigingen Settings", "minimum_donation_amount", 10)
        result = mgmt.simulate_auto_creation(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertFalse(data["would_create"])
        self.assertTrue(data["conditions"]["donor_already_exists"])

    # --------------------------------------------- test_customer_eligibility happy path

    def test_customer_eligibility_all_conditions_pass(self):
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        customer = self._make_customer(customer_group="Donors")
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", income_account)
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Donors")
        frappe.db.set_single_value("Verenigingen Settings", "minimum_donation_amount", 10)
        result = mgmt.test_customer_eligibility(customer_name=customer.name, amount=100)
        self.assertTrue(result["success"])
        data = result["data"]
        self.assertIn("would_create", data)
        self.assertTrue(data["conditions"]["auto_creation_enabled"])
        self.assertTrue(data["conditions"]["donations_account_configured"])

    # --------------------------------------------- update settings (real save round-trip)

    def test_update_auto_creation_settings_persists_gl_account(self):
        income_account, _company, _cash = self._income_account()
        if not income_account:
            self.skipTest("No income account provisioned on this site")
        self._require_saveable_settings()
        result = mgmt.update_auto_creation_settings(
            enabled=1,
            donations_gl_account=income_account,
            eligible_customer_groups="Donors",
            minimum_amount=42,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["donations_gl_account"], income_account)
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "donations_gl_account"),
            income_account,
        )

    # --------------------------------------------- dashboard with configured groups

    def test_dashboard_eligible_groups_reflects_configured_groups(self):
        # When donor_customer_groups is set, the dashboard reports per-group
        # customer counts instead of the "All Customer Groups" fallback.
        self._make_customer(customer_group="Donors")
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Donors")
        result = mgmt.get_auto_creation_dashboard()
        self.assertTrue(result["success"])
        groups = result["data"]["eligible_groups"]
        names = [g["name"] for g in groups]
        self.assertIn("Donors", names)
        self.assertNotIn("All Customer Groups", names)
        for g in groups:
            self.assertIn("customer_count", g)

    def test_dashboard_eligible_groups_fallback_when_unset(self):
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", None)
        result = mgmt.get_auto_creation_dashboard()
        self.assertTrue(result["success"])
        names = [g["name"] for g in result["data"]["eligible_groups"]]
        self.assertEqual(names, ["All Customer Groups"])

    # --------------------------------------------- bulk processing real create path

    def test_bulk_process_creates_donor_from_matching_payment(self):
        """End-to-end: a submitted Receive Payment Entry whose paid_to is the
        donations account, for an eligible customer over the minimum, results in
        a newly created Donor."""
        infra = self._infra()
        income_account = infra.get("income_account")
        company = infra.get("company")
        debtors_account = infra.get("debtors_account")
        cost_center = infra.get("cost_center")
        if not income_account or not debtors_account:
            self.skipTest("No GL infrastructure provisioned on this site")
        customer = self._make_customer(customer_group="Donors")
        frappe.db.set_single_value("Verenigingen Settings", "auto_create_donors", 1)
        frappe.db.set_single_value("Verenigingen Settings", "donations_gl_account", income_account)
        frappe.db.set_single_value("Verenigingen Settings", "donor_customer_groups", "Donors")
        frappe.db.set_single_value("Verenigingen Settings", "minimum_donation_amount", 10)

        # A "Receive" payment from a Customer takes paid_from = receivable
        # (Debtors); production matches on paid_to, so the donations income
        # account is the destination here.
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Receive"
        pe.party_type = "Customer"
        pe.party = customer.name
        pe.company = company
        pe.paid_amount = 100
        pe.received_amount = 100
        pe.source_exchange_rate = 1
        pe.target_exchange_rate = 1
        pe.paid_from = debtors_account
        pe.paid_to = income_account
        if cost_center:
            pe.cost_center = cost_center
        pe.posting_date = frappe.utils.today()
        pe.reference_no = "DON-TEST"
        pe.reference_date = frappe.utils.today()
        pe.insert()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)

        result = mgmt.bulk_process_pending_payments(
            donations_account=income_account, date_from=frappe.utils.today()
        )
        self.assertTrue(result["success"])
        data = result["data"]
        # Our payment must have produced exactly one created donor with a detail row.
        self.assertGreaterEqual(data["created"], 1)
        created_for_ours = [
            d for d in data["details"] if d.get("payment") == pe.name and d.get("status") == "created"
        ]
        self.assertEqual(len(created_for_ours), 1)
        donor_name = created_for_ours[0]["donor"]
        self.assertTrue(frappe.db.exists("Donor", donor_name))
        self.track_doc("Donor", donor_name)
        self.assertEqual(frappe.db.get_value("Donor", donor_name, "customer"), customer.name)
