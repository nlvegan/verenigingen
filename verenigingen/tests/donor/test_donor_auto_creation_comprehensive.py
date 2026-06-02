"""

Comprehensive tests for donor auto-creation functionality with test persona
Following CLAUDE.md requirements for Frappe ORM compliance and proper test patterns
"""

from verenigingen.utils.validation_utilities import DocumentExistenceValidator

import frappe
from frappe.utils import flt, now, add_days, getdate
from verenigingen.tests.utils.base import VereningingenTestCase


class TestDonorAutoCreationComprehensive(VereningingenTestCase):
    """
    Comprehensive test suite for donor auto-creation functionality
    Uses proper Frappe ORM patterns and includes test persona
    """
    
    @classmethod
    def setUpClass(cls):
        """One-time setup for test class"""
        super().setUpClass()
        cls.test_persona = DonorAutoCreationTestPersona()
    
    def setUp(self):
        """Set up test data for each test"""
        super().setUp()
        
        # Store original settings for restoration
        self.settings = frappe.get_single("Verenigingen Settings")
        self.original_settings = {
            'auto_create_donors': self.settings.auto_create_donors,
            'donations_gl_account': self.settings.donations_gl_account,
            'donor_customer_groups': self.settings.donor_customer_groups,
            'minimum_donation_amount': self.settings.minimum_donation_amount
        }
        
        # Set up test environment using persona
        self.test_data = self.test_persona.create_test_environment(self)
        
    def tearDown(self):
        """Clean up after each test"""
        # The persona and individual tests save Verenigingen Settings, so the
        # cached handle is stale; reload before restoring to avoid a conflict.
        self.settings.reload()
        for key, value in self.original_settings.items():
            setattr(self.settings, key, value)
        self.settings.save()

        super().tearDown()

    def run_donor_auto_creation_job(self, doc):
        """Run the donor auto-creation background job synchronously.

        Production wires Payment Entry ``on_submit`` to a queued background job
        rather than running donor creation inline; in tests the worker never
        runs, so we invoke the exact executor the job would call.
        """
        from verenigingen.utils.background_jobs import execute_donor_auto_creation

        execute_donor_auto_creation(payment_doc_name=doc.name)

    def test_payment_entry_auto_creation_success(self):
        """Test successful donor creation from Payment Entry"""
        # Create customer without existing donor
        customer = self.test_persona.create_eligible_customer(self)
        
        # Create Payment Entry to donations account
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 150.0, self.test_data['donations_account']
        )
        
        # Submit to trigger auto-creation
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify donor was created
        donor = frappe.db.get_value("Donor", {"customer": customer.name}, "*", as_dict=True)
        self.assertIsNotNone(donor, "Donor should be auto-created from payment entry")
        
        # Verify donor fields are correct
        self.assertEqual(donor['donor_name'], customer.customer_name)
        self.assertEqual(donor['donor_email'], customer.email_id)
        self.assertEqual(donor['customer_sync_status'], "Auto-Created")
        self.assertEqual(donor['created_from_payment'], payment.name)
        self.assertEqual(flt(donor['creation_trigger_amount']), 150.0)
        self.assertEqual(donor['donor_type'], "Individual")
        
        # Track for cleanup
        self.track_doc("Donor", donor['name'])
    
    def test_journal_entry_auto_creation_success(self):
        """Test successful donor creation from Journal Entry"""
        customer = self.test_persona.create_eligible_customer(self)
        
        # Create Journal Entry above the configured minimum (100.0)
        journal_entry = self.test_persona.create_donation_journal_entry(
            self, customer.name, 150.0,
            self.test_data['donations_account'],
            self.test_data['receivable_account']
        )

        journal_entry.submit()

        # Verify donor creation
        donor = frappe.db.get_value("Donor", {"customer": customer.name}, "*", as_dict=True)
        self.assertIsNotNone(donor, "Donor should be auto-created from journal entry")
        self.assertEqual(flt(donor['creation_trigger_amount']), 150.0)
        self.assertEqual(donor['created_from_payment'], journal_entry.name)
        
        self.track_doc("Donor", donor['name'])
    
    def test_minimum_amount_threshold_blocks_creation(self):
        """Test that donations below minimum threshold don't create donors"""
        customer = self.test_persona.create_eligible_customer(self)
        
        # Create payment below minimum (50.0 < 100.0)
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 50.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify NO donor was created
        donor_exists = DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name})
        self.assertFalse(donor_exists, "Donor should NOT be created below minimum threshold")
    
    def test_ineligible_customer_group_blocks_creation(self):
        """Test that customers from ineligible groups don't create donors"""
        # Create customer with ineligible group
        customer = self.test_persona.create_ineligible_customer(self)
        
        # Create payment above threshold
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 200.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify NO donor was created
        donor_exists = DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name})
        self.assertFalse(donor_exists, "Donor should NOT be created for ineligible customer group")
    
    def test_existing_donor_prevents_duplication(self):
        """Test that existing donors are not duplicated"""
        customer = self.test_persona.create_eligible_customer(self)
        
        # Create existing donor manually
        existing_donor = self.test_persona.create_donor_for_customer(self, customer)
        
        # Count donors before payment
        initial_count = frappe.db.count("Donor", {"customer": customer.name})
        
        # Create payment that would normally trigger creation
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 200.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify no additional donor was created
        final_count = frappe.db.count("Donor", {"customer": customer.name})
        self.assertEqual(initial_count, final_count, "Should not create duplicate donor")
    
    def test_disabled_auto_creation_blocks_creation(self):
        """Test that disabled auto-creation prevents donor creation"""
        # Disable auto-creation (reload first: persona already saved settings)
        self.settings.reload()
        self.settings.auto_create_donors = 0
        self.settings.save()
        
        customer = self.test_persona.create_eligible_customer(self)
        
        # Create payment
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 200.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify NO donor was created
        donor_exists = DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name})
        self.assertFalse(donor_exists, "Donor should NOT be created when auto-creation is disabled")
    
    def test_non_donations_account_ignored(self):
        """Test that payments to non-donations accounts are ignored"""
        customer = self.test_persona.create_eligible_customer(self)
        
        # Create payment to different account
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 200.0, self.test_data['other_income_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify NO donor was created
        donor_exists = DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name})
        self.assertFalse(donor_exists, "Donor should NOT be created for non-donations account")
    
    def test_empty_customer_groups_allows_all(self):
        """Test that empty customer groups configuration allows all groups"""
        # Clear customer groups restriction (reload: persona already saved settings)
        self.settings.reload()
        self.settings.donor_customer_groups = ""
        self.settings.save()
        
        # Create customer with any group
        customer = self.test_persona.create_customer_with_group(self, "Corporate Donors")
        
        # Create payment
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 200.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Verify donor WAS created (any group allowed)
        donor_exists = DocumentExistenceValidator.check_document_exists("Donor", {"customer": customer.name})
        self.assertTrue(donor_exists, "Donor should be created when all groups are allowed")
        
        # Track for cleanup
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.track_doc("Donor", donor_name)
    
    def test_customer_sync_after_auto_creation(self):
        """Test that customer sync works properly after auto-creation"""
        customer = self.test_persona.create_eligible_customer(self)
        
        # Trigger auto-creation
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 200.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Get created donor
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.track_doc("Donor", donor_name)
        
        # Auto-creation linked a donor onto the customer, bumping its
        # timestamp; reload before editing to avoid a stale-doc conflict.
        customer.reload()
        customer.customer_name = "Updated Test Customer"
        # NOTE: Customer.email_id is a read-only field fetched from the primary
        # contact (fetch_from=customer_primary_contact.email_id) and cannot be
        # set directly; only the editable name is updated here.
        customer.save()

        # Verify donor was updated through the customer->donor sync hook
        donor = frappe.get_doc("Donor", donor_name)
        self.assertEqual(donor.donor_name, "Updated Test Customer")
    
    def test_api_get_auto_creation_settings(self):
        """Test the get_auto_creation_settings API endpoint"""
        from verenigingen.utils.donor_auto_creation import get_auto_creation_settings
        
        settings = get_auto_creation_settings()
        
        self.assertIsInstance(settings, dict)
        self.assertIn('enabled', settings)
        self.assertIn('donations_gl_account', settings)
        self.assertIn('eligible_customer_groups', settings)
        self.assertIn('minimum_amount', settings)
        
        # Verify values match test configuration
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['donations_gl_account'], self.test_data['donations_account'])
        self.assertEqual(settings['minimum_amount'], 100.0)
    
    def test_api_get_auto_creation_stats(self):
        """Test the get_auto_creation_stats API endpoint"""
        from verenigingen.utils.donor_auto_creation import get_auto_creation_stats
        
        # Create a donor via auto-creation first
        customer = self.test_persona.create_eligible_customer(self)
        payment = self.test_persona.create_donation_payment_entry(
            self, customer.name, 150.0, self.test_data['donations_account']
        )
        payment.submit()
        self.run_donor_auto_creation_job(payment)
        
        # Track created donor
        donor_name = frappe.db.get_value("Donor", {"customer": customer.name}, "name")
        self.track_doc("Donor", donor_name)
        
        # Get stats
        stats = get_auto_creation_stats()
        
        self.assertIsInstance(stats, dict)
        self.assertIn('auto_created_count', stats)
        self.assertIn('total_trigger_amount', stats)
        self.assertIn('recent_creations', stats)
        
        self.assertGreaterEqual(stats['auto_created_count'], 1)
        self.assertGreaterEqual(stats['total_trigger_amount'], 150.0)
        self.assertIsInstance(stats['recent_creations'], list)
    
    def test_api_test_auto_creation_conditions(self):
        """Test the test_auto_creation_conditions API endpoint"""
        from verenigingen.utils.donor_auto_creation import test_auto_creation_conditions
        
        customer = self.test_persona.create_eligible_customer(self)
        
        # Test conditions that should pass
        result = test_auto_creation_conditions(customer.name, 150.0)
        
        self.assertIsInstance(result, dict)
        self.assertIn('would_create', result)
        self.assertIn('conditions', result)
        
        self.assertTrue(result['would_create'])
        self.assertTrue(result['conditions']['auto_creation_enabled'])
        self.assertTrue(result['conditions']['donations_account_configured'])
        self.assertTrue(result['conditions']['customer_exists'])
        self.assertTrue(result['conditions']['customer_group_eligible'])
        self.assertTrue(result['conditions']['amount_sufficient'])
        self.assertFalse(result['conditions']['donor_already_exists'])
        
        # Test conditions that should fail (amount too low)
        result_fail = test_auto_creation_conditions(customer.name, 50.0)
        
        self.assertFalse(result_fail['would_create'])
        self.assertFalse(result_fail['conditions']['amount_sufficient'])
        self.assertIn('failure_reason', result_fail['conditions'])
    
    def test_management_api_get_dashboard(self):
        """Test the management dashboard API"""
        from verenigingen.api.donor_auto_creation_management import get_auto_creation_dashboard
        
        dashboard = get_auto_creation_dashboard()
        # @standard_api wraps the payload in a {success, data, meta} envelope
        if isinstance(dashboard, dict) and "data" in dashboard:
            dashboard = dashboard["data"]

        self.assertIsInstance(dashboard, dict)
        self.assertIn('settings', dashboard)
        self.assertIn('statistics', dashboard)
        self.assertIn('recent_creations', dashboard)
        self.assertIn('eligible_groups', dashboard)
        
        # Verify settings structure
        settings = dashboard['settings']
        self.assertIn('enabled', settings)
        self.assertIn('donations_gl_account', settings)
        self.assertIn('minimum_amount', settings)
    
    def test_management_api_update_settings(self):
        """Test the update settings API"""
        from verenigingen.api.donor_auto_creation_management import update_auto_creation_settings
        
        # Update settings via API
        result = update_auto_creation_settings(
            enabled=True,
            donations_gl_account=self.test_data['donations_account'],
            eligible_customer_groups="Test Group,Another Group",
            minimum_amount=250.0
        )
        
        self.assertIsInstance(result, dict)
        self.assertTrue(result.get('success'))
        # @standard_api returns the updated settings under the "data" envelope key
        self.assertIn('data', result)
        self.assertIn('enabled', result['data'])

        # Verify settings were actually updated
        updated_settings = frappe.get_single("Verenigingen Settings")
        self.assertTrue(updated_settings.auto_create_donors)
        self.assertEqual(updated_settings.donor_customer_groups, "Test Group,Another Group")
        self.assertEqual(flt(updated_settings.minimum_donation_amount), 250.0)
    
    def test_complex_journal_entry_multi_customer(self):
        """Test complex Journal Entry with multiple customers"""
        customer1 = self.test_persona.create_eligible_customer(self, suffix="1")
        customer2 = self.test_persona.create_eligible_customer(self, suffix="2")
        
        # Create Journal Entry with multiple customer debits
        company = self.test_data['company']
        cost_center = self.test_persona.get_default_cost_center(company)
        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.voucher_type = "Journal Entry"
        journal_entry.company = company
        journal_entry.posting_date = frappe.utils.today()

        # Customer 1 debit
        journal_entry.append("accounts", {
            'account': self.test_data['receivable_account'],
            'party_type': 'Customer',
            'party': customer1.name,
            'cost_center': cost_center,
            'debit': 120.0,
            'debit_in_account_currency': 120.0,
            'credit': 0.0
        })

        # Customer 2 debit
        journal_entry.append("accounts", {
            'account': self.test_data['receivable_account'],
            'party_type': 'Customer',
            'party': customer2.name,
            'cost_center': cost_center,
            'debit': 180.0,
            'debit_in_account_currency': 180.0,
            'credit': 0.0
        })

        # Donations account credit
        journal_entry.append("accounts", {
            'account': self.test_data['donations_account'],
            'cost_center': cost_center,
            'debit': 0.0,
            'credit': 300.0,
            'credit_in_account_currency': 300.0
        })

        journal_entry.insert()
        self.track_doc("Journal Entry", journal_entry.name)
        
        journal_entry.submit()
        
        # Verify both customers got donors created
        donor1 = frappe.db.get_value("Donor", {"customer": customer1.name}, "*", as_dict=True)
        donor2 = frappe.db.get_value("Donor", {"customer": customer2.name}, "*", as_dict=True)
        
        self.assertIsNotNone(donor1, "Donor should be created for customer 1")
        self.assertIsNotNone(donor2, "Donor should be created for customer 2")
        
        self.assertEqual(flt(donor1['creation_trigger_amount']), 120.0)
        self.assertEqual(flt(donor2['creation_trigger_amount']), 180.0)
        
        # Track for cleanup
        self.track_doc("Donor", donor1['name'])
        self.track_doc("Donor", donor2['name'])


