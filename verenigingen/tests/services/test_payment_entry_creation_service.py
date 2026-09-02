"""
Unit Tests for PaymentEntryCreationService

Tests the consolidated payment entry creation service that replaces
duplicate logic from batch_processing_service, direct_debit_batch, and sepa_reconciliation.

A per-test status block used to live here, listing seven tests as failing on "ERPNext
account setup". All seven pass; the helper it blamed (_create_test_invoice) works. The
block was removed rather than refreshed - a hand-maintained list of which tests pass is
stale the moment it is written, and this one had gone from stale to actively misleading,
telling a reader the suite was broken when it was green.

Overpayment coverage: the service records cash above an invoice's outstanding ONLY when
a caller opts in via `cash_received`. Those tests assert the GL rows, not just the
amount fields - a capped posting and a full-cash one are indistinguishable on
`allocated_amount` alone, so an assertion on that field cannot tell the two apart.

Both gaps this docstring used to list as open are now closed by
`_ensure_foreign_currency_clearing_account`: the currency-boundary refusal on the
overpayment path, and the argument handed to `_suppress_early_payment_discount`. Neither
is observable on the same-currency path, which is why they went untested for so long -
see the three tests under "Currency boundary".
"""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest.mock import patch

# Read "today" off the SITE clock. The Currency Exchange fixture below is keyed
# on frappe.utils.today(), and ERPNext looks the rate up by the Payment Entry's
# posting_date; the naive process clock lands on a different calendar day from
# 18:30 UTC (site tz Asia/Kolkata, CI in UTC), the rate lookup misses, and the
# USD leg values at the fallback rate instead of the fixture's 1.25.
import frappe
from frappe.utils import flt, getdate

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
            posting_date=getdate(),
            due_date=getdate(),
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
            posting_date=getdate(),
            reference_no="TEST-REF-001",
            reference_date=getdate(),
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

    # test_payment_entry_with_bank_transaction_link was removed here. It was skipped,
    # and it asserted `payment_entry.bank_transaction == bank_trans.name` - a field
    # that does not exist on Payment Entry, so it pinned the very bug it appeared to
    # cover and would have passed against the broken behaviour if ever unskipped.
    # test_bank_transaction_name_is_persisted supersedes it and reads the value back
    # from the database.

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
                posting_date=getdate(),
                reference_no="TEST-REF-002",
                reference_date=getdate(),
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
                posting_date=getdate(),
                reference_no="TEST-REF-003",
                reference_date=getdate(),
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
                posting_date=getdate(),
                reference_no="TEST-REF-004",
                reference_date=getdate(),
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
            posting_date=getdate(),
            reference_no="TEST-REF-005",
            reference_date=getdate(),
            mode_of_payment="SEPA Direct Debit",
        )

        # Assert - ERPNext stores as float
        self.assertIsInstance(payment_entry.paid_amount, (float, int))
        self.assertAlmostEqual(float(payment_entry.paid_amount), float(pay_amount), places=2)

    # ---- Real permission-denial paths (no mocking) ------------------------
    # A skipped `pass` stub named test_graceful_degradation_creates_draft_on_permission_failure
    # stood here, deferring this as "requires complex permission mocking". It was
    # deleted rather than unskipped: the tests below already cover that path for real,
    # so unskipping an empty body would only have added a second, weaker claim on the
    # same behaviour. They need no mocking at all: a real deskless User carrying a role
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
                posting_date=getdate(),
                reference_no="PERM-CREATE",
                reference_date=getdate(),
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
                    posting_date=getdate(),
                    reference_no="PERM-SUBMIT",
                    reference_date=getdate(),
                    mode_of_payment="SEPA Direct Debit",
                    allow_draft_on_permission_failure=False,  # strict mode
                )
        # Exact literal from :148 — distinguishes the SUBMIT gate from the CREATE gate.
        self.assertIn("Insufficient permissions to submit payment entry", str(ctx.exception))

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
            posting_date=getdate(),
            reference_no="PARTIAL-1",
            reference_date=getdate(),
            mode_of_payment="SEPA Direct Debit",
        )

        payment2 = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("40.00"),
            posting_date=getdate(),
            reference_no="PARTIAL-2",
            reference_date=getdate(),
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
                    posting_date=getdate(),
                    reference_no="TEST-REF-LOG",
                    reference_date=getdate(),
                    mode_of_payment="SEPA Direct Debit",
                )

        # Verify the unexpected error was logged with the documented contract.
        #
        # Asserted on KEYWORDS. Passed positionally, the message lands in log_error's
        # `title` (which truncates) and the title in `message`; frappe's auto-swap only
        # rescues that when the title contains a newline, and this one has none. The
        # previous positional assertion therefore pinned the broken call shape.
        mock_log_error.assert_called_once()
        kwargs = mock_log_error.call_args.kwargs
        self.assertEqual(kwargs["title"], "Payment Entry Unexpected Error")
        self.assertIn(invoice.name, kwargs["message"])
        self.assertIn("Unexpected database error", kwargs["message"])
        # The traceback is the whole point of this log line: without it the branch
        # records that something failed but not where.
        self.assertIn("Traceback", kwargs["message"])

    def test_payment_type_parameter_respected(self):
        """Test that payment_type parameter (Receive/Pay) is properly used"""
        # Arrange
        invoice = self._create_test_invoice(amount=Decimal("150.00"))
        invoice.submit()

        # Act - Test with "Receive" type
        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("150.00"),
            posting_date=getdate(),
            reference_no="RECEIVE-TEST",
            reference_date=getdate(),
            mode_of_payment="Cash",
            payment_type="Receive",
        )

        # Assert
        self.assertEqual(payment_entry.payment_type, "Receive")

    # ------------------------------------------------------------------
    # Gateway parameters (bank_account / remarks)
    #
    # These exist so the four hand-rolled gateway wrappers (Mollie dues, Mollie
    # orchestrator, Ponto, ING) can call this service instead of ERPNext's
    # get_payment_entry directly. A gateway payment lands in a gateway-specific
    # clearing account rather than the company default and carries its own remarks.
    # Permissions are NOT special-cased: gateway webhooks run as the configured
    # service user, so the requirement is met by granting that role rather than by
    # bypassing the checks.
    # ------------------------------------------------------------------
    def _ensure_clearing_account(self, company):
        """A real Bank-type GL Account on `company`, standing in for a gateway
        clearing account (Mollie clearing, Ponto bank, ING). Created here rather
        than reusing the Mollie fixture so this suite stays gateway-agnostic."""
        name = frappe.db.get_value(
            "Account", {"company": company, "account_name": "Test Gateway Clearing"}, "name"
        )
        if name:
            return name
        parent = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": "Test Gateway Clearing",
                "company": company,
                "parent_account": parent,
                "account_type": "Bank",
                "is_group": 0,
                "account_currency": frappe.db.get_value("Company", company, "default_currency"),
            }
        ).insert()
        self.track_doc("Account", account.name)
        return account.name

    def test_bank_account_sets_the_receiving_side_of_the_entry(self):
        """A gateway payment must land in its clearing account, not the company default.

        `paid_to` is the load-bearing assertion: the clearing account is created fresh
        and is never the company's default bank account, so this only holds if
        `bank_account` reached `get_payment_entry`. Drop the pass-through and ERPNext
        resolves the company default instead.

        Deliberately does NOT assert `paid_to_account_currency`. ERPNext does derive it
        from the same resolved account (inside `get_payment_entry`), but the clearing
        account here carries the company's own currency, so that assertion holds whether
        or not the currency tracked the account - it would claim a guarantee it cannot
        provide. Proving it needs a differing-currency account, which drags in
        multi-currency conversion this test is not about.
        """
        invoice = self._create_test_invoice(amount=Decimal("60.00"))
        invoice.submit()
        clearing = self._ensure_clearing_account(invoice.company)
        self.assertNotEqual(
            clearing,
            frappe.db.get_value("Company", invoice.company, "default_bank_account"),
            "the fixture must differ from the default, or paid_to proves nothing",
        )

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("60.00"),
            posting_date=getdate(),
            reference_no="GATEWAY-BANK",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
            bank_account=clearing,
        )

        self.assertEqual(payment_entry.paid_to, clearing)

    def test_remarks_override_the_generated_text(self):
        """Gateways carry their own remarks (payment id, orphan banner, link name).

        ERPNext generates a default remark, so the test asserts the supplied text is
        used INSTEAD of it, not merely that the field is non-empty.
        """
        invoice = self._create_test_invoice(amount=Decimal("60.00"))
        invoice.submit()
        remarks = "Membership dues via Mollie (awaiting settlement). Payment tr_test_12345"

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("60.00"),
            posting_date=getdate(),
            reference_no="GATEWAY-REMARKS",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
            remarks=remarks,
        )

        self.assertEqual(payment_entry.remarks, remarks)
        # Read back from the DB: Payment Entry.validate() regenerates remarks unless
        # custom_remarks is set, so the in-memory value alone would not prove it stuck.
        self.assertEqual(frappe.db.get_value("Payment Entry", payment_entry.name, "remarks"), remarks)

    # ------------------------------------------------------------------
    # Money correctness: the service must not re-assert amounts that ERPNext
    # deliberately adjusted. See the two tests below.
    # ------------------------------------------------------------------

    def _ensure_company_discount_account(self, company):
        """Point the company at a discount account so ERPNext can book the discount loss.

        set_pending_discount_loss() reads Company.default_discount_account (or
        round_off_account when book_tax_discount_loss is on) to build the deductions
        row. Without it the row cannot be created and the scenario under test never
        forms. Privileged fixture setup belongs in a helper, not a test body.
        """
        # Pin the branch this helper actually prepares. Accounts Settings ships with
        # book_tax_discount_loss = 0, but if a site enables it ERPNext reads
        # round_off_account instead and the account set below is never used - the test
        # would then pass or fail for a reason unrelated to the service.
        self.assertFalse(
            frappe.get_single_value("Accounts Settings", "book_tax_discount_loss"),
            "This test prepares default_discount_account; with book_tax_discount_loss "
            "enabled ERPNext books the discount loss to round_off_account instead.",
        )
        account = frappe.get_cached_value("Company", company, "default_discount_account")
        if account:
            return account
        account = frappe.db.get_value(
            "Account",
            {"company": company, "root_type": "Expense", "is_group": 0},
            "name",
        )
        self.assertIsNotNone(account, f"No expense account available on {company} to book discount loss")
        frappe.db.set_value("Company", company, "default_discount_account", account)
        frappe.clear_cache(doctype="Company")
        return account

    def _append_discount_term(self, invoice, discount_percent):
        """Give the invoice a payment term carrying a live early-payment discount.

        Mutates the schedule row ERPNext already generated rather than replacing the
        child table: the invoice is inserted by the factory, and swapping the rows out
        leaves the new one unresolvable on save ("Payment Schedule <hash> not found").
        """
        if not invoice.get("payment_schedule"):
            invoice.append(
                "payment_schedule",
                {
                    "due_date": frappe.utils.add_days(frappe.utils.today(), 30),
                    "invoice_portion": 100,
                    "payment_amount": invoice.grand_total,
                },
            )
        for term in invoice.payment_schedule:
            term.discount_type = "Percentage"
            term.discount = discount_percent
            # Must be in the future: apply_early_payment_discount tests
            # `reference_date <= term.discount_date`.
            term.discount_date = frappe.utils.add_days(frappe.utils.today(), 7)
            # ERPNext requires due_date > discount_date on the same row.
            term.due_date = frappe.utils.add_days(frappe.utils.today(), 30)
        invoice.due_date = frappe.utils.add_days(frappe.utils.today(), 30)
        invoice.save()

    def test_early_payment_discount_is_not_overwritten(self):
        """A live discount term must not leave a phantom unallocated balance.

        ERPNext reduces paid_amount by the discount and books the discount as a
        `deductions` row (apply_early_payment_discount + set_pending_discount_loss).
        Re-asserting the full amount afterwards does NOT throw, as one might expect:
        set_unallocated_amount tests
        `base_total_allocated < base_paid_amount + deductions_to_consider`, which is
        `A < A + D` -> true, so it silently absorbs the discount into
        unallocated_amount and difference_amount still nets to zero. The entry then
        submits and posts a debtors credit of A + D - a credit the customer never paid.

        Asserting unallocated_amount is what distinguishes the two behaviours; the
        submit succeeding does not.

        The service now suppresses the discount outright (the gateway moved cash; the
        payer elected nothing), so paid_amount is the full amount requested and no
        deductions row survives. See
        test_partial_payment_against_discounted_invoice_records_full_cash for the case
        that actually distinguishes suppressing from merely not overriding.
        """
        # A DRAFT invoice: the factory submits by default, and the discount terms
        # have to be in place before submission (they are not editable after).
        invoice = self.create_test_sales_invoice(
            customer=self.test_customer.name,
            posting_date=getdate(),
            due_date=getdate(),
            items=[{"item_code": self.test_item_code, "qty": 1, "rate": 100.0}],
            status="Draft",
        )
        self._ensure_company_discount_account(invoice.company)
        self._append_discount_term(invoice, discount_percent=10)
        invoice.submit()

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("100.00"),
            posting_date=getdate(),
            reference_no="DISCOUNT-REF-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
        )

        self.assertEqual(
            flt(payment_entry.unallocated_amount, 2),
            0.0,
            "The discount was absorbed into unallocated_amount, which means the "
            "service re-asserted paid_amount over ERPNext's discounted figure.",
        )
        self.assertEqual(
            flt(payment_entry.paid_amount, 2),
            100.0,
            "paid_amount must equal the cash the gateway moved, with the early-payment "
            "discount suppressed.",
        )
        self.assertFalse(
            payment_entry.get("deductions"),
            "the discount deductions row must not survive suppression",
        )

    def test_partial_payment_against_discounted_invoice_records_full_cash(self):
        """A partial payment must debit the bank by the cash received, not less.

        This is the case the full-payment test cannot see. ERPNext computes the
        early-payment discount from the WHOLE invoice (`doc.base_grand_total`, in
        `apply_early_payment_discount`) and subtracts it from paid_amount, while every caller
        here passes only the cash the gateway moved - min(amount, outstanding). So a
        40.00 payment against a 100.00 invoice with a 10% term would post a bank debit
        of 30.00 against 40.00 of real cash, leaving the clearing account unable to
        reconcile against the gateway settlement.

        Both prior behaviours fail this: overriding paid_amount afterwards (the
        original code) left a 10.00 phantom unallocated balance, and simply not
        overriding it left paid_amount at 30.00.
        """
        invoice = self.create_test_sales_invoice(
            customer=self.test_customer.name,
            posting_date=getdate(),
            due_date=getdate(),
            items=[{"item_code": self.test_item_code, "qty": 1, "rate": 100.0}],
            status="Draft",
        )
        self._ensure_company_discount_account(invoice.company)
        self._append_discount_term(invoice, discount_percent=10)
        invoice.submit()

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("40.00"),
            posting_date=getdate(),
            reference_no="DISCOUNT-PARTIAL-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
        )

        self.assertEqual(
            flt(payment_entry.paid_amount, 2),
            40.00,
            "the bank must be debited by the cash actually received",
        )
        self.assertEqual(flt(payment_entry.unallocated_amount, 2), 0.0)
        self.assertFalse(payment_entry.get("deductions"))
        # The invoice keeps the rest outstanding - a discount the payer never elected
        # must not be written off here.
        self.assertEqual(
            flt(frappe.db.get_value("Sales Invoice", invoice.name, "outstanding_amount"), 2), 60.00
        )

    def _create_bank_transaction(self, company, amount):
        """A real Bank Transaction to link against.

        custom_bank_transaction is a Link to Bank Transaction, so the value has to
        resolve. That is itself part of the fix: the old stray `bank_transaction`
        attribute was dropped before validation, so it accepted any string silently.
        """
        bank_account = frappe.db.get_value("Bank Account", {"company": company}, "name")
        if not bank_account:
            bank_name = "Test Bank PECS"
            if not frappe.db.exists("Bank", bank_name):
                frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)
            account = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
            )
            self.assertIsNotNone(account, f"No bank account available on {company}")
            bank_account = (
                frappe.get_doc(
                    {
                        "doctype": "Bank Account",
                        "account_name": "Test PECS Bank Account",
                        "bank": bank_name,
                        "company": company,
                        "account": account,
                    }
                )
                .insert(ignore_permissions=True)
                .name
            )

        bank_transaction = frappe.new_doc("Bank Transaction")
        bank_transaction.date = frappe.utils.today()
        bank_transaction.bank_account = bank_account
        bank_transaction.deposit = amount
        bank_transaction.reference_number = frappe.generate_hash(length=10)
        # Bank Transaction defaults currency to the system default (INR on these
        # sites); it must match the bank account's account currency or validation
        # rejects it.
        gl_account = frappe.get_cached_value("Bank Account", bank_account, "account")
        if gl_account:
            bank_transaction.currency = frappe.get_cached_value("Account", gl_account, "account_currency")
        bank_transaction.insert(ignore_permissions=True)
        return bank_transaction

    def test_bank_transaction_name_is_persisted(self):
        """The bank_transaction_name parameter must land on a field that exists.

        The service used to assign `payment_entry.bank_transaction`, which is not a
        Payment Entry field in ERPNext nor a custom field in this app (the app's field
        is `custom_bank_transaction`). BaseDocument.get_valid_dict() drops unknown
        attributes silently, so the link was discarded on every reconciliation call.

        This does NOT restore anything to api/sepa_duplicate_prevention.py: that query
        filters on `custom_sepa_batch`, which no caller of this service sets.

        Read back from the DB, not from the in-memory doc: the old code set the stray
        attribute unconditionally, so an in-memory assertion passes against the bug.
        """
        invoice = self._create_test_invoice(amount=Decimal("40.00"))
        invoice.submit()
        bank_transaction = self._create_bank_transaction(invoice.company, 40.00)

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("40.00"),
            posting_date=getdate(),
            reference_no="BANKTRANS-REF-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
            bank_transaction_name=bank_transaction.name,
        )

        self.assertEqual(
            frappe.db.get_value("Payment Entry", payment_entry.name, "custom_bank_transaction"),
            bank_transaction.name,
        )

    # --- cash_received: recording an overpayment without losing the excess ---------

    def _debtors_account(self, company):
        return frappe.get_cached_value("Company", company, "default_receivable_account")

    def test_cash_received_records_full_cash_with_remainder_unallocated(self):
        """A gateway paying more than the invoice owes must post the WHOLE cash.

        Asserts the GL rather than only the amount fields. The failure this guards
        against is not a wrong `paid_amount` - it is a debtors credit that does not
        match the cash the gateway actually settled, which is invisible on the
        document and only shows up when the clearing account fails to reconcile.
        """
        invoice = self._create_test_invoice(amount=Decimal("30.00"))
        invoice.submit()

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("30.00"),
            cash_received=Decimal("100.00"),
            posting_date=getdate(),
            reference_no="OVERPAY-REF-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
        )

        pe = frappe.get_doc("Payment Entry", payment_entry.name)
        self.assertEqual(flt(pe.paid_amount, 2), 100.00)
        self.assertEqual(flt(pe.received_amount, 2), 100.00)
        self.assertEqual(flt(pe.references[0].allocated_amount, 2), 30.00)
        self.assertEqual(flt(pe.unallocated_amount, 2), 70.00)
        self.assertEqual(flt(pe.difference_amount, 2), 0.00)

        debtors = self._debtors_account(invoice.company)
        gl = frappe.get_all(
            "GL Entry",
            filters={"voucher_no": pe.name, "is_cancelled": 0},
            fields=["account", "debit", "credit", "against_voucher"],
        )

        # Two SEPARATE debtors credits: 30 carries against_voucher (settles the
        # invoice), 70 does not (sits as an advance). They must not merge - if they
        # ever do, the invoice is silently cleared for the full 100.
        allocated_credit = [r for r in gl if r.account == debtors and r.against_voucher == invoice.name]
        unallocated_credit = [r for r in gl if r.account == debtors and not r.against_voucher]
        self.assertEqual(len(allocated_credit), 1, f"expected one settled debtors row, got {gl}")
        self.assertEqual(flt(allocated_credit[0].credit, 2), 30.00)
        self.assertEqual(len(unallocated_credit), 1, f"expected one advance debtors row, got {gl}")
        self.assertEqual(flt(unallocated_credit[0].credit, 2), 70.00)

        # The bank side must carry the FULL cash, or the clearing account cannot
        # reconcile against the gateway settlement - the entire point of the change.
        bank_debit = sum(flt(r.debit) for r in gl if r.account != debtors)
        self.assertEqual(flt(bank_debit, 2), 100.00)

    def test_cash_received_defaults_to_the_allocation(self):
        """Omitting cash_received must leave every existing caller's posting unchanged."""
        invoice = self._create_test_invoice(amount=Decimal("45.00"))
        invoice.submit()

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("45.00"),
            posting_date=getdate(),
            reference_no="NOCASH-REF-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
        )

        pe = frappe.get_doc("Payment Entry", payment_entry.name)
        self.assertEqual(flt(pe.paid_amount, 2), 45.00)
        self.assertEqual(flt(pe.unallocated_amount, 2), 0.00)

    def test_cash_received_below_the_allocation_is_refused(self):
        """cash_received < amount would allocate money that never arrived."""
        invoice = self._create_test_invoice(amount=Decimal("50.00"))
        invoice.submit()

        with self.assertRaises(frappe.ValidationError) as ctx:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("50.00"),
                cash_received=Decimal("20.00"),
                posting_date=getdate(),
                reference_no="UNDERCASH-REF-001",
                reference_date=getdate(),
                mode_of_payment="Bank Transfer",
            )

        # Assert the MESSAGE, not just the type. ERPNext rejects this shortfall on its
        # own ("Difference Amount must be zero"), and the service re-wraps that as a
        # frappe.ValidationError too - its setup_keywords list contains "must be". So a
        # bare assertRaises passes with this guard deleted and pins nothing.
        self.assertIn("cannot be less than the amount allocated", str(ctx.exception))

    def test_overpayment_books_no_deductions_row(self):
        """An overpayment on a discount-free invoice must book no `deductions` row.

        NOT a test of the discount-argument swap, despite the obvious reading. This was
        originally named ...is_not_mistaken_for_an_early_payment_discount and claimed to
        pin that `_suppress_early_payment_discount` receives the ALLOCATION rather than
        the cash. A review disproved it: handed the cash, the helper skips its early
        return, clears an already-empty `deductions`, and assigns
        `paid = received = cash` - which the override two lines later assigns anyway. The
        resulting document is byte-identical, so the swap is genuinely unobservable here,
        and this test passed unchanged when the swap was simulated.

        The swap's only observable effect is on a CURRENCY BOUNDARY, where it throws the
        discount-related refusal instead of the overpayment one. That case IS now covered
        - see test_discount_suppression_is_handed_the_allocation_not_the_cash.

        What this DOES pin, and why it stays: a deductions row here would silently
        inflate `unallocated_amount` (set_unallocated_amount adds
        `deductions_to_consider`) while `difference_amount` still nets to zero, so the
        entry would submit having credited debtors more than the cash received.
        """
        invoice = self._create_test_invoice(amount=Decimal("30.00"))
        invoice.submit()

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("30.00"),
            cash_received=Decimal("80.00"),
            posting_date=getdate(),
            reference_no="NODISCOUNT-REF-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
        )

        pe = frappe.get_doc("Payment Entry", payment_entry.name)
        self.assertEqual(len(pe.deductions), 0, "a phantom discount was detected and booked")
        self.assertEqual(flt(pe.unallocated_amount, 2), 50.00)

    # ------------------------------------------------------------------
    # Currency boundary
    #
    # The service refuses an overpayment whose two sides sit in different
    # currencies, because a settlement webhook reports ONE figure and nothing says
    # which side of the boundary it belongs to. Left to ERPNext,
    # set_exchange_gain_loss() books the mismatch as a deductions row,
    # difference_amount still nets to zero, and the entry SUBMITS - debiting the
    # clearing account a converted figure for unconverted cash.
    #
    # Every test below needs a foreign-currency account, which is also the only
    # place the _suppress_early_payment_discount argument swap is observable. That
    # is why one fixture closes two long-standing gaps at once.
    # ------------------------------------------------------------------
    FX_CURRENCY = "USD"
    FX_RATE = 1.25  # EUR -> USD, chosen so 30.00 EUR is exactly 37.50 USD

    def _ensure_foreign_currency_clearing_account(self, company):
        """A Bank-type GL account in a currency the company does NOT use.

        `paid_from` on a Receive entry is the debtors account, which carries the
        company currency, so putting `paid_to` in another currency is all it takes to
        make `paid_from_account_currency != paid_to_account_currency` - the exact
        condition both refusals test. No foreign customer or foreign-currency invoice
        is needed, and adding one would drag in conversion behaviour these tests are
        not about.

        The Currency Exchange rows are NOT optional bookkeeping. Without a matching
        row, `erpnext.setup.utils.get_exchange_rate` falls through to a live HTTP call
        against the configured rate API and, when that fails, calls `frappe.log_error`.
        That would make these tests network-dependent AND trip the Error Log guard.
        Both directions are created because which one ERPNext asks for depends on the
        path taken; today it values the USD side against the company currency.
        """
        company_currency = frappe.db.get_value("Company", company, "default_currency")
        self.assertNotEqual(
            company_currency,
            self.FX_CURRENCY,
            "the fixture currency must differ from the company's, or there is no boundary",
        )

        for from_currency, to_currency, rate in (
            (company_currency, self.FX_CURRENCY, self.FX_RATE),
            (self.FX_CURRENCY, company_currency, 1 / self.FX_RATE),
        ):
            # Currency Exchange autonames from date + currencies + purpose, so an
            # insert of a row that already exists is a duplicate-key error rather than
            # a second row. Get-or-create, and only track what we actually created -
            # tracking a pre-existing row would schedule someone else's fixture for
            # deletion.
            existing = frappe.db.get_value(
                "Currency Exchange",
                {"from_currency": from_currency, "to_currency": to_currency, "date": frappe.utils.today()},
                "name",
            )
            if existing:
                continue
            rate_doc = frappe.get_doc(
                {
                    "doctype": "Currency Exchange",
                    "from_currency": from_currency,
                    "to_currency": to_currency,
                    "date": frappe.utils.today(),
                    "exchange_rate": rate,
                    "for_buying": 1,
                    "for_selling": 1,
                }
            ).insert()
            self.track_doc("Currency Exchange", rate_doc.name)

        account_name = f"Test FX Clearing {self.FX_CURRENCY}"
        name = frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")
        if name:
            return name
        parent = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Bank", "is_group": 1}, "name"
        ) or frappe.db.get_value("Account", {"company": company, "root_type": "Asset", "is_group": 1}, "name")
        account = frappe.get_doc(
            {
                "doctype": "Account",
                "account_name": account_name,
                "company": company,
                "parent_account": parent,
                "account_type": "Bank",
                "is_group": 0,
                "account_currency": self.FX_CURRENCY,
            }
        ).insert()
        self.track_doc("Account", account.name)
        return account.name

    def _assert_is_a_boundary(self, invoice, clearing):
        """Fail loudly if the fixture stopped producing a currency boundary.

        Without this, a change that quietly aligned the two currencies would leave
        both refusal tests passing against a condition that can no longer occur -
        green, and pinning nothing.
        """
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        probe = get_payment_entry(
            dt="Sales Invoice",
            dn=invoice.name,
            party_amount=float(invoice.outstanding_amount),
            bank_account=clearing,
            payment_type="Receive",
            reference_date=getdate(),
        )
        self.assertNotEqual(
            probe.paid_from_account_currency,
            probe.paid_to_account_currency,
            "fixture no longer crosses a currency boundary; the refusal tests below are vacuous",
        )

    def test_overpayment_across_a_currency_boundary_is_refused(self):
        """One gateway figure cannot be assigned to both sides of a currency boundary.

        The failure being prevented is not an exception - it is a SUBMITTED entry.
        Assigning the cash to `paid_amount` and `received_amount` alike makes
        set_exchange_gain_loss() absorb the mismatch into a deductions row;
        `difference_amount` still nets to zero, so ERPNext accepts the document and
        the clearing account is debited a converted figure for unconverted cash. That
        reconciles against nothing and is invisible on the entry itself.

        Asserts the MESSAGE, not just the type: ERPNext raises frappe.ValidationError
        across this path for several unrelated reasons, so a bare assertRaises would
        pass with the guard deleted.
        """
        invoice = self._create_test_invoice(amount=Decimal("30.00"))
        invoice.submit()
        clearing = self._ensure_foreign_currency_clearing_account(invoice.company)
        self._assert_is_a_boundary(invoice, clearing)

        # The refusal is raised INSIDE the service's try block, so its handler logs
        # the throw before re-raising. Declared rather than left to trip the Error Log
        # guard, and scoped to this message so an unrelated error still fails the test.
        self.expectErrorLog("crosses a currency boundary")

        with self.assertRaises(frappe.ValidationError) as ctx:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("30.00"),
                cash_received=Decimal("100.00"),
                posting_date=getdate(),
                reference_no="FX-OVERPAY-001",
                reference_date=getdate(),
                mode_of_payment="Bank Transfer",
                bank_account=clearing,
            )

        self.assertIn("exceeds the outstanding amount and crosses a currency boundary", str(ctx.exception))

    def test_discount_suppression_is_handed_the_allocation_not_the_cash(self):
        """`_suppress_early_payment_discount` must receive the ALLOCATION.

        This is the test test_overpayment_books_no_deductions_row could not be. That
        one was named for this swap and was disproved: on the same-currency path,
        handing the helper the cash produces a byte-identical document, so the swap is
        genuinely unobservable there.

        Here it is observable. The helper's detection is an equality test against the
        figure it is given, and pre-discount `paid_amount` equals the allocation and
        nothing else. Handed the cash on an overpayment, the equality fails, so it
        concludes a discount was applied and - because this crosses a currency boundary
        - throws the DISCOUNT refusal about an invoice that has no discount, instead of
        the overpayment refusal that actually applies.

        The invoice here is deliberately discount-free, which is what makes the
        negative assertion meaningful. Verified by mutation: passing `cash_received`
        into the helper flips the message and fails this test.
        """
        invoice = self._create_test_invoice(amount=Decimal("30.00"))
        invoice.submit()
        clearing = self._ensure_foreign_currency_clearing_account(invoice.company)
        self.assertFalse(
            invoice.get("payment_schedule") and any(r.discount for r in invoice.payment_schedule),
            "the invoice must carry no early-payment discount, or the assertion below is meaningless",
        )
        self.expectErrorLog("crosses a currency boundary")

        with self.assertRaises(frappe.ValidationError) as ctx:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("30.00"),
                cash_received=Decimal("100.00"),
                posting_date=getdate(),
                reference_no="FX-SWAP-001",
                reference_date=getdate(),
                mode_of_payment="Bank Transfer",
                bank_account=clearing,
            )

        self.assertNotIn(
            "carries an early-payment discount",
            str(ctx.exception),
            "the discount helper was handed the cash instead of the allocation",
        )

    def test_ordinary_foreign_currency_payment_is_not_refused(self):
        """The refusal is scoped to the OVERPAYMENT path, not to foreign currency.

        Without this, the two tests above could be satisfied by refusing every
        differing-currency payment outright - both would stay green while the service
        lost the ability to record ordinary gateway settlements into a
        foreign-currency clearing account.

        The two amounts are deliberately different: `paid_amount` is the 30.00 the
        invoice is settled for, `received_amount` the 37.50 that lands in the USD
        account. A single figure on both sides is exactly the corruption the
        overpayment path refuses to risk.
        """
        invoice = self._create_test_invoice(amount=Decimal("30.00"))
        invoice.submit()
        clearing = self._ensure_foreign_currency_clearing_account(invoice.company)

        payment_entry = payment_entry_service.create_payment_entry_from_invoice(
            invoice_name=invoice.name,
            amount=Decimal("30.00"),
            posting_date=getdate(),
            reference_no="FX-ORDINARY-001",
            reference_date=getdate(),
            mode_of_payment="Bank Transfer",
            bank_account=clearing,
        )

        pe = frappe.get_doc("Payment Entry", payment_entry.name)
        self.assertEqual(pe.docstatus, 1, "an ordinary foreign-currency payment must still submit")
        self.assertEqual(pe.paid_to, clearing)
        self.assertEqual(pe.paid_to_account_currency, self.FX_CURRENCY)
        self.assertEqual(flt(pe.paid_amount, 2), 30.00)
        self.assertEqual(flt(pe.received_amount, 2), 37.50)
        self.assertEqual(flt(pe.unallocated_amount, 2), 0.00)
        self.assertEqual(flt(pe.difference_amount, 2), 0.00)
        self.assertEqual(len(pe.deductions), 0)

    def test_unknown_custom_field_throws_instead_of_being_dropped(self):
        """A misnamed custom field must abort, not vanish into a log.

        The old behaviour warned to frappe.logger() and continued, so a typo or a renamed
        field left a SUBMITTED payment silently missing the link (custom_member, the SEPA
        batch reference) that a later reconciliation or dedup query needs to find it.
        """
        invoice = self._create_test_invoice(amount=Decimal("25.00"))
        invoice.submit()

        with self.assertRaises(frappe.ValidationError) as ctx:
            payment_entry_service.create_payment_entry_from_invoice(
                invoice_name=invoice.name,
                amount=Decimal("25.00"),
                posting_date=getdate(),
                reference_no="BADFIELD-REF-001",
                reference_date=getdate(),
                mode_of_payment="Bank Transfer",
                custom_fields={"custom_field_that_does_not_exist": "x"},
            )
        self.assertIn("custom_field_that_does_not_exist", str(ctx.exception))

    def test_race_predicate_is_evaluated_against_the_allocation_not_the_cash(self):
        """`invoice_cannot_absorb` must be asked about the ALLOCATION.

        The predicate is `outstanding < figure`. The Mollie lost-race handler uses it to
        decide whether a ValidationError means "another process consumed this invoice"
        (recover by recording the payment unallocated) or something else (re-raise).

        Handed the full cash on an overpayment, it is true whether or not a race
        occurred - so ANY ValidationError during an overpayment, including a frozen
        account, a closed period or the service's own currency guard, would be laundered
        into a silent full-amount unallocated Payment Entry. This pins the distinction
        the caller depends on, which no test covered.
        """
        from verenigingen.verenigingen_payments.utils.payment_allocation import (
            invoice_cannot_absorb,
        )

        invoice = self._create_test_invoice(amount=Decimal("30.00"))
        invoice.submit()

        # Nothing has happened to the invoice: it can absorb its own outstanding.
        self.assertFalse(
            invoice_cannot_absorb(invoice.name, 30.00),
            "a healthy invoice was reported as unable to absorb its own outstanding",
        )
        # ...but the full cash of an overpayment exceeds it, which is why passing the
        # cash here would report a lost race on every overpayment.
        self.assertTrue(
            invoice_cannot_absorb(invoice.name, 100.00),
            "the predicate must be true for a figure above outstanding - if this fails "
            "the caller's argument choice no longer matters and this test is moot",
        )


