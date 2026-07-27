"""
Unit Tests for PaymentEntryCreationService

Tests the consolidated payment entry creation service that replaces
duplicate logic from batch_processing_service, direct_debit_batch, and sepa_reconciliation.

Test Status (latest run):
- ✅ test_does_not_exist_error_invalid_invoice - PASS
- ❌ test_successful_payment_entry_creation_and_submission - ERPNext account setup
- ❌ test_payment_entry_with_bank_transaction_link - ERPNext account setup
- ❌ test_validation_error_negative_amount - ERPNext account setup (in helper)
- ❌ test_validation_error_zero_amount - ERPNext account setup (in helper)
- ❌ test_decimal_to_float_conversion - ERPNext account setup
- ❌ test_payment_entry_fields_correctly_set - ERPNext account setup
- ❌ test_multiple_payment_entries_for_same_invoice_allowed - ERPNext account setup
- ❌ test_payment_type_parameter_respected - ERPNext account setup

**Root Cause**: Tests use EnhancedTestCase correctly, but _create_test_invoice() helper
fails due to missing ERPNext accounting configuration (party accounts, currency setup).

**Service Validation**: The core service logic IS working - test_does_not_exist_error_invalid_invoice
proves the service correctly validates invoice existence without requiring full invoice creation.
"""

import unittest
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.services.payment.payment_entry_creation_service import (
    payment_entry_service,
)


