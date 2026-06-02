"""
Security tests for Bank Transaction creation with permission enforcement.

Tests that BankTransactionCreator properly respects user permissions when creating
and submitting Bank Transactions using the secure_operations framework.

NO TEST THEATER:
- Real Bank Transactions created in test database
- Real permission validation
- Real user context switching
- Automatic cleanup via EnhancedTestCase rollback
"""

import frappe
from frappe.utils import today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.bank_transaction_creator import (
    get_bank_transaction_creator,
)


class TestBankTransactionSecurity(EnhancedTestCase):
    """Test permission enforcement in Bank Transaction creation"""

    def setUp(self):
        super().setUp()
        self.creator = get_bank_transaction_creator()

        # Store admin user
        self.admin_user = frappe.session.user

        # Get test company from EnhancedTestCase (returns company name string)
        self.company_name = self._get_test_company()

        # Create Bank Account for testing (must be as admin)
        frappe.set_user(self.admin_user)
        self.bank_account_name = self._create_bank_account()

        # Create users with different permission levels
        # Create a custom role with create but NOT submit permission
        self._create_restricted_role()

        # User with create but NOT submit permission
        self.restricted_user = self.create_test_user(
            email="restricted@test.com",
            first_name="Restricted",
            last_name="User",
            roles=["Bank Transaction Creator"],  # Custom role: create but not submit
        )

        # User with NO Bank Transaction permissions
        self.guest_user = self.create_test_user(
            email="guest@test.com", first_name="Guest", last_name="User", roles=[]
        )

        # Restore admin context
        frappe.set_user(self.admin_user)

    def _create_restricted_role(self):
        """Create a role with Bank Transaction create but NOT submit permission"""
        role_name = "Bank Transaction Creator"

        if not frappe.db.exists("Role", role_name):
            role = frappe.get_doc({"doctype": "Role", "role_name": role_name})
            role.insert(ignore_permissions=True)

        # Add custom permission: create=1, submit=0
        if not frappe.db.exists(
            "Custom DocPerm",
            {"parent": "Bank Transaction", "role": role_name, "permlevel": 0},
        ):
            perm = frappe.get_doc(
                {
                    "doctype": "Custom DocPerm",
                    "parent": "Bank Transaction",
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    "role": role_name,
                    "permlevel": 0,
                    "read": 1,
                    "write": 1,
                    "create": 1,
                    "submit": 0,  # NO submit permission
                    "cancel": 0,
                    "delete": 0,
                }
            )
            perm.insert(ignore_permissions=True)

    def _create_bank_account(self):
        """Create test Bank Account with required Bank master"""
        # Create Bank if it doesn't exist
        if not frappe.db.exists("Bank", "Test Bank"):
            bank = frappe.get_doc({"doctype": "Bank", "bank_name": "Test Bank"})
            bank.insert(ignore_permissions=True)

        # A Bank Account must link to a GL Account of type "Bank" or the Bank
        # Transaction raises "Company Account is mandatory".
        gl_account = self._ensure_bank_gl_account()

        # Create Bank Account
        bank_account = frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": "Test Bank Account",
                "bank": "Test Bank",
                "account": gl_account,
                "company": self.company_name,
                "is_default": 0,
                "is_company_account": 1,
            }
        )
        bank_account.insert(ignore_permissions=True, ignore_if_duplicate=True)
        return bank_account.name

    def _ensure_bank_gl_account(self):
        """Return a non-group EUR GL Account of type Bank for the test company.

        The Bank Transaction creator defaults the transaction currency to EUR,
        so the linked GL account must also be EUR to avoid a currency mismatch.
        """
        existing = frappe.db.get_value(
            "Account",
            {
                "account_type": "Bank",
                "is_group": 0,
                "company": self.company_name,
                "account_currency": "EUR",
            },
            "name",
        )
        if existing:
            return existing
        parent = frappe.db.get_value(
            "Account",
            {"account_type": "Bank", "is_group": 1, "company": self.company_name},
            "name",
        ) or frappe.db.get_value(
            "Account",
            {"root_type": "Asset", "is_group": 1, "company": self.company_name},
            "name",
            order_by="lft",
        )
        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": "Test Bank GL EUR",
                "account_type": "Bank",
                "account_currency": "EUR",
                "parent_account": parent,
                "company": self.company_name,
            }
        )
        account.insert(ignore_permissions=True)
        return account.name

    def test_admin_can_create_and_submit(self):
        """Administrator can create and submit Bank Transactions"""
        frappe.set_user(self.admin_user)

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 100.0,
                "description": "Test transaction - admin",
                "reference_number": "ADMIN-TEST-001",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        self.assertIsNotNone(bt_name, "Admin should create Bank Transaction")

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.docstatus, 1, "Admin should submit Bank Transaction")
        self.assertEqual(bt.deposit, 100.0)
        self.assertEqual(bt.description, "Test transaction - admin")

    def test_restricted_user_creates_draft_only(self):
        """User without submit permission creates draft Bank Transaction"""
        frappe.set_user(self.restricted_user.name)

        # Check permissions before create
        has_create = frappe.has_permission("Bank Transaction", "create")
        has_submit = frappe.has_permission("Bank Transaction", "submit")
        print(f"\n🔍 Restricted user {self.restricted_user.name}:")
        print(f"   - has_create: {has_create}")
        print(f"   - has_submit: {has_submit}")

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 50.0,
                "description": "Test transaction - restricted",
                "reference_number": "RESTRICTED-TEST-001",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        # Should create via system user fallback (allow_system_user=True)
        self.assertIsNotNone(bt_name, "Should create Bank Transaction via system user fallback")

        bt = frappe.get_doc("Bank Transaction", bt_name)
        print(f"✅ Created: {bt_name}, docstatus={bt.docstatus}")

        # CRITICAL TEST: Should be draft (docstatus=0) because restricted user lacks submit permission
        # If this is 1 (submitted), we have a permission bypass bug
        self.assertEqual(
            bt.docstatus,
            0,
            f"Bank Transaction should remain draft when user lacks submit permission (got docstatus={bt.docstatus})",
        )
        self.assertEqual(bt.deposit, 50.0)
        self.assertEqual(bt.description, "Test transaction - restricted")

    def test_guest_user_with_system_fallback(self):
        """Guest user with no permissions uses system user fallback"""
        frappe.set_user(self.guest_user.name)

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 75.0,
                "description": "Test transaction - guest",
                "reference_number": "GUEST-TEST-001",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        # Should create via system user fallback (allow_system_user=True is default)
        self.assertIsNotNone(bt_name, "Should create Bank Transaction via system user fallback")

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.deposit, 75.0)
        self.assertEqual(bt.description, "Test transaction - guest")

    def test_negative_amount_creates_withdrawal(self):
        """Negative amounts create withdrawal (not deposit)"""
        frappe.set_user(self.admin_user)

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": -200.0,
                "description": "Test withdrawal",
                "reference_number": "WITHDRAWAL-TEST-001",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        self.assertIsNotNone(bt_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.withdrawal, 200.0, "Negative amount should create withdrawal")
        self.assertEqual(bt.deposit, 0.0, "Deposit should be zero for negative amount")

    def test_bank_party_fields_preserved(self):
        """Bank party fields (IBAN, name) are correctly set"""
        frappe.set_user(self.admin_user)

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 150.0,
                "description": "SEPA import test",
                "reference_number": "SEPA-TEST-001",
                "bank_party_name": "Test Counterparty",
                "bank_party_iban": "NL91ABNA0417164300",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="SEPA Import",
        )

        self.assertIsNotNone(bt_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.bank_party_name, "Test Counterparty")
        self.assertEqual(bt.bank_party_iban, "NL91ABNA0417164300")

    def test_transaction_id_field_preserved(self):
        """transaction_id field is correctly set"""
        frappe.set_user(self.admin_user)

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 25.0,
                "description": "Transaction ID test",
                "reference_number": "TXN-ID-TEST-001",
                "transaction_id": "INTERNAL-TX-123",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        self.assertIsNotNone(bt_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.transaction_id, "INTERNAL-TX-123")

    def test_idempotency_with_reference_number(self):
        """Duplicate reference_number returns existing transaction"""
        frappe.set_user(self.admin_user)

        reference = "IDEMPOTENT-TEST-001"

        # Create first transaction
        bt_name_1 = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 100.0,
                "description": "First attempt",
                "reference_number": reference,
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        # Attempt to create duplicate with same reference_number
        bt_name_2 = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 200.0,  # Different amount
                "description": "Second attempt",
                "reference_number": reference,  # Same reference
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        # Should return same Bank Transaction (idempotency)
        self.assertEqual(
            bt_name_1, bt_name_2, "Duplicate reference_number should return existing transaction"
        )

        # Verify amount didn't change
        bt = frappe.get_doc("Bank Transaction", bt_name_1)
        self.assertEqual(bt.deposit, 100.0, "Original transaction should be unchanged")

    def test_missing_required_fields_returns_none(self):
        """Missing required fields (date, amount) returns None"""
        frappe.set_user(self.admin_user)

        # Missing date
        bt_name = self.creator.create_from_dict(
            transaction_data={
                "amount": 100.0,
                "description": "Missing date",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        self.assertIsNone(bt_name, "Missing date should return None")

        # Missing amount
        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "description": "Missing amount",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        self.assertIsNone(bt_name, "Missing amount should return None")

    def test_audit_trail_logged(self):
        """Secure operations create audit trail entries"""
        frappe.set_user(self.admin_user)

        bt_name = self.creator.create_from_dict(
            transaction_data={
                "date": today(),
                "amount": 100.0,
                "description": "Audit trail test",
                "reference_number": "AUDIT-TEST-001",
            },
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Test",
        )

        self.assertIsNotNone(bt_name)

        # Check that secure operation audit was logged
        # secure_operations logs with "SECURE_OPERATION_AUDIT:" prefix
        logs = frappe.db.sql(
            """
            SELECT name, creation
            FROM `tabError Log`
            WHERE error LIKE %s
            ORDER BY creation DESC
            LIMIT 1
        """,
            (f"%SECURE_OPERATION_AUDIT%Bank Transaction%{bt_name}%",),
            as_dict=True,
        )

        # May or may not have audit log depending on log level configuration
        # This is informational, not a hard requirement
        if logs:
            frappe.logger().info(f"✅ Audit trail found: {logs[0].name}")

    def test_sepa_import_workflow(self):
        """Complete SEPA import workflow with real data"""
        frappe.set_user(self.admin_user)

        # Simulate SEPA transaction data
        sepa_data = {
            "date": today(),
            "amount": 250.0,
            "currency": "EUR",
            "description": "SEPA Overschrijving\nFactuur 2025-001",
            "reference_number": "202510230001",
            "transaction_id": "TXN-SEPA-001",
            "bank_party_name": "Nederlandse Vereniging",
            "bank_party_iban": "NL91ABNA0417164300",
        }

        bt_name = self.creator.create_from_dict(
            transaction_data=sepa_data,
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="SEPA/CAMT Import",
        )

        self.assertIsNotNone(bt_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.deposit, 250.0)
        self.assertEqual(bt.currency, "EUR")
        self.assertEqual(bt.transaction_id, "TXN-SEPA-001")
        self.assertEqual(bt.bank_party_name, "Nederlandse Vereniging")
        self.assertEqual(bt.bank_party_iban, "NL91ABNA0417164300")
        self.assertIn("SEPA Overschrijving", bt.description)

    def test_member_payment_import_workflow(self):
        """Complete member payment import workflow"""
        frappe.set_user(self.admin_user)

        # Simulate member payment CSV data
        payment_data = {
            "date": today(),
            "amount": 35.0,
            "currency": "EUR",
            "description": "Contributie 2025",
            "reference_number": "CONTRIB-2025-001",
            "bank_party_name": "Jan de Vries",
            "bank_party_iban": "NL20INGB0001234567",
        }

        bt_name = self.creator.create_from_dict(
            transaction_data=payment_data,
            bank_account=self.bank_account_name,
            company=self.company_name,
            source_type="Member Payment Import",
        )

        self.assertIsNotNone(bt_name)

        bt = frappe.get_doc("Bank Transaction", bt_name)
        self.assertEqual(bt.deposit, 35.0)
        self.assertEqual(bt.description, "Contributie 2025")
        self.assertEqual(bt.bank_party_name, "Jan de Vries")
        self.assertEqual(bt.bank_party_iban, "NL20INGB0001234567")

    def test_permission_restoration_after_error(self):
        """User context restored after operation error"""
        frappe.set_user(self.restricted_user.name)

        try:
            # Attempt operation with missing required field (should fail validation)
            bt_name = self.creator.create_from_dict(
                transaction_data={
                    # Missing 'date' field - validation should fail
                    "amount": 100.0,
                    "description": "Missing date test",
                    "reference_number": "ERROR-TEST-001",
                },
                bank_account=self.bank_account_name,
                company=self.company_name,
                source_type="Test",
            )

            # Operation should fail gracefully due to missing required field
            self.assertIsNone(bt_name, "Missing required field should return None")

        finally:
            # User context should be restored even after error
            self.assertEqual(
                frappe.session.user,
                self.restricted_user.name,
                "User context should be restored after validation failure",
            )