class DonorAutoCreationTestPersona:
    """
    Test persona for donor auto-creation scenarios
    Provides consistent test data creation following business rules
    """
    
    def create_test_environment(self, test_case):
        """Create complete test environment with accounts and settings"""
        # Get default company
        company = self.get_default_company()
        
        # Use existing accounts instead of creating new ones
        donations_account = self.get_existing_account("Income", company) 
        other_income_account = self.get_existing_account("Income", company, different_from=donations_account)
        receivable_account = self.get_existing_account("Receivable", company)
        cash_account = self.get_existing_account("Cash", company)
        
        # Configure auto-creation settings
        settings = frappe.get_single("Verenigingen Settings")
        settings.auto_create_donors = 1
        settings.donations_gl_account = donations_account
        settings.donor_customer_groups = "Individual Donors,Organization Donors"
        settings.minimum_donation_amount = 100.0
        settings.save()
        
        return {
            'donations_account': donations_account,
            'other_income_account': other_income_account,
            'receivable_account': receivable_account,
            'cash_account': cash_account,
            'company': company
        }
    
    def get_existing_account(self, account_type, company, different_from=None):
        """Get existing account of specified type"""
        # Map shorthand types to valid ERPNext Account "account_type" values
        account_type_alias = {"Income": "Income Account"}
        resolved_account_type = account_type_alias.get(account_type, account_type)
        filters = {
            "account_type": resolved_account_type,
            "is_group": 0,
            "company": company,
            "disabled": 0
        }
        # Restrict to the company's base currency so single-currency test
        # vouchers don't trip the multi-currency validation.
        company_currency = frappe.db.get_value("Company", company, "default_currency")
        if company_currency:
            filters["account_currency"] = company_currency

        # If we need a different account, exclude the specified one
        if different_from:
            accounts = frappe.db.get_all("Account", filters=filters, fields=["name"], limit=2)
            for account in accounts:
                if account.name != different_from:
                    return account.name
            # Fallback to first available if all are the same
            return accounts[0].name if accounts else None
        else:
            account = frappe.db.get_value("Account", filters, "name")
            return account
    
    def get_parent_account(self, account_type, company):
        """Get appropriate parent account for account type"""
        # Try to find existing parent
        parent = frappe.db.get_value("Account", {
            "account_type": account_type,
            "is_group": 1,
            "company": company
        }, "name")
        
        if parent:
            return parent
            
        # Fallback to root account
        root = frappe.db.get_value("Account", {
            "is_group": 1,
            "parent_account": "",
            "company": company
        }, "name")
        
        return root
    
    def create_eligible_customer(self, test_case, suffix=""):
        """Create customer eligible for donor auto-creation"""
        customer_name = f"Eligible Test Customer{suffix}"
        
        # Ensure eligible customer group exists
        group_name = "Individual Donors"
        if not DocumentExistenceValidator.check_document_exists("Customer Group", group_name):
            group = frappe.new_doc("Customer Group")
            group.customer_group_name = group_name
            group.parent_customer_group = "All Customer Groups"
            group.is_group = 0
            group.insert()
            test_case.track_doc("Customer Group", group.name)
        
        customer = frappe.new_doc("Customer")
        customer.customer_name = customer_name
        customer.customer_type = "Individual"
        customer.customer_group = group_name
        customer.territory = "All Territories"
        customer.email_id = f"eligible.customer{suffix}@example.com"
        # Use a full international number; Donor.phone validation requires a
        # country code, and this mobile_no is copied onto the auto-created donor.
        customer.mobile_no = "+31612345678"
        customer.insert()
        
        test_case.track_doc("Customer", customer.name)
        return customer
    
    def create_ineligible_customer(self, test_case):
        """Create customer NOT eligible for donor auto-creation"""
        # Ensure ineligible customer group exists
        group_name = "Corporate Accounts"
        if not DocumentExistenceValidator.check_document_exists("Customer Group", group_name):
            group = frappe.new_doc("Customer Group")
            group.customer_group_name = group_name
            group.parent_customer_group = "All Customer Groups"  
            group.is_group = 0
            group.insert()
            test_case.track_doc("Customer Group", group.name)
        
        customer = frappe.new_doc("Customer") 
        customer.customer_name = "Ineligible Test Customer"
        customer.customer_group = group_name  # Not in eligible groups
        customer.territory = "All Territories"
        customer.email_id = "ineligible.customer@example.com"
        customer.insert()
        
        test_case.track_doc("Customer", customer.name)
        return customer
    
    def create_customer_with_group(self, test_case, group_name):
        """Create customer with specific customer group"""
        # Ensure group exists
        if not DocumentExistenceValidator.check_document_exists("Customer Group", group_name):
            group = frappe.new_doc("Customer Group")
            group.customer_group_name = group_name
            group.parent_customer_group = "All Customer Groups"
            group.is_group = 0
            group.insert()
            test_case.track_doc("Customer Group", group.name)
        
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"Customer in {group_name}"
        customer.customer_group = group_name
        customer.territory = "All Territories" 
        customer.email_id = f"{group_name.lower().replace(' ', '.')}@example.com"
        customer.insert()
        
        test_case.track_doc("Customer", customer.name)
        return customer
    
    def create_donor_for_customer(self, test_case, customer):
        """Create donor record for existing customer"""
        donor = frappe.new_doc("Donor")
        donor.donor_name = customer.customer_name
        donor.donor_type = "Individual"
        donor.donor_email = customer.email_id or f"{customer.customer_name.lower().replace(' ', '.')}@example.com"
        donor.customer = customer.name
        donor.insert()
        
        test_case.track_doc("Donor", donor.name)
        return donor
    
    def create_donation_payment_entry(self, test_case, customer_name, amount, donations_account):
        """Create Payment Entry for donation to specified account"""
        company = self.get_default_company()
        # For a "Receive" payment the paid_from account must be the party's
        # Receivable account; funds are deposited to the donations account.
        receivable_account = self.get_existing_account("Receivable", company)

        payment = frappe.new_doc("Payment Entry")
        payment.payment_type = "Receive"
        payment.company = company
        payment.party_type = "Customer"
        payment.party = customer_name
        payment.paid_amount = amount
        payment.received_amount = amount
        payment.paid_from = receivable_account
        payment.paid_to = donations_account  # To donations account
        payment.source_exchange_rate = 1
        payment.target_exchange_rate = 1
        payment.cost_center = self.get_default_cost_center(company)
        payment.insert()

        test_case.track_doc("Payment Entry", payment.name)
        return payment

    def get_default_cost_center(self, company):
        """Get a non-group cost center for the company."""
        cost_center = frappe.db.get_value("Company", company, "cost_center")
        if cost_center:
            return cost_center
        return frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )
    
    def create_donation_journal_entry(self, test_case, customer_name, amount, donations_account, receivable_account):
        """Create Journal Entry for donation allocation"""
        company = self.get_default_company()
        cost_center = self.get_default_cost_center(company)
        journal_entry = frappe.new_doc("Journal Entry")
        journal_entry.voucher_type = "Journal Entry"
        journal_entry.company = company
        journal_entry.posting_date = frappe.utils.today()

        # Customer debit
        journal_entry.append("accounts", {
            'account': receivable_account,
            'party_type': 'Customer',
            'party': customer_name,
            'cost_center': cost_center,
            'debit': amount,
            'debit_in_account_currency': amount,
            'credit': 0.0
        })

        # Donations account credit
        journal_entry.append("accounts", {
            'account': donations_account,
            'cost_center': cost_center,
            'debit': 0.0,
            'credit': amount,
            'credit_in_account_currency': amount
        })

        journal_entry.insert()
        test_case.track_doc("Journal Entry", journal_entry.name)
        return journal_entry
    
    def get_default_company(self):
        """Get default company for tests"""
        company = frappe.db.get_single_value("Global Defaults", "default_company")
        if not company:
            companies = frappe.db.get_all("Company", limit=1)
            company = companies[0].name if companies else "Test Company"
        return company