# A class named TestPaymentEntryCreationServiceIntegration stood here, holding three
# skipped stubs with empty `pass` bodies and TODOs: "integration with ERPNext's
# get_payment_entry", "bank reconciliation workflow" and "batch processing workflow".
# All three were deleted rather than unskipped, because each names a behaviour that is
# already tested for real, and an empty stub carrying that name is worse than nothing -
# it reads as coverage of a thing nobody is covering here.
#
#   * get_payment_entry: the class above IS that integration test. Every test in it
#     drives the service against a real submitted Sales Invoice built by the factory
#     (real Item, income account, cost center, Customer), and the service calls
#     erpnext ... get_payment_entry on it directly. Its auto-population is asserted at
#     the field level (party, references[0].allocated_amount, the paid_from/paid_to
#     the bank_account argument derives, the deductions ERPNext adds for an
#     early-payment discount) and at the GL level in the cash_received tests. Taxes,
#     the one item on the stub's list not exercised there, would add nothing: the
#     service has no tax-sensitive branch - taxes only move the invoice outstanding,
#     which callers cap `amount` against before the service ever sees it.
#
#   * bank reconciliation: tests/payment/test_bank_transaction_reconciliation.py runs
#     the workflow end-to-end on a real DB (73 tests), including the two entry points
#     that call this service - create_payment_entry_from_transaction and
#     create_payment_entries_from_batch - covering the skip-Failed-row, skip-Pending-row
#     and re-run-idempotency guards.
#
#   * batch processing: tests/sepa/test_batch_processing_service_happy_path.py drives
#     BatchProcessingService.mark_batch_invoices_as_paid on a genuinely submitted
#     Direct Debit Batch and asserts the Payment Entry it books through this service,
#     with tests/sepa/test_dd_batch_pipeline_coverage.py on the guard branches.
#
# Nothing was lost on the cash_received path either: neither the reconciliation nor the
# batch caller passes cash_received (see the comment at
# bank_transaction_reconciliation.py:548), so there is no caller-level overpayment
# behaviour for a test here to reach.