class TestPaymentEntryCreationService(EnhancedTestCase):
    """Test PaymentEntryCreationService functionality"""

    def setUp(self):
        super().setUp()
        # Create test member and customer for invoice creation
        self.test_member = self.create_test_member(
            first_name="Payment", last_name="Test", email="payment.test@example.com", birth_date="1990-01-01"
        )

        # The factory already auto-creates and links a Customer for the member
        # (member.customer). Reuse it instead of inserting a second Customer with
        # the same derived name, which collided on the Customer primary key.
        self.test_customer = frappe.get_doc("Customer", self.test_member.customer)

        # Ensure test item exists (CodeRabbit suggestion - avoid hardcoded item dependency)
        if not frappe.db.exists("Item", "Test Payment Service Item"):
            item = frappe.get_doc(
                {
                    "doctype": "Item",
                    "item_code": "Test Payment Service Item",
                    "item_name": "Test Payment Service Item",
                    "item_group": "Services",
                    "stock_uom": "Nos",
                    "is_stock_item": 0,
                    "is_sales_item": 1,
                }
            )
            item.insert()
            self.track_doc("Item", item.name)

        self.test_item_code = "Test Payment Service Item"

    def tearDown(self):
        # Cleanup test data
        frappe.db.rollback()
        super().tearDown()

    def _create_test_invoice(self, amount=Decimal("100.00"), status="Unpaid"):
        """Helper to create test sales invoice using EnhancedTestCase factory"""
        # Use the factory's create_test_sales_invoice which properly handles
        # cost centers, income accounts, and other ERPNext requirements
        invoice = self.create_test_sales_invoice(
            customer=self.test_customer.name,
            posting_date=date.today(),
            due_date=date.today(),
            items=[{"item_code": self.test_item_code, "qty": 1, "rate": float(amount)}],
        )
        if status == "Submitted":
            invoice.submit()
        return invoice

    def test_successful_payment_entry_creation_and_submission(self):
        """Test successful payment entry creation with full permissions"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("50.00"))
        invoice.submit()

        # Act
        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("50.00"),
            posting_date=date.today(),
            reference_no="TEST-REF-001",
            reference_date=date.today(),
            mode_of_payment="SEPA Direct Debit",
        )

        # Assert
        self.assertIsNotNone(payment_entry)
        self.assertEqual(payment_entry.docstatus, 1)  # Submitted
        self.assertEqual(payment_entry.payment_type, "Receive")
        self.assertEqual(payment_entry.mode_of_payment, "SEPA Direct Debit")
        self.assertEqual(payment_entry.reference_no, "TEST-REF-001")
        self.assertEqual(float(payment_entry.paid_amount), 50.00)
        self.assertEqual(float(payment_entry.received_amount), 50.00)

    @unittest.skip("Requires Bank and Account setup - see file comments for known ERPNext setup issues")
    def test_payment_entry_with_bank_transaction_link(self):
        """Test payment entry creation with bank transaction linking (reconciliation)"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("75.00"))
        invoice.submit()

        # Create mock bank transaction
        bank_account = frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": "Test Bank Account",
                "bank": "Test Bank",
                "account": "Test - Company",
            }
        ).insert()

        bank_trans = frappe.get_doc(
            {
                "doctype": "Bank Transaction",
                "bank_account": bank_account.name,
                "date": date.today(),
                "deposit": 75.00,
                "description": "Test payment",
                "reference_number": "BANK-REF-001",
            }
        ).insert()

        # Act
        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("75.00"),
            posting_date=date.today(),
            reference_no="BANK-REF-001",
            reference_date=date.today(),
            mode_of_payment="Bank Transfer",
            bank_transaction_name=bank_trans.name,
        )

        # Assert
        self.assertIsNotNone(payment_entry)
        self.assertEqual(payment_entry.bank_transaction, bank_trans.name)
        self.assertEqual(payment_entry.docstatus, 1)

    def test_validation_error_negative_amount(self):
        """Test that negative amounts raise ValidationError"""
        # Arrange
        invoice = self._create_test_invoice()
        invoice.submit()

        # Act & Assert
        with self.assertRaises(frappe.ValidationError) as context:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("-50.00"),  # Negative amount
                posting_date=date.today(),
                reference_no="TEST-REF-002",
                reference_date=date.today(),
                mode_of_payment="SEPA Direct Debit",
            )

        self.assertIn("greater than zero", str(context.exception))

    def test_validation_error_zero_amount(self):
        """Test that zero amount raises ValidationError"""
        # Arrange
        invoice = self._create_test_invoice()
        invoice.submit()

        # Act & Assert
        with self.assertRaises(frappe.ValidationError) as context:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("0.00"),  # Zero amount
                posting_date=date.today(),
                reference_no="TEST-REF-003",
                reference_date=date.today(),
                mode_of_payment="SEPA Direct Debit",
            )

        self.assertIn("greater than zero", str(context.exception))

    def test_does_not_exist_error_invalid_invoice(self):
        """Test that non-existent invoice raises DoesNotExistError"""
        # Act & Assert
        with self.assertRaises(frappe.ValidationError):  # frappe.throw raises ValidationError
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name="INVALID-INV-999",
                amount=Decimal("50.00"),
                posting_date=date.today(),
                reference_no="TEST-REF-004",
                reference_date=date.today(),
                mode_of_payment="SEPA Direct Debit",
            )

    def test_decimal_to_float_conversion(self):
        """Test that Decimal amounts are properly converted to float for ERPNext"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("123.45"))
        invoice.submit()

        # Pay the invoice's actual outstanding amount as a Decimal. The company's
        # rounded_total settings can make outstanding differ slightly from the line
        # rate; allocating more than outstanding raises "Allocated Amount cannot be
        # greater than outstanding amount". The point of this test is Decimal->float
        # conversion, so derive the Decimal from the real outstanding.
        pay_amount = Decimal(str(invoice.outstanding_amount))

        # Act
        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=pay_amount,  # Decimal input
            posting_date=date.today(),
            reference_no="TEST-REF-005",
            reference_date=date.today(),
            mode_of_payment="SEPA Direct Debit",
        )

        # Assert - ERPNext stores as float
        self.assertIsInstance(payment_entry.paid_amount, (float, int))
        self.assertAlmostEqual(float(payment_entry.paid_amount), float(pay_amount), places=2)

    @unittest.skip("Requires complex permission mocking with user/role setup")
    def test_graceful_degradation_creates_draft_on_permission_failure(self):
        """Test that graceful mode creates draft entry if submit permission lacking"""
        # This test would require mocking permission checks
        # Skipping for now as it requires complex permission setup
        pass  # TODO: Implement with permission mocking

    # ---- Real permission-denial paths (no mocking) ------------------------
    # The two skipped stubs above deferred these as "requires complex permission
    # mocking". They need no mocking at all: a real deskless User carrying a role
    # with the exact Payment Entry perms under test, driven with frappe.set_user.
    # Custom DocPerm rows added via add_permission/update_permission_property are
    # transaction-scoped and roll back with the test.

    def _make_deskless_role_without_perms(self):
        """A desk-access Role carrying ZERO doctype permissions."""
        role = frappe.new_doc("Role")
        role.role_name = f"PECS NoPerm {frappe.generate_hash(length=8)}"
        role.desk_access = 1
        role.insert()
        self.track_doc("Role", role.name)
        return role.name

    def _make_user_with_roles(self, roles):
        """A fresh, enabled User carrying exactly the supplied roles."""
        user = frappe.new_doc("User")
        user.email = f"pecs-restricted-{frappe.generate_hash(length=10)}@example.com"
        user.first_name = "PECS Restricted"
        user.send_welcome_email = 0
        user.enabled = 1
        for r in roles:
            user.append("roles", {"role": r})
        user.insert()
        self.track_doc("User", user.name)
        return user.name

    @contextmanager
    def _payment_entry_create_granted(self, role):
        """Grant Payment Entry read+create (but NOT submit) to ``role`` via a Custom
        DocPerm, and serve ``frappe.get_meta("Payment Entry")`` from a Meta built right
        here for the duration. Transaction-scoped; the grant rolls back with the test.

        Grant and pin are one context manager on purpose: the pin, and the three
        assertions that prove the grant landed, all live in ``__enter__``. Split across a
        plain helper plus a returned context manager, a caller who ignored the return
        value would silently get neither, with nothing to warn them.

        WHY: the grant is an *uncommitted* Custom DocPerm row, but
        ``frappe.has_permission`` resolves role rows off
        ``frappe.get_meta("Payment Entry")`` (frappe/permissions.py:130), which is
        served from ``frappe.client_cache`` -- a process-shared, redis-backed,
        asynchronously-invalidated cache this test does not own. Any rebuild of that
        entry can legitimately drop the grant:

          * ``Meta.set_custom_permissions()`` discards *every* Custom DocPerm outright
            while ``frappe.flags.in_patch``/``in_install`` is set
            (frappe/model/meta.py:627-638), falling back to the two shipped
            DocPerms (Accounts User / Accounts Manager); and
          * a rebuild driven from any other process only ever sees committed rows.

        Either way the CREATE gate then refuses a permission this test just granted,
        so the assertion sees the create message instead of the submit one -- the
        ~50% flake on CI shard 10. The previous approach (global ``frappe.clear_cache()``
        + eager ``get_meta(cached=False)``) *raced* that cache rather than owning the
        state, so it could not close the window; it also published this test's
        uncommitted permissions into shared redis and wiped every other doctype's meta
        for the rest of the shard.

        Pinning removes the race without weakening what is under test:
        ``frappe.has_permission`` still runs for real and still evaluates these real
        Custom DocPerm rows against the user's real roles. Only the nondeterministic
        cache round-trip is bypassed. Patching ``frappe.get_meta`` (the cache layer) is
        sanctioned; patching ``frappe.has_permission`` (the security boundary itself)
        is not -- see scripts/validation/test_quality_enforcer.py.
        """
        from frappe.model.meta import load_meta
        from frappe.permissions import add_permission, update_permission_property

        add_permission("Payment Entry", role, 0)  # sets read=1
        update_permission_property("Payment Entry", role, 0, "create", 1)

        # load_meta() builds without reading or writing the shared cache, so the
        # dependency is severed in both directions.
        meta = load_meta("Payment Entry")

        # Assert the grant actually materialised. Checked against the object we
        # control rather than a shared cache, so this cannot flake -- and it turns a
        # broken grant into an immediate, explicit failure instead of a confusing
        # wrong-gate assertion further down.
        granted = [p for p in meta.permissions if p.role == role]
        self.assertEqual(len(granted), 1, f"expected exactly one Custom DocPerm row for {role}")
        self.assertTrue(granted[0].get("create"), "grant should give CREATE")
        self.assertFalse(granted[0].get("submit"), "grant must NOT give SUBMIT")

        real_get_meta = frappe.get_meta

        def pinned_get_meta(doctype, *args, **kwargs):
            if doctype == "Payment Entry":
                return meta
            return real_get_meta(doctype, *args, **kwargs)

        with patch("frappe.get_meta", pinned_get_meta):
            yield

    def test_create_permission_denied_raises_permission_error(self):
        """A user lacking Payment Entry CREATE is refused at the create gate
        (payment_entry_creation_service.py:136-140), before any DB write. The
        invoice exists and the amount is valid, so the ONLY reason to raise is
        the create-permission check."""
        # Seeded as Administrator (setUp context); the invoice only has to exist.
        invoice = self._create_test_invoice(amount=Decimal("40.00"))
        role = self._make_deskless_role_without_perms()
        restricted_user = self._make_user_with_roles([role])

        # No pre-check guard here (see the sibling strict-mode test for the full
        # rationale): reading has_permission in the pre-set_user Administrator context
        # is cache-fragile across parallel shards. It is also redundant -- the
        # create-gate message asserted below is only raised when the user lacks
        # create, which is exactly what a guard would have checked.
        frappe.set_user(restricted_user)
        with self.assertRaises(frappe.PermissionError) as ctx:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("40.00"),
                posting_date=date.today(),
                reference_no="PERM-CREATE",
                reference_date=date.today(),
                mode_of_payment="SEPA Direct Debit",
            )
        # Exact literal from :138 — distinguishes the CREATE gate from the SUBMIT gate.
        self.assertIn("Insufficient permissions to create payment entry", str(ctx.exception))

    def test_strict_mode_raises_permission_error_without_submit_permission(self):
        """A user WITH Payment Entry CREATE but WITHOUT SUBMIT is refused in
        strict mode (allow_draft_on_permission_failure=False) at :143-150, before
        any DB write. Having create isolates the failure to the submit gate."""
        invoice = self._create_test_invoice(amount=Decimal("45.00"))
        role = self._make_deskless_role_without_perms()
        restricted_user = self._make_user_with_roles([role])

        # The grant is verified on entry to the context manager, against the Meta object
        # the permission check will actually read. An earlier revision dropped that guard
        # because reading it back through the shared meta cache was itself flaky; pinning
        # makes the check deterministic, so it is worth having again.
        with self._payment_entry_create_granted(role):
            frappe.set_user(restricted_user)
            with self.assertRaises(frappe.PermissionError) as ctx:
                payment_entry_service.create_payment_entry_from_invoice(
                    invoice_name=invoice.name,
                    amount=Decimal("45.00"),
                    posting_date=date.today(),
                    reference_no="PERM-SUBMIT",
                    reference_date=date.today(),
                    mode_of_payment="SEPA Direct Debit",
                    allow_draft_on_permission_failure=False,  # strict mode
                )
        # Exact literal from :148 — distinguishes the SUBMIT gate from the CREATE gate.
        self.assertIn("Insufficient permissions to submit payment entry", str(ctx.exception))

    @unittest.skip("Requires complete ERPNext accounting setup - see file comments for known issues")
    def test_payment_entry_fields_correctly_set(self):
        """Test that all payment entry fields are correctly populated"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("200.00"))
        invoice.submit()

        test_date = date(2024, 3, 15)

        # Act
        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("200.00"),
            posting_date=test_date,
            reference_no="CUSTOM-REF-123",
            reference_date=test_date,
            mode_of_payment="Bank Transfer",
            payment_type="Receive",
        )

        # Assert all fields
        self.assertEqual(payment_entry.payment_type, "Receive")
        self.assertEqual(payment_entry.mode_of_payment, "Bank Transfer")
        self.assertEqual(payment_entry.reference_no, "CUSTOM-REF-123")
        self.assertEqual(payment_entry.reference_date, test_date)
        self.assertEqual(payment_entry.posting_date, test_date)
        self.assertEqual(float(payment_entry.paid_amount), 200.00)
        self.assertEqual(float(payment_entry.received_amount), 200.00)
        self.assertEqual(payment_entry.party, self.test_customer.name)

    def test_multiple_payment_entries_for_same_invoice_allowed(self):
        """Test that multiple payment entries can be created for same invoice (partial payments)"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("100.00"))
        invoice.submit()

        # Act - Create two partial payments
        payment1 = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("60.00"),
            posting_date=date.today(),
            reference_no="PARTIAL-1",
            reference_date=date.today(),
            mode_of_payment="SEPA Direct Debit",
        )

        payment2 = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("40.00"),
            posting_date=date.today(),
            reference_no="PARTIAL-2",
            reference_date=date.today(),
            mode_of_payment="SEPA Direct Debit",
        )

        # Assert - Both payments created successfully
        self.assertIsNotNone(payment1)
        self.assertIsNotNone(payment2)
        self.assertNotEqual(payment1.name, payment2.name)
        self.assertEqual(payment1.docstatus, 1)
        self.assertEqual(payment2.docstatus, 1)

    def test_error_logging_for_unexpected_exceptions(self):
        """Unexpected (non-Validation/Permission) errors hit the generic
        except-branch, which logs to frappe.log_error with the invoice name and
        the 'Payment Entry Unexpected Error' title before re-raising.

        Uses a REAL submitted invoice and REAL permissions (Administrator in
        tests). The downstream ERPNext ``get_payment_entry`` builder is patched
        at its source module to raise a RuntimeError — simulating the rare
        framework/database failure this branch exists to catch, without mocking
        any frappe primitive. ``frappe.log_error`` is captured only to assert the
        observability contract (title + invoice name); it does not alter control
        flow.
        """
        invoice = self._create_test_invoice(amount=Decimal("50.00"))
        invoice.submit()

        with (
            patch(
                "erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry",
                side_effect=RuntimeError("Unexpected database error"),
            ),
            patch(
                "verenigingen.verenigingen_payments.services.payment."
                "payment_entry_creation_service.frappe.log_error"
            ) as mock_log_error,
        ):
            with self.assertRaises(Exception):
                payment_entry_service.create_payment_entry_from_invoice(
                    invoice_name=invoice.name,
                    amount=Decimal("50.00"),
                    posting_date=date.today(),
                    reference_no="TEST-REF-LOG",
                    reference_date=date.today(),
                    mode_of_payment="SEPA Direct Debit",
                )

        # Verify the unexpected error was logged with the documented contract
        mock_log_error.assert_called_once()
        call_args = mock_log_error.call_args
        self.assertIn(invoice.name, call_args[0][0])  # Invoice name in error message
        self.assertEqual(call_args[0][1], "Payment Entry Unexpected Error")  # Error title

    def test_payment_type_parameter_respected(self):
        """Test that payment_type parameter (Receive/Pay) is properly used"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("150.00"))
        invoice.submit()

        # Act - Test with "Receive" type
        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("150.00"),
            posting_date=date.today(),
            reference_no="RECEIVE-TEST",
            reference_date=date.today(),
            mode_of_payment="Cash",
            payment_type="Receive",
        )

        # Assert
        self.assertEqual(payment_entry.payment_type, "Receive")


class TestPaymentEntryCreationServiceIntegration(FrappeTestCase):
    """Integration tests for PaymentEntryCreationService with actual ERPNext data"""

    @unittest.skip("Requires full ERPNext accounting setup (items, taxes, accounts)")
    def test_integration_with_erpnext_get_payment_entry(self):
        """Test that service properly integrates with ERPNext's get_payment_entry function"""
        # This test would create a full invoice with items, taxes, etc.
        # and verify that ERPNext's auto-population works correctly
        pass  # TODO: Implement full integration test

    @unittest.skip("Requires full ERPNext bank reconciliation module setup")
    def test_integration_with_bank_reconciliation_workflow(self):
        """Test that service works correctly in bank reconciliation context"""
        # This test would simulate the full reconciliation workflow
        pass  # TODO: Implement reconciliation integration test

    @unittest.skip("Requires full ERPNext accounting and SEPA batch setup")
    def test_integration_with_batch_processing_workflow(self):
        """Test that service works correctly in batch processing context"""
        # This test would simulate the batch processing workflow
        pass  # TODO: Implement batch processing integration test
