"""

Tests for automatic donor creation from payment allocations
"""

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

import frappe
from frappe.utils import flt
from verenigingen.tests.setup import ensure_member_test_masters
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorAutoCreation(VereningingenTestCase):
    """Test automatic donor creation from payments allocated to donations GL account"""

    def setUp(self):
        """Set up test data and configuration"""
        super().setUp()

        # Seed the master records this module depends on. CI's run-parallel-tests
        # seeds these via before_tests, but a single-module `run-tests --module`
        # run does not, so on a fresh/snapshot site the setUp below fails:
        # get_default_company() -> IndexError (no Company), and settings.save()
        # -> MandatoryError (Verenigingen Settings.company/creation_user unset).
        # ensure_member_test_masters() seeds ERPNext base masters (Company, CoA,
        # Territory, Customer Groups, Modes of Payment) AND Verenigingen Settings
        # .company + .creation_user. Idempotent / a cheap no-op once seeded.
        ensure_member_test_masters()

        # Enable auto-creation in settings
        self.settings = frappe.get_single("Verenigingen Settings")
        self.original_settings = {
            'auto_create_donors': self.settings.auto_create_donors,
            'donations_gl_account': self.settings.donations_gl_account,
            'donor_customer_groups': self.settings.donor_customer_groups,
            'minimum_donation_amount': self.settings.minimum_donation_amount
        }
        
        # Ensure customer groups referenced by the tests exist
        self._ensure_customer_group("General")
        self._ensure_customer_group("Donors")
        self._ensure_customer_group("Corporate")

        # Set up test configuration
        self.donations_account = self.create_test_account("Donations - TEST", "Income")
        self.settings.auto_create_donors = 1
        self.settings.donations_gl_account = self.donations_account
        self.settings.donor_customer_groups = "Donors,General"
        self.settings.minimum_donation_amount = 10.0
        self.settings.save()
        
    def tearDown(self):
        """Restore original settings"""
        # Restore original settings
        for key, value in self.original_settings.items():
            setattr(self.settings, key, value)
        self.settings.save()
        
        super().tearDown()
        
    def test_payment_entry_creates_donor(self):
        """Test that Payment Entry allocated to donations account creates donor"""
        # Create test customer without existing donor
        customer = self.create_test_customer(
            customer_name="John Donor",
            customer_group="General",
            email_id="john.donor@example.com"
        )
        
        # Verify no donor exists initially
        self.assertFalse(DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name}))
        
        # Create Payment Entry with donation allocation
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=self.donations_account
        )
        
        # Submit payment to trigger hooks
        payment.submit()
        self.run_donor_auto_creation_job(payment)

        # Check that donor was created
        donor = frappe.db.get_value("Donor", {"customer": customer.name}, "*", as_dict=True)
        self.assertIsNotNone(donor, "Donor should be created automatically")
        
        # Verify donor fields
        self.assertEqual(donor['donor_name'], customer.customer_name)
        self.assertEqual(donor['donor_email'], customer.email_id)
        self.assertEqual(donor['customer_sync_status'], "Auto-Created")
        self.assertEqual(donor['created_from_payment'], payment.name)
        self.assertEqual(flt(donor['creation_trigger_amount']), 100.0)
        
        # Track created donor for cleanup
        self.track_doc("Donor", donor['name'])
        
    def test_journal_entry_creates_donor(self):
        """Test that Journal Entry with donations allocation creates donor"""
        # Create test customer
        customer = self.create_test_customer(
            customer_name="Jane Donor",
            customer_group="Donors"
        )
        
        # Create Journal Entry with customer debit and donations credit
        journal_entry = self.create_test_journal_entry([
            {
                'account': self.get_customer_receivable_account(),
                'party_type': 'Customer',
                'party': customer.name,
                'debit': 50.0,
                'credit': 0.0
            },
            {
                'account': self.donations_account,
                'debit': 0.0,
                'credit': 50.0
            }
        ])
        
        # Submit to trigger hooks
        journal_entry.submit()
        
        # Check that donor was created
        donor = frappe.db.get_value("Donor", {"customer": customer.name}, "*", as_dict=True)
        self.assertIsNotNone(donor, "Donor should be created from journal entry")
        
        # Verify donor fields
        self.assertEqual(donor['donor_name'], customer.customer_name)
        self.assertEqual(donor['customer_sync_status'], "Auto-Created")
        self.assertEqual(donor['created_from_payment'], journal_entry.name)
        self.assertEqual(flt(donor['creation_trigger_amount']), 50.0)
        
        self.track_doc("Donor", donor['name'])
        
    def test_minimum_amount_threshold(self):
        """Test that donations below minimum amount don't create donors"""
        # Create customer
        customer = self.create_test_customer(
            customer_name="Small Donor",
            customer_group="General"
        )
        
        # Create payment below minimum threshold (5.0 < 10.0)
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=5.0,
            received_amount=5.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify no donor was created
        self.assertFalse(DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name}))
        
    def test_ineligible_customer_group(self):
        """Test that customers from ineligible groups don't create donors"""
        # Create customer with ineligible group
        customer = self.create_test_customer(
            customer_name="Ineligible Customer",
            customer_group="Corporate"  # Not in "Donors,General"
        )
        
        # Create payment above threshold
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify no donor was created
        self.assertFalse(DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name}))
        
    def test_empty_customer_groups_allows_all(self):
        """Test that empty customer groups configuration allows all groups"""
        # Clear customer groups restriction
        self.settings.donor_customer_groups = ""
        self.settings.save()
        
        # Create customer with any group
        customer = self.create_test_customer(
            customer_name="Any Group Customer",
            customer_group="Corporate"
        )
        
        # Create payment
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify donor was created
        self.assertTrue(DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name}))
        
        # Track for cleanup
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.track_doc("Donor", donor_name)
        
    def test_existing_donor_not_duplicated(self):
        """Test that existing donors are not duplicated"""
        # Create customer and donor
        customer = self.create_test_customer(
            customer_name="Existing Donor Customer",
            customer_group="General"
        )
        
        donor = self.create_test_donor(
            donor_name="Existing Donor",
            customer=customer.name
        )
        
        # Count existing donors
        initial_count = frappe.db.count("Donor", {"customer": customer.name})
        
        # Create payment
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify no additional donor was created
        final_count = frappe.db.count("Donor", {"customer": customer.name})
        self.assertEqual(initial_count, final_count, "Should not create duplicate donor")
        
    def test_auto_creation_disabled(self):
        """Test that auto-creation respects disabled setting"""
        # Disable auto-creation
        self.settings.auto_create_donors = 0
        self.settings.save()
        
        # Create customer and payment
        customer = self.create_test_customer(
            customer_name="Test Customer",
            customer_group="General"
        )
        
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify no donor was created
        self.assertFalse(DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name}))
        
    def test_non_donations_account_ignored(self):
        """Test that payments to non-donations accounts are ignored"""
        # Create different account
        other_account = self.create_test_account("Other Income - TEST", "Income")
        
        # Create customer and payment to non-donations account
        customer = self.create_test_customer(
            customer_name="Other Account Customer",
            customer_group="General"
        )
        
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=other_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify no donor was created
        self.assertFalse(DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name}))
        
    def test_get_auto_creation_settings_api(self):
        """Test the get_auto_creation_settings API endpoint"""
        from verenigingen.utils.donor_auto_creation import get_auto_creation_settings
        
        settings = get_auto_creation_settings()
        
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['donations_gl_account'], self.donations_account)
        self.assertEqual(settings['eligible_customer_groups'], "Donors,General")
        self.assertEqual(settings['minimum_amount'], 10.0)
        
    def test_get_auto_creation_stats_api(self):
        """Test the get_auto_creation_stats API endpoint"""
        from verenigingen.utils.donor_auto_creation import get_auto_creation_stats
        
        # Create a donor via auto-creation first
        customer = self.create_test_customer(
            customer_name="Stats Test Customer",
            customer_group="General"
        )
        
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=75.0,
            received_amount=75.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Track created donor
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.track_doc("Donor", donor_name)
        
        # Get stats
        stats = get_auto_creation_stats()
        
        self.assertGreaterEqual(stats['auto_created_count'], 1)
        self.assertGreaterEqual(stats['total_trigger_amount'], 75.0)
        self.assertIsInstance(stats['recent_creations'], list)
        
    def test_test_auto_creation_conditions_api(self):
        """Test the test_auto_creation_conditions API endpoint"""  
        from verenigingen.utils.donor_auto_creation import test_auto_creation_conditions
        
        # Create test customer
        customer = self.create_test_customer(
            customer_name="Conditions Test Customer",
            customer_group="General"
        )
        
        # Test conditions that should pass
        result = test_auto_creation_conditions(customer.name, 50.0)
        
        self.assertTrue(result['would_create'])
        self.assertTrue(result['conditions']['auto_creation_enabled'])
        self.assertTrue(result['conditions']['donations_account_configured'])
        self.assertTrue(result['conditions']['customer_exists'])
        self.assertTrue(result['conditions']['customer_group_eligible'])
        self.assertTrue(result['conditions']['amount_sufficient'])
        self.assertFalse(result['conditions']['donor_already_exists'])
        
        # Test conditions that should fail (amount too low)
        result_fail = test_auto_creation_conditions(customer.name, 5.0)
        
        self.assertFalse(result_fail['would_create'])
        self.assertFalse(result_fail['conditions']['amount_sufficient'])
        self.assertEqual(result_fail['conditions']['failure_reason'], "Amount 5.0 below minimum 10.0")
        
    def test_customer_sync_after_auto_creation(self):
        """Test that customer sync works properly after auto-creation"""
        # Create customer and trigger auto-creation
        customer = self.create_test_customer(
            customer_name="Sync Test Customer",
            customer_group="General",
            email_id="sync.test@example.com"
        )
        
        payment = self.create_test_payment_entry(
            party=customer.name,
            paid_amount=100.0,
            received_amount=100.0,
            target_account=self.donations_account
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Get created donor
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.track_doc("Donor", donor_name)
        
        # Auto-creation linked a donor onto the customer, bumping its
        # timestamp; reload before editing to avoid a stale-doc conflict.
        customer.reload()
        customer.customer_name = "Updated Sync Test Customer"
        # NOTE: Customer.email_id is a read-only field fetched from the
        # primary contact (fetch_from=customer_primary_contact.email_id), so it
        # cannot be set directly here; only the editable name is updated.
        customer.save()

        # Verify donor was updated through the customer->donor sync hook
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_name, "Updated Sync Test Customer")
        
    def run_donor_auto_creation_job(self, doc):
        """Run the donor auto-creation background job synchronously.

        Production wires Payment/Journal Entry ``on_submit`` to a queued
        background job (``queue_donor_auto_creation_handler``) rather than
        running donor creation inline. In tests the worker never runs, so we
        invoke the exact executor the job would call against the same document.
        """
        from verenigingen.utils.background_jobs import execute_donor_auto_creation

        execute_donor_auto_creation(payment_doc_name=doc.name)

    # Helper methods for test data creation
    def _ensure_customer_group(self, group_name):
        """Create a leaf Customer Group under the root if it doesn't exist."""
        if frappe.db.exists("Customer Group", group_name):
            return group_name
        parent = frappe.db.get_value(
            "Customer Group", {"is_group": 1, "parent_customer_group": ["in", ["", None]]}, "name"
        )
        group = frappe.new_doc("Customer Group")
        group.customer_group_name = group_name
        group.parent_customer_group = parent
        group.is_group = 0
        group.insert(ignore_permissions=True)
        self.track_doc("Customer Group", group.name)
        return group.name

    def create_test_account(self, account_name, account_type):
        """Create a test account (idempotent across runs)."""
        company = self.get_default_company()
        abbr = frappe.db.get_value("Company", company, "abbr")
        # ERPNext appends " - <abbr>" to the saved account name
        full_name = f"{account_name} - {abbr}"
        if frappe.db.exists("Account", full_name):
            return full_name

        # Map shorthand types to valid ERPNext Account "account_type" values
        account_type_alias = {"Income": "Income Account"}
        resolved_account_type = account_type_alias.get(account_type, account_type)

        account = frappe.new_doc("Account")
        account.account_name = account_name
        account.account_type = resolved_account_type
        account.parent_account = self.get_parent_account(account_type)
        account.company = company
        account.insert()
        
        self.track_doc("Account", account.name)
        return account.name
        
    def create_test_customer(self, customer_name, customer_group, email_id=None):
        """Create a test customer"""
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_group = customer_group
        customer.territory = "All Territories"
        if email_id:
            customer.email_id = email_id
        customer.insert()
        
        self.track_doc("Customer", customer.name)
        return customer
        
    def create_test_donor(self, donor_name, customer=None):
        """Create a test donor"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = donor_name
        donor.donor_type = "Individual"
        if customer:
            donor.customer = customer
        donor.insert()
        
        self.track_doc("Donor", donor.name)
        return donor
        
    def create_test_payment_entry(self, party, paid_amount, received_amount, target_account):
        """Create a test payment entry"""
        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.company = self.get_default_company()
        payment.party_type = "Customer"
        payment.party = party
        payment.paid_amount = paid_amount
        payment.received_amount = received_amount
        # For a "Receive" payment, paid_from must be the party's Receivable
        # account; the funds are deposited to the donations (target) account.
        payment.paid_from = self.get_customer_receivable_account()
        payment.paid_to = target_account
        # Single-currency (company base) test accounts: exchange rates are 1:1
        payment.source_exchange_rate = 1
        payment.target_exchange_rate = 1
        # The donations account is a P&L account and needs a Cost Center on submit
        payment.cost_center = self.get_default_cost_center()
        payment.insert()
        
        self.track_doc("Payment Entry", payment.name)
        return payment
        
    def create_test_journal_entry(self, accounts):
        """Create a test journal entry"""
        company = self.get_default_company()
        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.voucher_type = "Journal Entry"
        journal_entry.company = company
        journal_entry.posting_date = frappe.utils.today()

        cost_center = self.get_default_cost_center()
        for account_data in accounts:
            account_data.setdefault("cost_center", cost_center)
            # JE child rows need the account-currency amounts populated too
            if "debit" in account_data:
                account_data.setdefault("debit_in_account_currency", account_data["debit"])
            if "credit" in account_data:
                account_data.setdefault("credit_in_account_currency", account_data["credit"])
            journal_entry.append("accounts", account_data)

        journal_entry.insert()
        
        self.track_doc("Journal Entry", journal_entry.name)
        return journal_entry
        
    def get_parent_account(self, account_type):
        """Get parent (group) account for test accounts.

        The standard ERPNext Chart of Accounts only sets root_type on the
        top-level group accounts (account_type is blank on them), so we map
        the requested account_type to a root_type and pick an existing group.
        """
        company = self.get_default_company()

        root_type_map = {
            "Income": "Income",
            "Cash": "Asset",
            "Bank": "Asset",
            "Receivable": "Asset",
            "Payable": "Liability",
            "Expense Account": "Expense",
        }
        root_type = root_type_map.get(account_type, "Asset")

        parent = frappe.db.get_value(
            "Account",
            {"root_type": root_type, "is_group": 1, "company": company},
            "name",
            order_by="lft",
        )
        return parent
        
    def get_default_cost_center(self):
        """Get a non-group cost center for the default company."""
        company = self.get_default_company()
        cost_center = frappe.db.get_value("Company", company, "cost_center")
        if cost_center:
            return cost_center
        return frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )

    def get_default_company(self):
        """Get default company for tests"""
        return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_all("Company", limit=1)[0].name
        
    def get_cash_account(self):
        """Get cash account for payments"""
        company = self.get_default_company()
        account = frappe.db.get_value("Account", 
            {"account_type": "Cash", "is_group": 0, "company": company}, 
            "name"
        )
        if account:
            return account
        # Create if doesn't exist
        return self.create_test_account("Cash - TEST", "Cash")
        
    def get_customer_receivable_account(self):
        """Get customer receivable account"""
        company = self.get_default_company()
        account = frappe.db.get_value("Account", 
            {"account_type": "Receivable", "is_group": 0, "company": company}, 
            "name"
        )
        if account:
            return account
        # Create if doesn't exist  
        return self.create_test_account("Debtors - TEST", "Receivable")