"""
Real-integration tests for
``verenigingen/services/member/donor/donor_auto_creation.py``.

This module auto-creates Donor records when payments land on the donations GL
account from an unknown Customer. Tests drive real Customer / Donor / Verenigingen
Settings / Account records (no business-logic mocking) as Administrator.

Covered behaviour:
- is_customer_group_eligible: all-allowed, in-list, not-in-list
- has_existing_donor: by donor.customer link and by customer.donor back-ref
- create_donor_from_customer: field mapping (Individual/Organization), customer
  back-link, placeholder-email generation, idempotency on existing donor
- test_auto_creation_conditions: each failure branch + the all-conditions-met
  success path
- get_auto_creation_stats: counts/sum over auto-created donors
- process_journal_entry: end-to-end donor creation from a JE customer debit

Run:
  bench --site test_site_4 run-tests --app verenigingen \
    --module verenigingen.tests.services.test_donor_auto_creation
"""

import frappe

from verenigingen.services.member.donor import donor_auto_creation as dac
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestDonorAutoCreation(EnhancedTestCase):
    """Exercise donor auto-creation helpers with real records."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._settings_backup = {}
        self._company = self._ensure_company()
        self._donations_account = self._ensure_donations_account()

    def tearDown(self):
        self._restore_settings()
        super().tearDown()

    # ----------------------------------------------------------- setup helpers

    @staticmethod
    def _ensure_company():
        # Prefer a company that already has an Income account tree so the
        # factory's income-account helper finds a valid parent. Picking an
        # arbitrary company can land on a bare one (e.g. a leftover migration
        # test company with no Chart of Accounts), where account creation fails
        # with a parent_account MandatoryError — green on dev sites that happen
        # to order a good company first, red in CI.
        company = frappe.db.get_value(
            "Account", {"root_type": "Income", "is_group": 1}, "company", order_by="lft"
        )
        if not company:
            company = frappe.db.get_value("Company", {}, "name")
        if not company:
            raise RuntimeError("Test site has no Company with an Income account tree")
        return company

    def _ensure_donations_account(self):
        # Reuse the factory's income-account helper for a real, leaf GL account.
        return self._get_or_create_income_account(self._company)

    def _configure_settings(self, **overrides):
        """Set Verenigingen Settings auto-creation fields, remembering originals."""
        settings = frappe.get_single("Verenigingen Settings")
        values = {
            "auto_create_donors": 1,
            "donations_gl_account": self._donations_account,
            "minimum_donation_amount": 10,
            "donor_customer_groups": "",
        }
        values.update(overrides)
        for field, value in values.items():
            if field not in self._settings_backup:
                self._settings_backup[field] = settings.get(field)
            settings.set(field, value)
        # Runs as Administrator (full perms on the Single), so no bypass needed.
        settings.save()
        return frappe.get_single("Verenigingen Settings")

    def _restore_settings(self):
        if not self._settings_backup:
            return
        settings = frappe.get_single("Verenigingen Settings")
        for field, value in self._settings_backup.items():
            settings.set(field, value)
        settings.save()
        self._settings_backup = {}

    def _make_customer(self, **kwargs):
        kwargs.setdefault("customer_group", "Individual")
        return self.factory.create_test_customer(**kwargs)

    def _track_donor(self, donor_name):
        if donor_name and frappe.db.exists("Donor", donor_name):
            self.track_doc("Donor", donor_name)

    # ----------------------------------------------------------- is_customer_group_eligible

    def test_group_eligible_when_no_groups_configured(self):
        settings = frappe._dict(donor_customer_groups="")
        self.assertTrue(dac.is_customer_group_eligible("Individual", settings))

    def test_group_eligible_when_in_list(self):
        settings = frappe._dict(donor_customer_groups="Individual, Commercial")
        self.assertTrue(dac.is_customer_group_eligible("Commercial", settings))

    def test_group_ineligible_when_not_in_list(self):
        settings = frappe._dict(donor_customer_groups="Commercial")
        self.assertFalse(dac.is_customer_group_eligible("Individual", settings))

    # ----------------------------------------------------------- has_existing_donor

    def test_has_existing_donor_by_donor_customer_link(self):
        customer = self._make_customer()
        self.assertFalse(dac.has_existing_donor(customer.name))
        donor = self.create_test_donor(
            donor_name="Linked", donor_email=f"linked.{frappe.generate_hash(length=6)}@example.com"
        )
        frappe.db.set_value("Donor", donor.name, "customer", customer.name)
        self.assertTrue(dac.has_existing_donor(customer.name))

    def test_has_existing_donor_by_customer_donor_backref(self):
        customer = self._make_customer()
        donor = self.create_test_donor(
            donor_name="Backref", donor_email=f"backref.{frappe.generate_hash(length=6)}@example.com"
        )
        frappe.db.set_value("Customer", customer.name, "donor", donor.name)
        self.assertTrue(dac.has_existing_donor(customer.name))

    # ----------------------------------------------------------- create_donor_from_customer

    def test_create_donor_from_individual_customer(self):
        customer = self._make_customer(
            customer_type="Individual", email_id=f"indiv.{frappe.generate_hash(length=6)}@example.com"
        )
        donor_name = dac.create_donor_from_customer(customer, 50.0, "PE-TEST-1")
        self.assertTrue(donor_name)
        self._track_donor(donor_name)
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_name, customer.customer_name)
        self.assertEqual(donor.donor_type, "Individual")
        self.assertEqual(donor.donor_email, customer.email_id)
        self.assertEqual(donor.customer, customer.name)
        self.assertEqual(donor.customer_sync_status, "Auto-Created")
        self.assertEqual(float(donor.creation_trigger_amount), 50.0)
        self.assertEqual(donor.created_from_payment, "PE-TEST-1")
        # Customer back-link is set.
        self.assertEqual(frappe.db.get_value("Customer", customer.name, "donor"), donor_name)

    def test_create_donor_from_company_customer_is_organization(self):
        customer = self._make_customer(
            customer_type="Company",
            customer_group="Commercial",
            email_id=f"org.{frappe.generate_hash(length=6)}@example.com",
        )
        donor_name = dac.create_donor_from_customer(customer, 75.0, "JE-TEST-1")
        self.assertTrue(donor_name)
        self._track_donor(donor_name)
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_type, "Organization")

    def test_create_donor_generates_placeholder_email_when_missing(self):
        # Customer without email -> a deterministic placeholder email is built.
        customer = self._make_customer(customer_type="Individual")
        self.assertFalse(customer.email_id)
        donor_name = dac.create_donor_from_customer(customer, 30.0, "PE-TEST-2")
        self.assertTrue(donor_name)
        self._track_donor(donor_name)
        donor = frappe.get_doc("Donor", donor_name)
        self.assertTrue(donor.donor_email.endswith("@example.com"))
        self.assertIn(customer.name.lower().replace(" ", "."), donor.donor_email)

    def test_create_donor_idempotent_for_existing_donor(self):
        customer = self._make_customer(email_id=f"dup.{frappe.generate_hash(length=6)}@example.com")
        first = dac.create_donor_from_customer(customer, 40.0, "PE-TEST-3")
        self.assertTrue(first)
        self._track_donor(first)
        # Second call detects the existing donor (defensive has_existing_donor
        # check) and returns None instead of creating a duplicate.
        second = dac.create_donor_from_customer(customer, 40.0, "PE-TEST-4")
        self.assertIsNone(second)

    # ----------------------------------------------------------- test_auto_creation_conditions

    def test_conditions_disabled(self):
        self._configure_settings(auto_create_donors=0)
        customer = self._make_customer()
        result = dac.test_auto_creation_conditions(customer.name, 100)
        self.assertFalse(result["would_create"])
        self.assertEqual(result["conditions"]["failure_reason"], "Auto-creation is disabled")

    def test_conditions_no_gl_account(self):
        self._configure_settings(donations_gl_account=None)
        customer = self._make_customer()
        result = dac.test_auto_creation_conditions(customer.name, 100)
        self.assertFalse(result["would_create"])
        self.assertEqual(result["conditions"]["failure_reason"], "Donations GL account not configured")

    def test_conditions_customer_missing(self):
        self._configure_settings()
        result = dac.test_auto_creation_conditions("Customer-DOES-NOT-EXIST", 100)
        self.assertFalse(result["would_create"])
        self.assertIn("does not exist", result["conditions"]["failure_reason"])

    def test_conditions_group_not_eligible(self):
        self._configure_settings(donor_customer_groups="Commercial")
        customer = self._make_customer(customer_group="Individual")
        result = dac.test_auto_creation_conditions(customer.name, 100)
        self.assertFalse(result["would_create"])
        self.assertIn("not eligible", result["conditions"]["failure_reason"])

    def test_conditions_amount_below_minimum(self):
        self._configure_settings(minimum_donation_amount=100)
        customer = self._make_customer()
        result = dac.test_auto_creation_conditions(customer.name, 5)
        self.assertFalse(result["would_create"])
        self.assertIn("below minimum", result["conditions"]["failure_reason"])

    def test_conditions_donor_already_exists(self):
        self._configure_settings()
        customer = self._make_customer()
        donor = self.create_test_donor(
            donor_name="Exists", donor_email=f"exists.{frappe.generate_hash(length=6)}@example.com"
        )
        frappe.db.set_value("Customer", customer.name, "donor", donor.name)
        result = dac.test_auto_creation_conditions(customer.name, 100)
        self.assertFalse(result["would_create"])
        self.assertEqual(result["conditions"]["failure_reason"], "Donor already exists for this customer")

    def test_conditions_all_met(self):
        self._configure_settings(minimum_donation_amount=10)
        customer = self._make_customer()
        result = dac.test_auto_creation_conditions(customer.name, 100)
        self.assertTrue(result["would_create"])
        self.assertTrue(result["conditions"]["all_conditions_met"])

    # ----------------------------------------------------------- get_auto_creation_stats

    def test_get_auto_creation_stats_counts_auto_created(self):
        customer = self._make_customer(email_id=f"stat.{frappe.generate_hash(length=6)}@example.com")
        donor_name = dac.create_donor_from_customer(customer, 60.0, "PE-STAT-1")
        self._track_donor(donor_name)
        stats = dac.get_auto_creation_stats()
        self.assertIn("auto_created_count", stats)
        self.assertGreaterEqual(stats["auto_created_count"], 1)
        # Our donor appears in the recent list.
        names = [r["name"] for r in stats["recent_creations"]]
        self.assertIn(donor_name, names)
        self.assertGreaterEqual(float(stats["total_trigger_amount"]), 60.0)

    # ----------------------------------------------------------- process_journal_entry

    def test_process_journal_entry_creates_donor(self):
        """A JE crediting the donations account and debiting a customer creates a donor."""
        self._configure_settings(minimum_donation_amount=10)
        settings = frappe.get_single("Verenigingen Settings")
        customer = self._make_customer(email_id=f"je.{frappe.generate_hash(length=6)}@example.com")
        receivable = frappe.db.get_value("Company", self._company, "default_receivable_account")
        self.assertTrue(receivable, "company needs a receivable account for the JE")

        # Build an in-memory JE shape with the accounts the processor inspects.
        je = frappe._dict(
            name="JE-INMEM-1",
            accounts=[
                frappe._dict(
                    account=self._donations_account,
                    credit=80.0,
                    debit=0.0,
                    party_type=None,
                    party=None,
                ),
                frappe._dict(
                    account=receivable,
                    credit=0.0,
                    debit=80.0,
                    party_type="Customer",
                    party=customer.name,
                ),
            ],
        )
        dac.process_journal_entry(je, settings)

        # A donor now exists for this customer, marked Auto-Created.
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.assertTrue(donor_name, "process_journal_entry should have created a donor")
        self._track_donor(donor_name)
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.customer_sync_status, "Auto-Created")
        self.assertEqual(float(donor.creation_trigger_amount), 80.0)

    def test_process_journal_entry_skips_below_minimum(self):
        self._configure_settings(minimum_donation_amount=1000)
        settings = frappe.get_single("Verenigingen Settings")
        customer = self._make_customer(email_id=f"jelow.{frappe.generate_hash(length=6)}@example.com")
        receivable = frappe.db.get_value("Company", self._company, "default_receivable_account")
        je = frappe._dict(
            name="JE-INMEM-2",
            accounts=[
                frappe._dict(
                    account=self._donations_account, credit=50.0, debit=0.0, party_type=None, party=None
                ),
                frappe._dict(
                    account=receivable, credit=0.0, debit=50.0, party_type="Customer", party=customer.name
                ),
            ],
        )
        dac.process_journal_entry(je, settings)
        # Below the 1000 minimum -> no donor created.
        self.assertIsNone(frappe.db.get_value("Donor", {"customer": customer.name}, "name"))
