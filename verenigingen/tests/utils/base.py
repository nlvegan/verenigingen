# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""
Verenigingen Operational Test Framework
======================================

🔧 **OPERATIONAL TESTING FRAMEWORK** - Use for integration, UI, and workflow testing

WHEN TO USE VereningingenTestCase:
✅ Integration tests requiring mocking (external APIs, file systems)
✅ UI/form testing with CSRF handling and request simulation
✅ Workflow tests that need operational conveniences
✅ Performance tests with controlled environments
✅ Tests requiring extensive setup/teardown infrastructure

WHEN NOT TO USE (Use EnhancedTestCase instead):
❌ Business logic validation that should catch production issues
❌ Data integrity testing where field validation is critical
❌ Tests that need to verify real system behavior
❌ Core business rule testing (use Enhanced for field safety)

Key Features:
- Extensive mocking capabilities for external dependencies
- CSRF and request environment simulation
- Operational convenience methods (payment modes, regions)
- Traditional test-prefixed factory methods (create_test_*)

Companion Framework: EnhancedTestCase (enhanced_test_factory.py)
"""

import json
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from verenigingen.tests.utils.error_log_guard import ErrorLogGuardMixin


class VereningingenTestCase(ErrorLogGuardMixin, FrappeTestCase):
    """
    🔧 Operational Testing Framework - Mocking, Integration & Workflow Testing

    Optimized for tests that need extensive mocking, CSRF handling, and operational
    conveniences. Provides 31 factory methods with create_test_* naming convention.

    Use when you need: mocking, UI testing, workflow integration, performance testing
    Don't use for: business logic validation, production issue discovery, field safety
    """

    #: The harness-owned company pinned on `Verenigingen Settings` by `setUpClass`.
    #: Declared here so a subclass that forgets `super().setUpClass()` gets the
    #: explanatory error from `_owned_company_and_income_account()` rather than a
    #: bare AttributeError.
    settings_company = None

    @classmethod
    def setUpClass(cls):
        """Set up class-level test environment"""
        super().setUpClass()
        cls._ensure_test_environment()
        cls._track_created_docs = []

        # Validate required fixtures are loaded (run once per test class)
        cls._validate_fixtures()

        cls.setup_payment_modes()  # Ensure payment modes exist for all tests

        # Ensure a current-year Fiscal Year (covering all companies) and a global
        # default Company exist once per session. erpnext v16 leaves neither
        # reliably set on fresh CI sites, which breaks dated-document submission
        # and the Opportunity.company `:Company` default. EnhancedTestCase runs
        # the same setup; the shared session flag makes it run once regardless of
        # which base class executes first.
        if not getattr(frappe.flags, "_test_fiscal_year_ensured", False):
            from verenigingen.tests.setup import (
                ensure_default_company,
                ensure_test_fiscal_year_for_all_companies,
            )

            ensure_test_fiscal_year_for_all_companies()
            ensure_default_company()
            frappe.flags._test_fiscal_year_ensured = True

        # The "Netherlands" Territory is hardcoded by fixtures throughout this app
        # and nothing else creates it on a fresh site (hrms's before_tests runs
        # setup_complete with country="India"). It used to be created only by
        # EnhancedTestDataFactory, so classes on THIS base never got it and merely
        # inherited whatever an earlier EnhancedTestCase happened to leave behind.
        # Cheap: one db.exists once the row is present.
        from verenigingen.tests.setup import ensure_netherlands_territory

        ensure_netherlands_territory()

        # OWN the company production code resolves from Verenigingen Settings,
        # instead of inheriting whatever ran before us. Much of the code under
        # test reads that single rather than taking a company argument
        # (sepa_config_manager, chapter_finance_service, invoice_generator,
        # department_sync_service...), so a test whose fixtures live under the
        # harness company fails when the single points elsewhere.
        #
        # Classes on this base used to pass only because an EnhancedTestCase
        # test earlier in the same shard set it and the restore that should have
        # undone it was never reached (#312) -- the same shape as the territory
        # note above. Pinning here is that same value, made deterministic. See #308.
        #
        # Class scope, not setUp: this commits, and the compat FrappeTestCase
        # this inherits rolls back only once per CLASS. A per-test commit would
        # make every untracked row a test creates durable.
        from verenigingen.tests.support.verenigingen_settings import own_settings_company

        # Kept on the class so subclasses can build fixtures under the SAME company
        # rather than scanning for one that happens to look usable -- see #431 for
        # what borrowing costs, and #394 for the class it belongs to.
        cls.settings_company = own_settings_company(cls)

    @classmethod
    def tearDownClass(cls):
        """Clean up class-level test data"""
        cls._cleanup_tracked_docs()
        super().tearDownClass()

    @classmethod
    def _validate_fixtures(cls):
        """
        Validate required fixtures are loaded before running tests.

        Prints warnings if fixtures are missing but doesn't block tests.
        Set SKIP_FIXTURE_VALIDATION=1 environment variable to skip validation.
        """
        import os

        # Allow skipping fixture validation via environment variable
        if os.environ.get("SKIP_FIXTURE_VALIDATION"):
            return

        # Only validate once globally (not per test class)
        if hasattr(frappe.flags, "fixtures_validated"):
            return
        frappe.flags.fixtures_validated = True

        from verenigingen.tests.utils.fixture_validator import validate_test_fixtures

        # Validate core fixtures (non-blocking - just warns)
        categories = ["roles", "regions"]
        if not validate_test_fixtures(categories=categories, quiet=False):
            print("\n⚠️  WARNING: Some fixtures are missing but tests will continue")
            print("    Tests may fail with cryptic LinkValidationError messages")
            print("    Set SKIP_FIXTURE_VALIDATION=1 to hide this warning\n")

    def setUp(self):
        """Set up test-specific environment"""
        super().setUp()

        # BATCH-QUEUE ISOLATION: the FinancialHistoryBatchProcessor's queues are
        # class-level and therefore PROCESS-global, and add_invoice_to_payment_history()
        # drains them INLINE. An entry left by a prior (rolled-back) test names a Member
        # that no longer exists, and processing it used to issue a transaction-wide
        # rollback that wiped THIS test's uncommitted setUp data -- surfacing four frames
        # later as "Member ... not found" from an unrelated reload().
        # EnhancedTestCase has done this since the queue was found to be process-global;
        # this base class is its sibling and never got it, which is why
        # test_payment_system_functionality (a VereningingenTestCase) still failed in CI.
        try:
            from verenigingen.utils.financial_history_batch_processor import (
                FinancialHistoryBatchProcessor,
            )

            FinancialHistoryBatchProcessor.reset_queues()
        except Exception as e:  # never break the test lifecycle over this
            # print, not logger.warning: bare loggers default to ERROR under
            # `bench run-tests`, so a warning here would be discarded entirely.
            print(f"Financial batch queue reset failed: {e}")

        self._test_docs = []
        self._original_session_user = frappe.session.user
        # Track test start time for error monitoring
        self._test_start_time = frappe.utils.now()

        # Initialize test data factory
        from verenigingen.tests.fixtures.test_data_factory import CoreTestDataFactory

        self.factory = CoreTestDataFactory()

        # Set up test request context for API security framework
        self._setup_test_request_context()

        # Store original commit behavior
        self._original_commit = frappe.db.commit

        # Mock problematic validations that interfere with tests
        self._setup_test_mocks()

    def tearDown(self):
        """Clean up test-specific data"""
        # Capture Error Logs written during this test BEFORE any cleanup/rollback --
        # an uncommitted frappe.log_error() row is erased by the rollbacks below.
        self._capture_test_error_logs()

        # Restore original session user
        frappe.session.user = self._original_session_user

        # Clean up customers linked to members BEFORE deleting members
        self._cleanup_member_customers()

        # Clean up test docs with retry logic for lock timeouts
        for doc_info in reversed(self._test_docs):
            self._cleanup_document_with_retry(doc_info)

        # Report cleanup summary if there were failures
        self._report_cleanup_summary()

        # Clean up test request context
        self._cleanup_test_request_context()

        # Restore original behaviors
        self._cleanup_test_mocks()

        super().tearDown()

        # LAST: warn (default) or fail (VERENIGINGEN_FAIL_ON_ERROR_LOG=1) on captured
        # Error Logs. Done after cleanup so a raise here never skips teardown.
        self._finalize_error_log_check()

        # Documents this test tracked and cleanup could not delete. Same ordering
        # contract, and the same machine-readable form EnhancedTestCase uses (#328).
        self._finalize_leak_check()

    def _finalize_leak_check(self):
        """Report tracked documents that survived cleanup.

        `_report_cleanup_summary` above already prints these, but for a human:
        a "CLEANUP SUMMARY" block the leak ratchet cannot parse. The rows are the
        same; only the format is machine-readable.
        """
        from verenigingen.tests.utils.leak_guard import report_leaks

        rows = [
            {
                "doctype": doc["doctype"],
                "name": doc["name"],
                "error": doc.get("cleanup_error"),
            }
            for doc in getattr(self, "_test_docs", [])
            if doc.get("cleanup_status") == "failed"
        ]
        test_id = (
            f"{type(self).__module__}.{type(self).__name__}."
            f"{getattr(self, '_testMethodName', '?')}"
        )
        report_leaks(rows, test_id)

    def _report_cleanup_summary(self):
        """Report summary of cleanup results, highlighting any failures."""
        if not self._test_docs:
            return

        failed = [d for d in self._test_docs if d.get("cleanup_status") == "failed"]
        success = [d for d in self._test_docs if d.get("cleanup_status") == "success"]
        skipped = [d for d in self._test_docs if d.get("cleanup_status") == "skipped"]

        if failed:
            print(f"\n⚠️  CLEANUP SUMMARY for {self._testMethodName}:")
            print(f"   ✓ Success: {len(success)} | ⊘ Skipped: {len(skipped)} | ✗ Failed: {len(failed)}")
            print("   Failed documents (may need manual cleanup):")
            for doc in failed:
                error = doc.get("cleanup_error", "Unknown error")
                print(f"     - {doc['doctype']}: {doc['name']}")
                print(f"       Error: {error[:100]}{'...' if len(error) > 100 else ''}")

    # Ledgers that key rows to a parent by (voucher_type, voucher_no) and are NOT
    # removed when that parent is deleted. Deliberately data-driven rather than a
    # list of voucher doctypes: the set of things that post to the ledger grows
    # with every erpnext release, and a stale allowlist fails open -- silently
    # stranding rows again.
    LEDGER_DOCTYPES = ("GL Entry", "Payment Ledger Entry")

    def _has_ledger_rows(self, doctype, name):
        """True when deleting this document would strand ledger rows behind it."""
        return any(
            frappe.db.exists(ledger, {"voucher_type": doctype, "voucher_no": name})
            for ledger in self.LEDGER_DOCTYPES
        )

    def _cancel_if_submitted(self, doctype, name):
        """Cancel a submitted document so the delete below can remove it.

        `frappe.model.delete_doc` runs `check_permission_and_not_submitted(doc)`
        BEFORE its `if not force:` guard, so `force=True` does NOT bypass the
        submitted check -- a submitted document simply cannot be force-deleted.
        Every submitted Membership a test created therefore survived cleanup and
        was recorded as a leak: 24 per run in
        tests/membership/test_contribution_amendment_request alone, and the reason
        the retired tests/payment/test_self_service_fee_adjustment carried a
        9-record entry in known_test_leaks.txt.

        `is_submittable`, NOT `docstatus == 1` alone: erpnext calls `gle.submit()`
        on GL Entry, which is `is_submittable = 0`, and cancelling those raises.
        Child rows inherit docstatus from their parent too.

        LEDGER-BEARING VOUCHERS ARE LEFT ALONE. Cancelling one does not remove its
        ledger rows -- it WRITES MORE. Measured on a real submitted Payment Entry:

            after submit   2 GL Entry, 1 Payment Ledger Entry
            after cancel   4 GL Entry, 2 Payment Ledger Entry   (reversals)
            after delete   4 GL Entry, 2 Payment Ledger Entry   (parent gone)

        `delete_doc` does not take the ledger rows with it, so cancel-then-delete
        turns one honestly-reported submitted parent into six ORPHANED ledger rows
        pointing at a voucher_no that no longer exists -- and the drain only walks
        tracked documents, so it never tracked those rows, never counted them and
        reported the cleanup as a success. That is strictly worse than the leak it
        replaces: a stranded Payment Ledger Entry is what made a later Sales
        Invoice undeletable in #328, and it is what broke
        e_boekhouden/test_cleanup_utils_coverage on CI. The name is reused because
        `delete_doc` calls `revert_series_if_last()`, which DECREMENTS the naming
        series when the deleted document is the last in it: the cancelled parent
        goes, the series rewinds, the ledger rows stay, and the next Payment Entry
        is handed the same name and is born already linked to them.

        So: skip the cancel when the document already has ledger rows, and let the
        delete fail and the leak be reported under its own name. Checked BEFORE
        cancelling rather than after, so erpnext's on_cancel -- which mutates OTHER
        documents -- never runs for these at all, and the fix does not depend on a
        savepoint surviving an inner commit.

        Wrapped in a savepoint because `_save` writes docstatus=2 BEFORE
        `run_post_save_methods()` fires on_cancel and check_no_back_links_exist().
        A failure part-way would otherwise leave a cancelled-but-undeleted record
        whose on_cancel side effects already ran -- strictly worse than the
        submitted leak it replaces, since erpnext's cancel mutates OTHER
        documents. On any failure we roll back and return, leaving the document
        submitted so the delete fails and the caller records an ordinary leak:
        exactly the behaviour that existed before this method.

        EnhancedTestCase._remove_drained_record carries the same logic. The two
        bases are siblings (both derive from FrappeTestCase) and neither can
        inherit the other's teardown, so the rule is stated in both places rather
        than shared -- see the note in tests/utils/leak_guard.py.
        """
        if not (
            frappe.get_meta(doctype).is_submittable
            and frappe.db.get_value(doctype, name, "docstatus") == 1
        ):
            return

        if self._has_ledger_rows(doctype, name):
            return

        savepoint = f"cleanup_{frappe.generate_hash(length=8)}"
        frappe.db.savepoint(savepoint)
        try:
            doc = frappe.get_doc(doctype, name)
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            doc.cancel()
        except Exception as cancel_error:
            print(f"Could not cancel {doctype} {name} before delete: {cancel_error}")
            try:
                frappe.db.rollback(save_point=savepoint)
            except Exception:
                # The savepoint is gone -- an inner commit dropped it, or a deadlock
                # rolled the whole transaction back (MySQL 1305). Nothing left to
                # undo; fall through and let the delete record the real leak.
                pass

    def _cleanup_document_with_retry(self, doc_info, max_retries=3, retry_delay=0.5):
        """Clean up document with retry logic for lock timeouts.

        Updates doc_info['cleanup_status'] to track cleanup result.
        """
        import time

        for attempt in range(max_retries):
            try:
                if frappe.db.exists(doc_info["doctype"], doc_info["name"]):
                    # Ensure any pending transactions are rolled back before cleanup
                    frappe.db.rollback()
                    self._cancel_if_submitted(doc_info["doctype"], doc_info["name"])
                    frappe.delete_doc(doc_info["doctype"], doc_info["name"], force=True)
                    # Commit the deletion to release locks
                    frappe.db.commit()
                    doc_info["cleanup_status"] = "success"
                else:
                    doc_info["cleanup_status"] = "skipped"  # Already deleted
                break  # Success, exit retry loop
            except frappe.exceptions.QueryTimeoutError as e:
                if attempt < max_retries - 1:
                    print(
                        f"Lock timeout cleaning up {doc_info['doctype']} {doc_info['name']}, retrying (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(retry_delay)
                    # Rollback any stuck transaction before retrying
                    frappe.db.rollback()
                else:
                    print(
                        f"Failed to clean up {doc_info['doctype']} {doc_info['name']} after {max_retries} attempts: {e}"
                    )
                    doc_info["cleanup_status"] = "failed"
                    doc_info["cleanup_error"] = str(e)
            except (frappe.DoesNotExistError, frappe.ValidationError, frappe.PermissionError) as e:
                # Document may already be deleted or validation prevents deletion
                print(f"Error cleaning up {doc_info['doctype']} {doc_info['name']}: {e}")
                frappe.db.rollback()
                doc_info["cleanup_status"] = "failed"
                doc_info["cleanup_error"] = str(e)
                break  # Don't retry for these errors

    # Error Log detection now lives in ErrorLogGuardMixin (error_log_guard.py); tearDown
    # calls _capture_test_error_logs() early and _finalize_error_log_check() last.

    def _setup_test_request_context(self):
        """Set up proper request context for API security framework"""
        # Mock request environment for CSRF validation
        self._mock_request = MagicMock()
        self._mock_request.method = "POST"
        self._mock_request.headers = {
            "X-Verenigingen-CSRF-Token": "test-csrf-token",
            "X-Frappe-CSRF-Token": "test-csrf-token",
        }

        # Set up frappe request context
        if not hasattr(frappe, "request") or frappe.request is None:
            frappe.local.request = self._mock_request

        # Set up session with CSRF token
        if not hasattr(frappe.session, "csrf_token") or not frappe.session.csrf_token:
            frappe.session.csrf_token = "test-csrf-token"

        # Set up form_dict for CSRF validation
        if not hasattr(frappe, "form_dict"):
            frappe.form_dict = {}
        frappe.form_dict["csrf_token"] = "test-csrf-token"

    def _cleanup_test_request_context(self):
        """Clean up test request context"""
        # Reset request context if we set it
        if hasattr(frappe.local, "request") and frappe.local.request == self._mock_request:
            frappe.local.request = None

    def _setup_test_mocks(self):
        """Set up mocks for problematic validations during tests"""
        self._active_mocks = []

        # Mock Mollie validation that interferes with tests
        mollie_validator_mock = patch(
            "verenigingen.verenigingen_payments.mollie.utils.data_validator.validate_mollie_customer_data",
            return_value=None,
        )
        mollie_validator_mock.start()
        self._active_mocks.append(mollie_validator_mock)

        # Mock CSRF validation in test environment
        csrf_mock = patch(
            "verenigingen.utils.security.csrf_protection.CSRFProtection.validate_request", return_value=True
        )
        csrf_mock.start()
        self._active_mocks.append(csrf_mock)

        # Mock rate limiting to bypass limits in tests
        def mock_rate_limit_validation(self, profile, operation_key, force_check=False):
            """Mock rate limit validation - always passes in tests"""
            return True

        rate_limit_mock = patch(
            "verenigingen.utils.security.api_security_framework.APISecurityFramework.validate_rate_limits",
            mock_rate_limit_validation,
        )
        rate_limit_mock.start()
        self._active_mocks.append(rate_limit_mock)

    def _cleanup_test_mocks(self):
        """Clean up test mocks"""
        for mock in getattr(self, "_active_mocks", []):
            try:
                mock.stop()
            except (RuntimeError, AttributeError):
                # Mock may already be stopped or improperly initialized
                pass
        self._active_mocks = []

    @classmethod
    def _ensure_test_environment(cls):
        """Ensure required test environment setup"""
        # Create required doctypes if they don't exist
        cls._ensure_required_doctypes()

    @classmethod
    def _ensure_required_doctypes(cls):
        """Ensure required master data exists"""
        # Ensure test Item Group exists
        if not frappe.db.exists("Item Group", "Membership"):
            item_group = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Membership",
                    "parent_item_group": "All Item Groups",
                    "is_group": 0,
                }
            )
            item_group.insert(ignore_permissions=True)

        # Ensure test Region exists.
        # The Region docname is the slugified region_name ("Test Region" -> "test-region").
        # A prior run may have left a "test-region" doc with a uniquified region_code
        # (e.g. "TR17"), so a region_code=="TR" check alone misses it and the re-insert
        # below then collides on the primary key. Fall back to the docname to reuse it.
        existing_region = frappe.db.get_value("Region", {"region_code": "TR"}, "name") or (
            "test-region" if frappe.db.exists("Region", "test-region") else None
        )
        if not existing_region:
            region = frappe.get_doc(
                {
                    "doctype": "Region",
                    "region_name": "Test Region",
                    "region_code": "TR",
                    "country": "Netherlands",
                    "is_active": 1,
                }
            )
            region.insert(ignore_permissions=True)
            # Store the actual name that was generated
            existing_region = region.name

        # Store the region name for use in tests
        cls._test_region_name = existing_region

        # Ensure test Membership Type exists
        if not frappe.db.exists("Membership Type", "Test Membership"):
            # Get a role profile for the membership type (required field)
            role_profile = frappe.db.get_value("Role Profile", {"name": "Verenigingen Staff"}, "name")
            if not role_profile:
                role_profile = frappe.db.get_value("Role Profile", {}, "name")

            membership_type = frappe.get_doc(
                {
                    "doctype": "Membership Type",
                    "membership_type_name": "Test Membership",
                    "payment_interval": "Monthly",
                    "amount": 10.00,
                    "is_active": 1,
                    "role_profile": role_profile,
                }
            )
            membership_type.insert(ignore_permissions=True)

        # Ensure test Chapter exists (unique per test session)
        cls._test_chapter_name = getattr(
            cls, "_test_chapter_name", f"Test Chapter {frappe.generate_hash(length=8)}"
        )
        if not frappe.db.exists("Chapter", cls._test_chapter_name):
            # Get the actual region name after insert
            region_name = frappe.db.get_value("Region", {"region_code": "TR"}, "name") or "test-region"
            chapter = frappe.get_doc(
                {
                    "doctype": "Chapter",
                    "name": cls._test_chapter_name,  # Set name explicitly for prompt autoname
                    "chapter_name": cls._test_chapter_name,
                    "region": region_name,
                    "is_active": 1,
                }
            )
            chapter.insert(ignore_permissions=True)

    def track_doc(self, doctype, name, depends_on=None):
        """Track a document for cleanup with optional dependency tracking.

        Args:
            doctype: The DocType name
            name: The document name
            depends_on: Optional tuple of (doctype, name) that this document depends on.
                        Dependent documents are cleaned up AFTER their dependencies.

        Idempotent: re-registering the same (doctype, name) is a no-op.
        This protects against the wrapper-and-factory both calling track_doc
        for the same doc (e.g. create_test_chapter → factory.create_test_chapter
        chain), which previously caused double-delete attempts in tearDown.
        """
        for existing in self._test_docs:
            if existing.get("doctype") == doctype and existing.get("name") == name:
                # Already tracked; preserve original registration order.
                return

        doc_info = {
            "doctype": doctype,
            "name": name,
            "registered_at": frappe.utils.now(),
            "depends_on": depends_on,
            "cleanup_status": None,  # Will be set during cleanup: 'success', 'failed', 'skipped'
        }
        self._test_docs.append(doc_info)

    def _cleanup_member_customers(self):
        """Clean up customers created for tracked members"""
        # Find all tracked members and their customers
        customers_to_delete = set()

        # Method 1: Find customers via Member.customer field
        for doc_info in self._test_docs:
            if doc_info["doctype"] == "Member":
                try:
                    if frappe.db.exists("Member", doc_info["name"]):
                        customer = frappe.db.get_value("Member", doc_info["name"], "customer")
                        if customer:
                            customers_to_delete.add(customer)
                except frappe.DoesNotExistError:
                    pass  # Member already deleted
            # Note: Membership applications are stored as Member documents with status='Pending'
            # They are handled by the "Member" branch above, no separate DocType exists

        # Method 2: Find customers via new Customer.member field (backup method)
        for doc_info in self._test_docs:
            if doc_info["doctype"] == "Member":
                try:
                    # Use direct customer.member link
                    customer = frappe.db.get_value("Customer", {"member": doc_info["name"]}, "name")
                    if customer:
                        customers_to_delete.add(customer)
                except frappe.DoesNotExistError:
                    pass  # Customer or member already deleted

        # Clean up customer dependencies and then customers
        for customer in customers_to_delete:
            try:
                if frappe.db.exists("Customer", customer):
                    # Clean up related documents first
                    self._cleanup_customer_dependencies(customer)
                    # Delete customer
                    frappe.delete_doc("Customer", customer, force=True, ignore_permissions=True)
                    print(f"✅ Cleaned up customer: {customer}")
            except (frappe.DoesNotExistError, frappe.ValidationError, frappe.LinkExistsError) as e:
                print(f"⚠️ Error cleaning up customer {customer}: {e}")

    def _cleanup_customer_dependencies(self, customer_name):
        """Clean up documents that depend on a customer"""
        # Cancel and delete Sales Invoices - optimized batch approach
        invoices = frappe.get_all(
            "Sales Invoice", filters={"customer": customer_name}, fields=["name", "docstatus"]
        )

        for invoice in invoices:
            try:
                if invoice.docstatus == 1:
                    frappe.db.set_value("Sales Invoice", invoice.name, "docstatus", 2)
                frappe.delete_doc("Sales Invoice", invoice.name, force=True, ignore_permissions=True)
            except (frappe.DoesNotExistError, frappe.ValidationError):
                continue  # Document already deleted or invalid

        # Cancel and delete Payment Entries - optimized
        payments = frappe.get_all(
            "Payment Entry",
            filters={"party": customer_name, "party_type": "Customer"},
            fields=["name", "docstatus"],
        )

        for payment in payments:
            try:
                if payment.docstatus == 1:
                    frappe.db.set_value("Payment Entry", payment.name, "docstatus", 2)
                frappe.delete_doc("Payment Entry", payment.name, force=True, ignore_permissions=True)
            except (frappe.DoesNotExistError, frappe.ValidationError):
                continue

        # Delete SEPA Mandates (linked to members, not customers directly)
        # Find member linked to this customer and delete their SEPA Mandates
        try:
            member = frappe.db.get_value("Member", {"customer": customer_name}, "name")
            if member:
                for mandate in frappe.get_all("SEPA Mandate", filters={"member": member}):
                    try:
                        frappe.delete_doc("SEPA Mandate", mandate.name, force=True, ignore_permissions=True)
                    except (frappe.DoesNotExistError, frappe.ValidationError):
                        pass  # Mandate already deleted or cannot be deleted
        except frappe.DoesNotExistError:
            pass  # Member doesn't exist

    @staticmethod
    def get_test_region_name():
        """Get (creating if necessary) the canonical test region name.

        On accumulated dev sites a Region with code "TR" already exists, but on a
        fresh CI site it does not. Returning a bare "test-region" string for a row
        that doesn't exist makes any chapter created with that region fail link
        validation. So ensure the region exists and return its real name.
        """
        existing = frappe.db.get_value("Region", {"region_code": "TR"}, "name")
        if existing:
            return existing

        region = frappe.get_doc(
            {
                "doctype": "Region",
                "region_name": "test-region",
                "region_code": "TR",
                "country": "Netherlands",
                "is_active": 1,
            }
        )
        region.insert(ignore_permissions=True)
        frappe.db.commit()
        return region.name

    @classmethod
    def setup_payment_modes(cls):
        """Set up required payment modes for testing"""
        payment_modes = [
            {"mode_of_payment": "Bank Transfer", "type": "Bank", "enabled": 1},
            {"mode_of_payment": "SEPA Direct Debit", "type": "Bank", "enabled": 1},
            {"mode_of_payment": "Cash", "type": "Cash", "enabled": 1},
        ]

        for mode_data in payment_modes:
            if not frappe.db.exists("Mode of Payment", mode_data["mode_of_payment"]):
                try:
                    mode_doc = frappe.new_doc("Mode of Payment")
                    mode_doc.update(mode_data)
                    mode_doc.save()
                    print(f"Created payment mode: {mode_data['mode_of_payment']}")
                except (frappe.DuplicateEntryError, frappe.ValidationError, frappe.PermissionError) as e:
                    print(f"Warning: Could not create payment mode {mode_data['mode_of_payment']}: {e}")

    @classmethod
    def get_test_chapter_name(cls):
        """Get the unique test chapter name for this test session"""
        return getattr(cls, "_test_chapter_name", f"Test Chapter {frappe.generate_hash(length=8)}")

    @classmethod
    def track_class_doc(cls, doctype, name):
        """Track a document for class-level cleanup"""
        cls._track_created_docs.append({"doctype": doctype, "name": name})

    @classmethod
    def _cleanup_tracked_docs(cls):
        """Clean up all tracked documents"""
        for doc_info in reversed(cls._track_created_docs):
            try:
                if frappe.db.exists(doc_info["doctype"], doc_info["name"]):
                    frappe.delete_doc(doc_info["doctype"], doc_info["name"], force=True)
            except (frappe.DoesNotExistError, frappe.ValidationError, frappe.LinkExistsError) as e:
                print(f"Error cleaning up {doc_info['doctype']} {doc_info['name']}: {e}")

    def reload_doc_with_retries(self, doc, max_retries=3):
        """
        Reload document with retry logic to handle timestamp issues

        Args:
            doc: Document to reload
            max_retries: Maximum number of retry attempts

        Returns:
            Reloaded document or None if all attempts fail
        """
        for attempt in range(max_retries):
            try:
                # Force reload from database
                fresh_doc = frappe.get_doc(doc.doctype, doc.name)
                return fresh_doc
            except frappe.DoesNotExistError as e:
                if attempt == max_retries - 1:
                    frappe.log_error(
                        f"Failed to reload {doc.doctype} {doc.name} after {max_retries} attempts: {str(e)}"
                    )
                    return None
                # Wait briefly before retry
                import time

                time.sleep(0.1)
        return None

    def save_doc_with_retry(self, doc, max_retries=3):
        """
        Save document with retry logic for timestamp mismatches

        Args:
            doc: Document to save
            max_retries: Maximum number of retry attempts

        Returns:
            True if save successful, False otherwise
        """
        for attempt in range(max_retries):
            try:
                # Debug retry attempts
                if frappe.flags.get("in_test") and attempt > 0:
                    print(f"⚠️ Retry attempt {attempt} for {doc.doctype} {doc.name}")

                # For timestamp issues, reload first
                if attempt > 0:
                    fresh_doc = self.reload_doc_with_retries(doc, max_retries=1)
                    if fresh_doc:
                        # Copy over the changes we want to save
                        for field in doc.meta.get_valid_columns():
                            if field != "modified":
                                setattr(fresh_doc, field, getattr(doc, field, None))

                        # Preserve important flags that control sync behavior
                        if hasattr(doc, "flags"):
                            fresh_doc.flags.enable_customer_sync_in_test = doc.flags.get(
                                "enable_customer_sync_in_test"
                            )
                            fresh_doc.flags.ignore_customer_sync = doc.flags.get("ignore_customer_sync")

                        doc = fresh_doc

                doc.save()
                return True

            except frappe.TimestampMismatchError:
                if attempt == max_retries - 1:
                    print(
                        f"Warning: Timestamp mismatch on {doc.doctype} {doc.name} after {max_retries} attempts"
                    )
                    return False
                continue
            except (frappe.ValidationError, frappe.PermissionError, frappe.LinkValidationError) as e:
                frappe.log_error(f"Error saving {doc.doctype} {doc.name}: {str(e)}")
                return False

        return False

    def wait_for_sync_completion(
        self, doc, sync_field="customer_sync_status", expected_status="Synced", max_wait=5
    ):
        """
        Wait for document sync to complete

        Args:
            doc: Document to monitor
            sync_field: Field to check for sync status
            expected_status: Expected sync status
            max_wait: Maximum seconds to wait

        Returns:
            True if sync completed, False if timeout
        """
        import time

        start_time = time.time()

        while time.time() - start_time < max_wait:
            # Reload document to get latest status
            fresh_doc = self.reload_doc_with_retries(doc)
            if fresh_doc and getattr(fresh_doc, sync_field, "") == expected_status:
                return True
            time.sleep(0.2)

        return False

    def create_test_donor_with_sync(self, donor_name=None, **kwargs):
        """
        Create test donor with proper sync handling

        Args:
            donor_name: Name for the donor
            **kwargs: Additional donor fields

        Returns:
            Created donor document
        """
        if not donor_name:
            donor_name = f"Test Donor {frappe.generate_hash(length=6)}"

        # Set defaults that work well in tests
        donor_data = {
            "donor_name": donor_name,
            "donor_type": "Individual",
            "donor_email": f"test{frappe.generate_hash(length=8).lower()}@example.com",
            "phone": "+31612345678",
        }
        donor_data.update(kwargs)

        donor = frappe.new_doc("Donor")
        donor.update(donor_data)

        # Enable sync during tests for this specific donor
        donor.flags.enable_customer_sync_in_test = True

        # Save with retry logic
        if self.save_doc_with_retry(donor):
            self.track_doc("Donor", donor.name)
            if donor.customer:
                self.track_doc("Customer", donor.customer)
            return donor
        else:
            raise Exception(f"Failed to create test donor: {donor_name}")

    @contextmanager
    def as_user(self, user_email):
        """Context manager to execute code as a specific user"""
        original_user = frappe.session.user
        frappe.set_user(user_email)
        try:
            yield
        finally:
            frappe.set_user(original_user)

    def assert_field_value(self, doc, field, expected_value, message=None):
        """Assert that a document field has the expected value"""
        actual_value = doc.get(field)
        if message is None:
            message = f"Expected {doc.doctype}.{field} to be {expected_value}, got {actual_value}"
        self.assertEqual(actual_value, expected_value, message)

    def assert_doc_exists(self, doctype, filters, message=None):
        """Assert that a document exists with given filters"""
        exists = frappe.db.exists(doctype, filters)
        if message is None:
            message = f"Expected {doctype} to exist with filters {filters}"
        self.assertTrue(exists, message)

    def assert_doc_not_exists(self, doctype, filters, message=None):
        """Assert that a document does not exist with given filters"""
        exists = frappe.db.exists(doctype, filters)
        if message is None:
            message = f"Expected {doctype} to not exist with filters {filters}"
        self.assertFalse(exists, message)

    def create_test_membership_type(self, **kwargs):
        """Create a test membership type with default values and unique naming"""
        # NOTE: do NOT pre-assign dues_schedule_template. MembershipType.after_insert
        # auto-creates and links a valid per-type "[Type] Membership Template"
        # (valid contribution_mode, dues_rate 15.0). The previous hardcoded fallback to
        # the literal "Monthly Membership Template" passed only because that record
        # happened to exist in a dirty local DB; on a clean CI DB it raised
        # LinkValidationError ("Could not find Default Dues Schedule Template") before
        # after_insert could run.

        # Get a role profile for members (required field)
        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")

        # Generate unique name with timestamp to prevent duplicates
        import time

        timestamp = str(int(time.time() * 1000))  # millisecond precision
        unique_suffix = frappe.generate_hash(length=4)
        unique_name = f"Test Type {timestamp[-6:]}-{unique_suffix}"

        # NOTE: only fields that actually exist on the Membership Type DocType are set.
        # "amount", "contribution_mode", "enable_income_calculator" and
        # "income_percentage_rate" were previously included but are NOT Membership Type
        # fields (verified via frappe.get_meta) — setting them was a silent no-op.
        defaults = {
            "membership_type_name": unique_name,
            "is_active": 1,
            "role_profile": role_profile,
        }
        defaults.update(kwargs)

        # Check if name already exists and make it more unique if needed
        if frappe.db.exists("Membership Type", unique_name):
            unique_name = f"Test Type {timestamp}-{unique_suffix}-{frappe.generate_hash(length=3)}"
            defaults["membership_type_name"] = unique_name

        membership_type = frappe.new_doc("Membership Type")
        for key, value in defaults.items():
            setattr(membership_type, key, value)

        membership_type.save()
        self.track_doc("Membership Type", membership_type.name)
        return membership_type

    def ensure_test_membership_type(self, type_name, **kwargs):
        """Idempotently ensure a Membership Type with a specific `name` exists.

        Several legacy tests reference Membership Types by hardcoded names
        (e.g. "Monthly Standard", "Regular"). On a fresh CI-mirror site these
        master records are never seeded, so the link fails. This creates a
        minimal valid instance (name == membership_type_name) if missing and
        returns the existing/created doc.
        """
        if frappe.db.exists("Membership Type", type_name):
            return frappe.get_doc("Membership Type", type_name)

        role_profile = frappe.db.get_value(
            "Role Profile", {"name": ["like", "%Member%"]}, "name"
        ) or frappe.db.get_value("Role Profile", {}, "name")

        defaults = {
            "membership_type_name": type_name,
            "is_active": 1,
            "role_profile": role_profile,
            "minimum_amount": 15.00,
        }
        defaults.update(kwargs)

        membership_type = frappe.new_doc("Membership Type")
        for key, value in defaults.items():
            setattr(membership_type, key, value)
        membership_type.insert(ignore_permissions=True)
        self.track_doc("Membership Type", membership_type.name)
        return membership_type

    def ensure_team_roles(self):
        """Idempotently ensure the standard seeded Team Role records exist.

        The standard Team Roles ("Team Leader", "Team Member", "Coordinator",
        "Secretary", "Treasurer", "Verenigingen Auditor") are created during
        site setup via `verenigingen.setup.create_default_team_roles`, but
        they are NOT seeded on fresh CI-mirror test sites. Tests that attach
        Team Members with these named roles must ensure they exist first.
        """
        from verenigingen.setup import create_default_team_roles

        create_default_team_roles()

    def create_test_dues_schedule(self, **kwargs):
        """Create a test dues schedule with default values"""
        # If member is provided, create instance directly (not from template)
        # since factory method doesn't support custom kwargs like dues_rate
        if "member" in kwargs:
            member_name = kwargs.pop("member")
            membership_type_name = kwargs.get("membership_type")

            # Get membership type if not provided
            if not membership_type_name:
                membership = frappe.db.get_value(
                    "Membership", {"member": member_name, "status": "Active"}, "membership_type"
                )
                if membership:
                    membership_type_name = membership
                else:
                    # Fallback to any membership type
                    membership_type_name = frappe.db.get_value("Membership Type", {}, "name")

            # Create schedule directly with all kwargs
            defaults = {
                "schedule_name": f"Test-{member_name}-{membership_type_name}",
                "member": member_name,
                "membership_type": membership_type_name,
                "dues_rate": 15.00,
                "billing_frequency": "Monthly",
                "status": "Active",
                "auto_generate": 1,
                "next_invoice_date": frappe.utils.today(),
                "is_template": 0,  # This is a member instance, not template
            }
            defaults.update(kwargs)  # This will override dues_rate if provided

            dues_schedule = frappe.new_doc("Membership Dues Schedule")
            for key, value in defaults.items():
                setattr(dues_schedule, key, value)

            dues_schedule.save()
            self.track_doc("Membership Dues Schedule", dues_schedule.name)
            return dues_schedule

        # Otherwise create a template (for backward compatibility)
        membership_type = kwargs.get("membership_type")
        if not membership_type:
            membership_type = frappe.db.get_value("Membership Type", {"name": ["like", "%Test%"]}, "name")
            if not membership_type:
                membership_type = frappe.db.get_value("Membership Type", {}, "name")

        # Create template
        defaults = {
            "is_template": 1,
            "schedule_name": f"Test-Template-{membership_type}",
            "membership_type": membership_type,
            "dues_rate": 15.00,  # Fixed: was "amount", should be "dues_rate"
            "contribution_mode": "Income-Based",
            "currency": "EUR",
            "status": "Active",
            "auto_generate": 1,
            "minimum_amount": 5.00,
            "suggested_amount": 15.00,
        }
        defaults.update(kwargs)

        # Remove deprecated fields if they were passed
        deprecated_fields = ["payment_method", "current_coverage_start", "effective_date", "test_mode"]
        for field in deprecated_fields:
            defaults.pop(field, None)

        dues_schedule = frappe.new_doc("Membership Dues Schedule")
        for key, value in defaults.items():
            setattr(dues_schedule, key, value)

        dues_schedule.save()
        self.track_doc("Membership Dues Schedule", dues_schedule.name)
        return dues_schedule

    def create_test_volunteer_expense(self, **kwargs):
        """Removed: Volunteer Expense DocType was archived in commit 1a8e5fa2.

        The underlying tabVolunteer Expense table is dropped by
        patches/v2_2/drop_volunteer_expense_archived_doctype.py. Use the
        HRMS Expense Claim helpers in verenigingen/services/volunteer/
        volunteer_expense_setup.py (get_or_create_expense_type, etc.) or
        call verenigingen.templates.pages.volunteer.expenses.submit_expense
        through the portal flow, which routes into ERPNext Expense Claim.
        """
        raise NotImplementedError(
            "Volunteer Expense DocType archived in commit 1a8e5fa2; create "
            "Expense Claim records via the HRMS flow instead. See docstring "
            "for migration pointers."
        )

    def create_test_event(self, **kwargs):
        """Create a test event with default values"""
        defaults = {
            "subject": f"Test Event {frappe.generate_hash(length=6)}",
            "event_type": "Public",
            "starts_on": frappe.utils.add_days(frappe.utils.today(), 30),
            "ends_on": frappe.utils.add_days(frappe.utils.today(), 30),
            "description": "Test event for automated testing",
        }
        defaults.update(kwargs)

        event = frappe.new_doc("Event")
        for key, value in defaults.items():
            setattr(event, key, value)

        event.save()
        self.track_doc("Event", event.name)
        return event

    def create_test_sepa_mandate(self, **kwargs):
        """
        Create a test SEPA mandate with enhanced validation and scenarios

        Args:
            scenario: Predefined scenario ("normal", "first_payment", "one_time", "suspended", "expired", "cancelled")
            bank_code: Mock bank code ("TEST", "MOCK", "DEMO")
            **kwargs: Additional field overrides

        Returns:
            SEPA Mandate document with automatic cleanup tracking
        """
        # Extract scenario-specific parameters
        scenario = kwargs.pop("scenario", "normal")
        bank_code = kwargs.pop("bank_code", "TEST")

        # Create a member first if not provided
        if "member" not in kwargs:
            member = self.create_test_member(
                first_name="SEPA",
                last_name="TestMember",
                email=f"sepa.{frappe.generate_hash(length=6)}@example.com",
            )
            kwargs["member"] = member.name

        # Ensure member has a customer (required for mandates)
        member_doc = frappe.get_doc("Member", kwargs["member"])
        if not member_doc.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = f"{member_doc.first_name} {member_doc.last_name}"
            customer.customer_type = "Individual"
            customer.member = member_doc.name  # Direct link to member
            customer.save()
            member_doc.customer = customer.name
            member_doc.save()
            self.track_doc("Customer", customer.name)

        # Scenario-based defaults with realistic test data
        scenario_defaults = {
            "normal": {
                "iban": self._get_test_iban(bank_code),
                "status": "Active",
                "mandate_type": "RCUR",
                "is_active": 1,
                "frequency": "Monthly",
                "maximum_amount": 100.00,
                "used_for_memberships": 1,
                "used_for_donations": 0,
            },
            "first_payment": {
                "iban": self._get_test_iban(bank_code),
                "status": "Active",
                "mandate_type": "CORE",  # First payment in sequence
                "is_active": 1,
                "frequency": "Monthly",
                "maximum_amount": 50.00,
                "used_for_memberships": 1,
                "first_collection_date": frappe.utils.add_days(frappe.utils.today(), 5),
            },
            "one_time": {
                "iban": self._get_test_iban(bank_code),
                "status": "Active",
                "mandate_type": "OOFF",  # One-off payment
                "is_active": 1,
                "frequency": "Variable",
                "maximum_amount": 500.00,
                "used_for_donations": 1,
                "used_for_memberships": 0,
            },
            "suspended": {
                "iban": self._get_test_iban(bank_code),
                "status": "Suspended",
                "mandate_type": "RCUR",
                "is_active": 0,  # Suspended mandate
                "frequency": "Monthly",
                "maximum_amount": 75.00,
                "used_for_memberships": 1,
            },
            "expired": {
                "iban": self._get_test_iban(bank_code),
                "status": "Expired",
                "mandate_type": "RCUR",
                "is_active": 0,
                "frequency": "Monthly",
                "maximum_amount": 25.00,
                "expiry_date": frappe.utils.add_days(frappe.utils.today(), -30),  # Expired 30 days ago
                "used_for_memberships": 1,
            },
            "cancelled": {
                "iban": self._get_test_iban(bank_code),
                "status": "Cancelled",
                "mandate_type": "RCUR",
                "is_active": 0,
                "frequency": "Monthly",
                "maximum_amount": 30.00,
                "cancelled_date": frappe.utils.add_days(frappe.utils.today(), -7),  # Cancelled 7 days ago
                "cancellation_reason": "Member request - account change",
                "used_for_memberships": 1,
            },
        }

        # Get scenario-specific defaults
        defaults = scenario_defaults.get(scenario, scenario_defaults["normal"])

        # Add common defaults for all scenarios
        common_defaults = {
            "account_holder_name": f"{member_doc.first_name} {member_doc.last_name}",
            "sign_date": frappe.utils.today(),
            "scheme": "SEPA",
        }
        defaults.update(common_defaults)

        # Apply user overrides
        defaults.update(kwargs)

        # Create mandate with proper field validation
        mandate = frappe.new_doc("SEPA Mandate")

        # Validate fields exist in DocType before setting
        valid_fields = [field.get("fieldname") for field in mandate.meta.fields]
        for key, value in defaults.items():
            if key in valid_fields:
                setattr(mandate, key, value)

        # Auto-generate mandate_id if not provided
        if "mandate_id" not in kwargs:
            # Generate unique mandate ID based on scenario
            scenario_prefix = scenario.upper()[:4]
            hash_suffix = frappe.generate_hash(length=6)
            mandate.mandate_id = f"{scenario_prefix}-{hash_suffix}"

        mandate.save()
        self.track_doc("SEPA Mandate", mandate.name)
        return mandate

    def _get_test_iban(self, bank_code="TEST"):
        """Generate a UNIQUE valid test IBAN for testing.

        generate_test_iban() without an account number always returns the same
        IBAN, so two mandates for the same member collided ("already has an
        active SEPA mandate with this IBAN"). Use a per-call counter to mint a
        unique 10-digit account number so each generated IBAN is distinct.
        """
        type(self)._iban_account_seq = getattr(type(self), "_iban_account_seq", 0) + 1
        account_number = f"{type(self)._iban_account_seq:010d}"
        try:
            # Try to use the main generator when Frappe is available
            from verenigingen.utils.validation.iban_validator import generate_test_iban

            return generate_test_iban(bank_code, account_number=account_number)
        except (ImportError, ModuleNotFoundError):
            # Fallback to standalone IBAN generation when Frappe is not available
            return self._generate_standalone_test_iban(bank_code, account_number=account_number)

    def _generate_standalone_test_iban(self, bank_code="TEST", account_number=None):
        """Generate a valid test IBAN without Frappe dependencies"""
        if bank_code not in ["TEST", "MOCK", "DEMO"]:
            bank_code = "TEST"

        if not account_number:
            # Generate a simple 10-digit account number
            account_number = "0123456789"

        # Ensure account number is 10 digits
        account_number = account_number.zfill(10)[:10]

        # Calculate correct checksum using MOD-97 algorithm
        # Create temp IBAN with 00 checksum
        temp_iban = "NL00" + bank_code + account_number

        # Move first 4 characters to end
        rearranged = temp_iban[4:] + temp_iban[:4]

        # Convert letters to numbers (A=10, B=11, ..., Z=35)
        numeric_iban = ""
        for char in rearranged:
            if char.isdigit():
                numeric_iban += char
            else:
                numeric_iban += str(ord(char) - ord("A") + 10)

        # Calculate checksum
        remainder = int(numeric_iban) % 97
        checksum = 98 - remainder

        # Construct final IBAN
        iban = f"NL{checksum:02d}{bank_code}{account_number}"
        return iban

    def create_test_sepa_mandate_with_pattern(self, pattern, starting_counter, **kwargs):
        """Create a test SEPA mandate with specific naming pattern for testing"""
        # Store current payments settings (SEPA fields moved to Payments Settings)
        payments_settings = frappe.get_single("Verenigingen Payments Settings")
        original_pattern = getattr(payments_settings, "sepa_mandate_naming_pattern", None)
        original_counter = getattr(payments_settings, "sepa_mandate_starting_counter", None)

        try:
            # Set test pattern on payments settings
            payments_settings.sepa_mandate_naming_pattern = pattern
            payments_settings.sepa_mandate_starting_counter = starting_counter
            payments_settings.save()

            # Create mandate with test pattern
            mandate = self.create_test_sepa_mandate(**kwargs)

            return mandate

        finally:
            # Restore original settings
            if original_pattern is not None:
                payments_settings.sepa_mandate_naming_pattern = original_pattern
            if original_counter is not None:
                payments_settings.sepa_mandate_starting_counter = original_counter
            payments_settings.save()

    def assert_sepa_mandate_pattern(self, mandate, expected_prefix, expected_counter=None):
        """Assert that a SEPA mandate follows expected naming pattern"""
        self.assertTrue(mandate.mandate_id, "SEPA Mandate should have mandate_id")
        self.assertTrue(
            mandate.mandate_id.startswith(expected_prefix),
            f"mandate_id '{mandate.mandate_id}' should start with '{expected_prefix}'",
        )

        if expected_counter:
            self.assertIn(
                str(expected_counter).zfill(4),
                mandate.mandate_id,
                f"mandate_id '{mandate.mandate_id}' should contain counter '{expected_counter}'",
            )

    def get_sepa_settings_backup(self):
        """Get current SEPA settings for backup/restore (from Payments Settings)"""
        payments_settings = frappe.get_single("Verenigingen Payments Settings")
        return {
            "pattern": getattr(payments_settings, "sepa_mandate_naming_pattern", None),
            "counter": getattr(payments_settings, "sepa_mandate_starting_counter", None),
        }

    def restore_sepa_settings(self, backup):
        """Restore SEPA settings from backup (to Payments Settings)"""
        payments_settings = frappe.get_single("Verenigingen Payments Settings")
        payments_settings.reload()  # Refresh to avoid timestamp issues
        if backup["pattern"] is not None:
            payments_settings.sepa_mandate_naming_pattern = backup["pattern"]
        if backup["counter"] is not None:
            payments_settings.sepa_mandate_starting_counter = backup["counter"]
        payments_settings.save()

    def create_test_membership_application(self, **kwargs):
        """Create a test membership application (as Member with pending status)

        Note: Membership applications are stored as Member documents with application_status='Pending'.
        There is no separate 'Membership Application' DocType.
        """
        defaults = {
            "first_name": "Test",
            "last_name": "Applicant",
            "email": f"applicant.{frappe.generate_hash(length=6)}@example.com",
            "status": "Pending",
            "application_status": "Pending",
            "application_date": frappe.utils.today(),
            "birth_date": "1990-01-01",
        }
        # Map membership_type to selected_membership_type if provided
        if "membership_type" in kwargs:
            kwargs["selected_membership_type"] = kwargs.pop("membership_type")
        defaults.update(kwargs)

        application = frappe.new_doc("Member")
        for key, value in defaults.items():
            if hasattr(application, key):
                setattr(application, key, value)

        application.save()
        self.track_doc("Member", application.name)
        return application

    def create_test_sales_invoice(self, **kwargs):
        """Create a test sales invoice with default values"""
        # Ensure we have a customer
        if "customer" not in kwargs:
            if "member" in kwargs:
                member = frappe.get_doc("Member", kwargs["member"])
                if not member.customer:
                    customer = frappe.new_doc("Customer")
                    customer.customer_name = f"{member.first_name} {member.last_name}"
                    customer.customer_type = "Individual"
                    customer.member = member.name  # Direct link to member
                    customer.save()
                    member.customer = customer.name
                    member.save()
                    self.track_doc("Customer", customer.name)
                kwargs["customer"] = member.customer
            else:
                # Create a test customer
                customer = frappe.new_doc("Customer")
                customer.customer_name = "Test Customer"
                customer.customer_type = "Individual"
                customer.save()
                self.track_doc("Customer", customer.name)
                kwargs["customer"] = customer.name

        defaults = {
            "posting_date": frappe.utils.today(),
            "due_date": frappe.utils.today(),
            "is_membership_invoice": 1,
            "company": frappe.defaults.get_user_default("Company")
            or frappe.get_all("Company", limit=1, pluck="name")[0],
        }
        defaults.update(kwargs)

        # ERPNext resets posting_date to today during validate unless set_posting_time
        # is enabled; without it a back/forward-dated posting_date is ignored and a
        # custom due_date can end up "before" today's posting date.
        if "posting_date" in kwargs:
            defaults.setdefault("set_posting_time", 1)

        invoice = frappe.new_doc("Sales Invoice")
        for key, value in defaults.items():
            setattr(invoice, key, value)

        # Add a default item if no items provided
        if not invoice.items:
            # Get a valid income account for the company
            company = defaults.get("company")
            income_account = frappe.get_all(
                "Account",
                filters={"account_type": "Income Account", "company": company, "is_group": 0},
                limit=1,
                pluck="name",
            )
            if not income_account:
                # Fallback - create a basic income account if none exists
                income_account = self._get_or_create_income_account(company)
            else:
                income_account = income_account[0]

            # Get or create a test item
            item_code = self._get_or_create_test_item()

            invoice.append(
                "items", {"item_code": item_code, "qty": 1, "rate": 25.0, "income_account": income_account}
            )

        invoice.save()
        self.track_doc("Sales Invoice", invoice.name)
        return invoice

    def _owned_company_and_income_account(self):
        """(company, income_account) for the company this class OWNS.

        Three modules grew their own `_get_company_with_current_fy()`, each of
        which scanned every Company on the site for one that happened to have
        both a current Fiscal Year and an account with
        `account_type = "Income Account"`. Both halves were wrong (#431):

        * **The scan borrowed.** Which company won depended on what else had run
          first in the same shard. Shard bins are packed by measured runtime, so
          editing any test file re-packs all of them -- meaning any PR could
          redden a module it never touched. It did, on trunk. #394 is the class;
          #390 is why a company another suite has drained cannot be repaired.
        * **The filter keyed on the wrong field.** ERPNext's standard chart of
          accounts leaves `account_type` empty on income leaves; they carry
          `root_type = "Income"`. Measured on a test site, `_Test Company 1` has
          five income leaves and **zero** rows matching that filter. So the
          helper only resolved when a sibling suite had already planted such a
          row. `Sales Invoice` requires neither: `validate_account_head`
          (erpnext/controllers/accounts_controller.py) asks only that the account
          belong to the invoice's company and not be a group.

        One of the three copies had already been fixed for the second half, with
        a comment naming the exact symptom -- and its two siblings kept the bug
        for as long as the fix went unsearched. Hence one helper here rather than
        three there.

        Neither of the scan's two checks needs repeating: `setUpClass` pins the
        harness-owned company on `Verenigingen Settings` (so fixtures agree with
        the company production code resolves) and runs
        `ensure_test_fiscal_year_for_all_companies()`, which guarantees an
        unrestricted Fiscal Year covering today for every company on the site.
        """
        company = self.settings_company
        if not company:
            raise RuntimeError(
                "No harness-owned Company is pinned on `Verenigingen Settings`. before_tests "
                "(verenigingen/tests/setup/__init__.py) creates one; run the suite through "
                "`bench run-tests` so that hook fires. This deliberately will NOT fall back to "
                "scanning for a company nobody here owns -- see #431 for what that costs."
            )
        return company, self._get_or_create_income_account(company)

    def _get_or_create_income_account(self, company):
        """Get or create a basic income account for testing"""
        # Check if account already exists
        existing = frappe.db.get_value("Account", {"account_name": "Test Sales Income", "company": company})
        if existing:
            return existing

        # First, find an existing Income group account to serve as parent
        # Prefer root-level accounts (no parent) but accept any valid group account
        parent_account = frappe.get_all(
            "Account",
            filters={
                "root_type": "Income",
                "company": company,
                "is_group": 1,
                "parent_account": ["is", "not set"],  # True root account
            },
            limit=1,
            pluck="name",
        )

        if not parent_account:
            # Fallback: any Income group account
            parent_account = frappe.get_all(
                "Account",
                filters={"root_type": "Income", "company": company, "is_group": 1},
                limit=1,
                pluck="name",
            )

        if not parent_account:
            # No Income accounts exist - this shouldn't happen with a properly set up company
            raise frappe.ValidationError(
                f"No Income group accounts found for company {company}. On a test site this "
                "almost never means 'ERPNext is misconfigured' -- it means another suite "
                "drained this company's chart of accounts, and per #390 a partially-drained "
                "company can NOT be repaired by rebuilding it: Company.on_update skips "
                "create_default_accounts() while any account for it survives. Find what "
                "deleted the accounts; do not add a fallback here."
            )

        # Create new income account under existing parent
        account = frappe.new_doc("Account")
        account.account_name = "Test Sales Income"
        account.company = company
        account.account_type = "Income Account"
        account.root_type = "Income"
        account.report_type = "Profit and Loss"
        account.is_group = 0
        account.parent_account = parent_account[0]

        account.save()
        self.track_doc("Account", account.name)
        return account.name

    def _get_or_create_test_item(self, suffix=None):
        """Get or create a test item for invoices.

        Pass a distinct suffix to get distinct item codes -- ERPNext rejects the
        same item appearing in multiple Sales Invoice rows unless "Allow Item to Be
        Added Multiple Times" is enabled, so callers that build multi-row invoices
        must use distinct items.
        """
        item_code = "TEST-MEMBERSHIP" if suffix is None else f"TEST-MEMBERSHIP-{suffix}"

        # Check if item already exists
        if frappe.db.exists("Item", item_code):
            return item_code

        # Create new test item
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = f"Test Membership Item {suffix}" if suffix is not None else "Test Membership Item"
        item.item_group = "Services"  # Common item group
        item.is_sales_item = 1
        item.is_service_item = 1
        item.include_item_in_manufacturing = 0
        item.is_stock_item = 0
        item.has_variants = 0
        item.variant_of = ""
        item.standard_rate = 25.0

        # Try to find item group or create one
        if not frappe.db.exists("Item Group", "Services"):
            # Create basic Services item group
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Services"
            item_group.is_group = 0
            # Find or create parent group
            if frappe.db.exists("Item Group", "All Item Groups"):
                item_group.parent_item_group = "All Item Groups"
            item_group.save()
            self.track_doc("Item Group", item_group.name)

        item.save()
        self.track_doc("Item", item.name)
        return item.name

    def ensure_erpnext_infrastructure(self):
        """Ensure ERPNext infrastructure exists for payment testing.

        Sets up:
        - Test company with abbreviation
        - Required accounts (Debtors, Cash, Income)
        - Membership Fee item

        Returns dict with company, accounts, and item names.

        Uses Administrator context for infrastructure setup since these
        are shared setup operations that need elevated permissions.
        """
        # Use as_user context manager for consistent user context management
        with self.as_user("Administrator"):
            # Get or create test company
            company_name = frappe.defaults.get_user_default("Company")
            if not company_name:
                companies = frappe.get_all("Company", limit=1, pluck="name")
                company_name = companies[0] if companies else None

            if not company_name:
                # Create test company
                company = frappe.new_doc("Company")
                company.company_name = "Test Company"
                company.abbr = "TC"
                company.default_currency = "EUR"
                company.country = "Netherlands"
                company.save()
                company_name = company.name
                self.track_doc("Company", company_name)

            # Get company abbreviation
            abbr = frappe.db.get_value("Company", company_name, "abbr") or "TC"

            # Ensure required accounts exist
            debtors_account = self._ensure_account(
                f"Debtors - {abbr}", company_name, "Receivable", is_group=0
            )
            cash_account = self._ensure_account(f"Cash - {abbr}", company_name, "Cash", is_group=0)
            income_account = self._get_or_create_income_account(company_name)

            # Get or create Membership Fee item
            item_code = self._get_or_create_membership_item()

            # Get or create cost center
            cost_center = self._ensure_cost_center(company_name, abbr)

            return {
                "company": company_name,
                "abbr": abbr,
                "debtors_account": debtors_account,
                "cash_account": cash_account,
                "income_account": income_account,
                "membership_item": item_code,
                "cost_center": cost_center,
            }

    def _ensure_account(self, account_name, company, account_type, is_group=0):
        """Ensure an account exists, create if needed."""
        # Check if account exists
        base_name = account_name.split(" - ")[0]
        existing = frappe.db.get_value("Account", {"account_name": base_name, "company": company})
        if existing:
            return existing

        # Determine root_type based on account_type
        if account_type in ("Receivable", "Cash", "Bank"):
            root_type = "Asset"
        elif account_type == "Income Account":
            root_type = "Income"
        elif account_type in ("Payable",):
            root_type = "Liability"
        elif account_type in ("Expense Account",):
            root_type = "Expense"
        else:
            root_type = "Asset"  # Default

        # Find parent account - prefer root-level group accounts (no parent)
        parent = frappe.get_all(
            "Account",
            filters={
                "company": company,
                "is_group": 1,
                "root_type": root_type,
                "parent_account": ["is", "not set"],  # True root account
            },
            limit=1,
            pluck="name",
        )

        if not parent:
            # Fallback: any group account with matching root_type
            parent = frappe.get_all(
                "Account",
                filters={"company": company, "is_group": 1, "root_type": root_type},
                limit=1,
                pluck="name",
            )

        if not parent:
            raise frappe.ValidationError(
                f"No parent account found for {account_type} (root_type={root_type}) in {company}. "
                "ERPNext may not be properly configured with a Chart of Accounts."
            )

        account = frappe.new_doc("Account")
        account.account_name = base_name
        account.company = company
        account.account_type = account_type
        account.root_type = root_type
        account.is_group = is_group
        account.parent_account = parent[0]
        account.save()
        self.track_doc("Account", account.name)
        return account.name

    def _ensure_cost_center(self, company, abbr):
        """Ensure a cost center exists for the company."""
        # First try to get existing cost center
        existing = frappe.db.get_value("Cost Center", {"company": company, "is_group": 0})
        if existing:
            return existing

        # Try to get company default cost center
        default_cc = frappe.db.get_value("Company", company, "cost_center")
        if default_cc:
            return default_cc

        # Look for any cost center that's not a group
        any_cc = frappe.get_all(
            "Cost Center", filters={"company": company}, order_by="is_group asc", limit=1, pluck="name"
        )
        if any_cc:
            return any_cc[0]

        # Create a new cost center under the main company cost center
        main_cc = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1})

        if main_cc:
            cc = frappe.new_doc("Cost Center")
            cc.cost_center_name = "Main"
            cc.company = company
            cc.parent_cost_center = main_cc
            cc.is_group = 0
            cc.save()
            self.track_doc("Cost Center", cc.name)
            return cc.name

        raise frappe.ValidationError(
            f"No cost center could be found or created for company {company}. "
            "ERPNext may not be properly configured."
        )

    def _get_or_create_membership_item(self):
        """Get or create Membership Fee item for invoicing."""
        item_code = "Membership Fee"

        if frappe.db.exists("Item", item_code):
            return item_code

        # Ensure Services item group exists
        if not frappe.db.exists("Item Group", "Services"):
            item_group = frappe.new_doc("Item Group")
            item_group.item_group_name = "Services"
            item_group.is_group = 0
            if frappe.db.exists("Item Group", "All Item Groups"):
                item_group.parent_item_group = "All Item Groups"
            item_group.save()
            self.track_doc("Item Group", item_group.name)

        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = "Membership Fee"
        item.item_group = "Services"
        item.is_sales_item = 1
        item.is_service_item = 1
        item.is_stock_item = 0
        item.standard_rate = 100.0
        item.save()
        self.track_doc("Item", item.name)
        return item.name

    def create_test_donor(self, **kwargs):
        """Create a test donor with default values"""
        defaults = {
            "donor_name": f"Test Donor {frappe.generate_hash(length=6)}",
            "donor_email": f"donor.{frappe.generate_hash(length=6)}@example.com",
            "donor_type": "Individual",
            "is_anbi_eligible": 1,
        }
        defaults.update(kwargs)

        donor = frappe.new_doc("Donor")
        for key, value in defaults.items():
            setattr(donor, key, value)

        donor.save()
        self.track_doc("Donor", donor.name)
        return donor

    def create_test_periodic_donation_agreement(self, **kwargs):
        """Create a test periodic donation agreement with default values"""
        # Create a donor first if not provided
        if "donor" not in kwargs:
            donor = self.create_test_donor()
            kwargs["donor"] = donor.name

        defaults = {
            "start_date": frappe.utils.today(),
            "annual_amount": 1200,
            "payment_frequency": "Monthly",
            "payment_method": "Bank Transfer",
            "agreement_duration_years": "5 Years (ANBI Minimum)",
            "anbi_eligible": 1,
            "status": "Draft",
        }
        defaults.update(kwargs)

        agreement = frappe.new_doc("Periodic Donation Agreement")
        for key, value in defaults.items():
            setattr(agreement, key, value)

        agreement.save()
        self.track_doc("Periodic Donation Agreement", agreement.name)
        return agreement

    def create_test_donation(self, **kwargs):
        """Create a test donation with default values"""
        # Create a donor first if not provided
        if "donor" not in kwargs:
            donor = self.create_test_donor()
            kwargs["donor"] = donor.name

        # Map legacy/alias kwargs to the real Donation fieldnames. Callers (and the
        # old factory defaults) used "date"/"payment_method", but the Donation
        # doctype's mandatory fields are "donation_date" and "mode_of_payment".
        if "date" in kwargs:
            kwargs.setdefault("donation_date", kwargs.pop("date"))
        if "payment_method" in kwargs:
            kwargs.setdefault("mode_of_payment", kwargs.pop("payment_method"))

        # mode_of_payment is a mandatory Link; ensure a usable Mode of Payment exists.
        mode_of_payment = kwargs.get("mode_of_payment", "Bank Transfer")
        if not frappe.db.exists("Mode of Payment", mode_of_payment):
            mode_of_payment = frappe.db.get_value("Mode of Payment", {}, "name") or mode_of_payment

        defaults = {
            "donation_date": frappe.utils.today(),
            "amount": 100.0,
            "mode_of_payment": mode_of_payment,
            "donor_type": "Individual",
            "currency": "EUR",
            "company": frappe.defaults.get_user_default("Company")
            or frappe.get_all("Company", limit=1, pluck="name")[0],
        }
        defaults.update(kwargs)

        donation = frappe.new_doc("Donation")
        for key, value in defaults.items():
            setattr(donation, key, value)

        donation.save()
        self.track_doc("Donation", donation.name)
        return donation

    def create_anbi_compliant_agreement(self, **kwargs):
        """Create an ANBI-compliant donation agreement (5+ years)"""
        defaults = {
            "agreement_duration_years": "5 Years (ANBI Minimum)",
            "anbi_eligible": 1,
            "annual_amount": 1200,
        }
        defaults.update(kwargs)
        return self.create_test_periodic_donation_agreement(**defaults)

    def create_non_anbi_pledge(self, **kwargs):
        """Create a non-ANBI pledge (1-4 years)"""
        defaults = {
            "agreement_duration_years": "1 Year (Pledge - No ANBI benefits)",
            "anbi_eligible": 0,
            "annual_amount": 600,
        }
        defaults.update(kwargs)
        return self.create_test_periodic_donation_agreement(**defaults)

    def create_test_payment_entry(self, **kwargs):
        """Create a test payment entry with default values"""
        # Ensure we have a party (customer or supplier)
        if "party" not in kwargs:
            if "member" in kwargs:
                member = frappe.get_doc("Member", kwargs["member"])
                if not member.customer:
                    customer = frappe.new_doc("Customer")
                    customer.customer_name = f"{member.first_name} {member.last_name}"
                    customer.customer_type = "Individual"
                    customer.member = member.name  # Direct link to member
                    customer.save()
                    member.customer = customer.name
                    member.save()
                    self.track_doc("Customer", customer.name)
                kwargs["party"] = member.customer
                kwargs["party_type"] = "Customer"
            else:
                # Create a test customer
                customer = frappe.new_doc("Customer")
                customer.customer_name = "Test Payment Customer"
                customer.customer_type = "Individual"
                customer.save()
                self.track_doc("Customer", customer.name)
                kwargs["party"] = customer.name
                kwargs["party_type"] = "Customer"

        # Get company and default accounts
        company = (
            frappe.defaults.get_user_default("Company") or frappe.get_all("Company", limit=1, pluck="name")[0]
        )

        # Get default cash account for the company
        cash_account = frappe.db.get_value(
            "Account", {"company": company, "account_type": "Cash", "is_group": 0}, "name"
        )

        if not cash_account:
            # Find or create parent cash account first
            parent_cash = frappe.db.get_value(
                "Account", {"company": company, "account_type": "Cash", "is_group": 1}, "name"
            )

            if not parent_cash:
                # Use a generic receivable account as fallback
                parent_cash = frappe.db.get_value(
                    "Account", {"company": company, "account_type": "Receivable", "is_group": 0}, "name"
                )

            if parent_cash:
                # Create a test cash account if none exists
                cash_account = frappe.get_doc(
                    {
                        "doctype": "Account",
                        "account_name": "Test Cash Account",
                        "parent_account": parent_cash,
                        "company": company,
                        "account_type": "Cash",
                        "is_group": 0,
                    }
                )
                cash_account.insert(ignore_permissions=True)
                cash_account = cash_account.name
                self.track_doc("Account", cash_account)
            else:
                # Fallback to any existing account for this company
                cash_account = frappe.db.get_value("Account", {"company": company, "is_group": 0}, "name")

        defaults = {
            "payment_type": "Receive",
            "posting_date": frappe.utils.today(),
            "paid_amount": 100.0,
            "received_amount": 100.0,
            "source_exchange_rate": 1,
            "target_exchange_rate": 1,
            "company": company,
            "mode_of_payment": "Bank Transfer",
            "paid_to": cash_account,
            "paid_to_account_currency": "EUR",
        }
        defaults.update(kwargs)

        payment = frappe.new_doc("Payment Entry")
        for key, value in defaults.items():
            setattr(payment, key, value)

        payment.save()
        self.track_doc("Payment Entry", payment.name)
        return payment

    def create_test_direct_debit_batch(self, **kwargs):
        """Create a test direct debit batch with default values and invoices"""
        defaults = {
            "batch_date": frappe.utils.today(),
            "batch_description": f"Test DD Batch {frappe.generate_hash(length=6)}",
            "batch_type": "CORE",
            "currency": "EUR",
        }
        defaults.update(kwargs)

        batch = frappe.new_doc("Direct Debit Batch")
        for key, value in defaults.items():
            setattr(batch, key, value)

        # Create test invoice to satisfy validation requirement
        if not kwargs.get("skip_invoice_creation", False):
            # Create a member, membership, and invoice for the batch
            test_member = self.create_test_member()
            test_membership = self.create_test_membership(member=test_member.name)
            test_invoice = self.create_test_sales_invoice(
                customer=test_member.customer, is_membership_invoice=1, membership=test_membership.name
            )

            # Create SEPA mandate for the member
            test_mandate = self.create_test_sepa_mandate(
                member=test_member.name, bank_code="TEST"  # Use mock bank
            )

            # Ensure invoice is unpaid for batch validation
            # Reset any payment allocations that might exist from test pollution
            frappe.db.sql(
                """
                DELETE FROM `tabPayment Entry Reference`
                WHERE reference_doctype = 'Sales Invoice' AND reference_name = %s
            """,
                (test_invoice.name,),
            )

            # Update invoice status to be unpaid
            frappe.db.set_value(
                "Sales Invoice",
                test_invoice.name,
                {"outstanding_amount": test_invoice.grand_total, "status": "Unpaid"},
            )

            # Add invoice to batch with all required fields
            batch.append(
                "invoices",
                {
                    "invoice": test_invoice.name,
                    "membership": test_membership.name,
                    "member": test_member.name,
                    "member_name": f"{test_member.first_name} {test_member.last_name}",
                    "amount": test_invoice.grand_total,
                    "currency": "EUR",
                    "iban": test_mandate.iban,
                    "mandate_reference": test_mandate.mandate_id,
                },
            )

        batch.save()
        self.track_doc("Direct Debit Batch", batch.name)
        return batch

    def create_test_chapter_role(self, **kwargs):
        """Create a test chapter role with default values"""
        defaults = {
            "role_name": f"Test Role {frappe.generate_hash(length=6)}",
            "description": "Test role for automated testing",
            "permissions_level": "Basic",  # Valid options: Basic/Financial/Admin
            "is_chair": 0,
            "is_unique": 0,
            "is_active": 1,
        }
        defaults.update(kwargs)

        role = frappe.new_doc("Chapter Role")
        for key, value in defaults.items():
            setattr(role, key, value)

        role.save()
        self.track_doc("Chapter Role", role.name)
        return role

    def create_test_volunteer_with_realistic_name(self, **kwargs):
        """Create volunteer with realistic name that could cause duplicates (for production scenario testing)"""
        common_names = [
            ("John", "Smith"),
            ("Mary", "Johnson"),
            ("James", "Williams"),
            ("Patricia", "Brown"),
            ("Robert", "Jones"),
            ("Jennifer", "Garcia"),
            ("Michael", "Davis"),
            ("Linda", "Rodriguez"),
            ("David", "Martinez"),
            ("Barbara", "Hernandez"),
            ("William", "Anderson"),
            ("Elizabeth", "Taylor"),
        ]

        # Use deterministic but realistic names based on test context
        import hashlib

        test_context = f"{self._testMethodName}_{str(kwargs)}"
        test_id = hashlib.md5(test_context.encode(), usedforsecurity=False).hexdigest()[:4]
        name_index = int(test_id, 16) % len(common_names)
        first_name, last_name = common_names[name_index]

        # Create member with realistic name if not provided
        if "member" not in kwargs:
            member = self.create_test_member(
                first_name=first_name,
                last_name=last_name,
                email=f"{first_name.lower()}.{last_name.lower()}.{test_id}@example.com",
            )
            kwargs["member"] = member.name

        # Don't override volunteer_name if explicitly provided
        if "volunteer_name" not in kwargs:
            # Get the member to use their name
            member_doc = frappe.get_doc("Member", kwargs["member"])
            kwargs["volunteer_name"] = f"{member_doc.first_name} {member_doc.last_name}".strip()

        return self.create_test_volunteer(**kwargs)

    def add_board_member_to_chapter(self, chapter, volunteer, chapter_role, **kwargs):
        """Add a board member to a chapter with proper validation"""
        defaults = {
            "volunteer": volunteer.name if hasattr(volunteer, "name") else volunteer,
            "chapter_role": chapter_role.name if hasattr(chapter_role, "name") else chapter_role,
            "from_date": frappe.utils.today(),
            "is_active": 1,
        }
        defaults.update(kwargs)

        chapter.append("board_members", defaults)
        chapter.save()

        return chapter

    def create_test_user(self, email, roles=None, password="test123"):
        """Create a test user with specified roles"""
        if frappe.db.exists("User", email):
            user = frappe.get_doc("User", email)
        else:
            user = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Test",
                    "last_name": "User",
                    "enabled": 1,
                    "new_password": password,
                    # The User DocType defaults send_welcome_email to 1, so the insert
                    # calls send_welcome_mail_to_user(), which raises OutgoingEmailError
                    # on a test site with no outgoing account and logs "Unable to send new
                    # password notification" (frappe user.py:472-490). Note the mail is
                    # gated on send_welcome_email alone -- new_password above is not what
                    # triggers it. That Error Log is pure noise, and it fails every test
                    # creating a user under VERENIGINGEN_FAIL_ON_ERROR_LOG=1. The
                    # enhanced_test_factory helper already opts out; this matches it.
                    "send_welcome_email": 0,
                }
            )
            user.insert(ignore_permissions=True)
            self.track_doc("User", email)

        if roles:
            user.roles = []
            for role in roles:
                user.append("roles", {"role": role})
            user.save(ignore_permissions=True)

        return user

    def get_test_data_path(self, filename):
        """Get path to test data file"""
        return os.path.join(os.path.dirname(__file__), "..", "fixtures", filename)

    def load_test_data(self, filename):
        """Load test data from JSON file"""
        with open(self.get_test_data_path(filename), "r") as f:
            return json.load(f)

    # Edge Case Testing Methods
    # Added based on user suggestion for better testing approach

    def clear_member_auto_schedules(self, member_name):
        """
        Clear auto-created schedules for a member to enable controlled edge case testing.

        This method implements the approach suggested for testing edge cases:
        1. Find all active schedules for the member
        2. Cancel them (removes business rule blocks)
        3. Return list of cancelled schedules for reference

        Use this when you need to create specific test scenarios with multiple
        schedules or conflicting configurations that would normally be prevented
        by business rules.

        Args:
            member_name (str): Name/ID of the member

        Returns:
            list: List of cancelled schedule details

        Example:
            member = self.create_test_member()
            membership = self.create_test_membership(member=member.name)

            # Clear auto-schedules to enable edge case testing
            cancelled = self.clear_member_auto_schedules(member.name)

            # Now create controlled test schedules
            schedule1 = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
            schedule2 = self.create_controlled_dues_schedule(member.name, "Annual", 200.0)

            # Test validation logic on the conflicting schedules
            validation_result = schedule2.validate_billing_frequency_consistency()
            self.assertFalse(validation_result["valid"])
        """

        # Find all active schedules for this member
        active_schedules = frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "billing_frequency", "dues_rate"],
        )

        cancelled_schedules = []

        for schedule_info in active_schedules:
            try:
                schedule = frappe.get_doc("Membership Dues Schedule", schedule_info.name)
                original_status = schedule.status
                schedule.status = "Cancelled"
                schedule.save()

                # Track for cleanup
                self.track_doc("Membership Dues Schedule", schedule.name)

                cancelled_schedules.append(
                    {
                        "name": schedule.name,
                        "original_status": original_status,
                        "billing_frequency": schedule_info.billing_frequency,
                        "dues_rate": schedule_info.dues_rate,
                    }
                )

            except (frappe.DoesNotExistError, frappe.ValidationError, frappe.PermissionError) as e:
                # Log but continue - some schedules might not be cancellable
                print(f"Warning: Could not cancel schedule {schedule_info.name}: {str(e)}")

        return cancelled_schedules

    def create_controlled_dues_schedule(self, member_name, billing_frequency, dues_rate, **kwargs):
        """
        Create a controlled dues schedule for edge case testing.

        This method creates a schedule with specific parameters, bypassing
        normal auto-creation logic. Use after clear_member_auto_schedules()
        to create test scenarios with multiple or conflicting schedules.

        Args:
            member_name (str): Member to create schedule for
            billing_frequency (str): Monthly, Quarterly, Annual, etc.
            dues_rate (float): Amount for the schedule
            **kwargs: Additional fields to set

        Returns:
            Document: The created schedule document

        Example:
            # Clear auto-schedules first
            self.clear_member_auto_schedules(member.name)

            # Create conflicting schedules for testing
            monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
            annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)

            # Now test validation logic
            result = annual.validate_billing_frequency_consistency()
        """

        # Get member's membership type if not provided
        if "membership_type" not in kwargs:
            membership_type = frappe.db.get_value(
                "Membership", {"member": member_name, "status": "Active"}, "membership_type"
            )

            if not membership_type:
                # Fallback to any active membership type
                membership_type = frappe.db.get_value("Membership Type", {"is_active": 1}, "name")

            if not membership_type:
                raise frappe.ValidationError(
                    "No active membership type found for controlled schedule creation"
                )

            kwargs["membership_type"] = membership_type

        # Set up default values
        test_id = frappe.generate_hash(length=6)
        defaults = {
            "schedule_name": f"ControlledTest-{billing_frequency}-{test_id}",
            "member": member_name,
            "dues_rate": dues_rate,
            "billing_frequency": billing_frequency,
            "status": "Active",
            "auto_generate": 1,
            "next_invoice_date": frappe.utils.today(),
            "is_template": 0,
        }
        defaults.update(kwargs)

        # Create the schedule
        schedule = frappe.get_doc({"doctype": "Membership Dues Schedule", **defaults})

        schedule.insert()

        # Track for cleanup
        self.track_doc("Membership Dues Schedule", schedule.name)

        return schedule

    def setup_edge_case_testing(self, member_name):
        """
        Complete setup for edge case testing with multiple schedules.

        This convenience method combines clear_member_auto_schedules() with
        helpful context information for edge case testing.

        Args:
            member_name (str): Member to set up for edge case testing

        Returns:
            dict: Context information about the setup

        Example:
            member = self.create_test_member()
            membership = self.create_test_membership(member=member.name)

            # Set up for edge case testing
            context = self.setup_edge_case_testing(member.name)

            # Create test scenarios
            monthly = self.create_controlled_dues_schedule(member.name, "Monthly", 25.0)
            annual = self.create_controlled_dues_schedule(member.name, "Annual", 250.0)

            # Test validation logic
            result = annual.validate_billing_frequency_consistency()
            self.assertFalse(result["valid"])  # Should detect conflict
        """

        # Clear auto-schedules
        cancelled_schedules = self.clear_member_auto_schedules(member_name)

        # Get member context
        member_doc = frappe.get_doc("Member", member_name)

        # Get active membership context
        active_memberships = frappe.get_all(
            "Membership",
            filters={"member": member_name, "status": "Active"},
            fields=["name", "membership_type", "status"],
        )

        return {
            "member_name": member_name,
            "member_full_name": getattr(member_doc, "full_name", "Unknown"),
            "cancelled_schedules": cancelled_schedules,
            "active_memberships": active_memberships,
            "edge_case_ready": True,
            "helper_methods": [
                "create_controlled_dues_schedule(member_name, frequency, rate)",
                "Test validation methods directly on created schedules",
                "Business rules bypassed - can create multiple schedules per member",
            ],
        }

    def create_payment_failure_test_scenario(self, failure_type="insufficient_funds", member=None, **kwargs):
        """
        Create a complete payment failure test scenario with SEPA error codes

        Args:
            failure_type: Type of payment failure to simulate
            member: Member name (creates test member if None)
            **kwargs: Additional scenario parameters

        Returns:
            dict with failure scenario, member, mandate, and test context
        """
        try:
            from verenigingen.tests.support.sepa_payment_failure_scenarios import (
                create_payment_failure_scenario,
            )
        except ImportError:
            # Fallback for when module is not available
            return self._create_basic_failure_scenario(failure_type, **kwargs)

        # Create test member if not provided
        if not member:
            test_member = self.create_test_member(
                first_name="PaymentTest",
                last_name="Member",
                email=f"payment.{frappe.generate_hash(length=6)}@example.com",
            )
            member = test_member.name

        # Create mandate for payment failures
        mandate = self.create_test_sepa_mandate(
            member=member, scenario="normal", bank_code="TEST"  # Start with valid mandate
        )

        # Generate failure scenario
        failure_scenario = create_payment_failure_scenario(failure_type, **kwargs)

        # Add test context
        test_context = {
            "member": member,
            "mandate": mandate,
            "failure_scenario": failure_scenario,
            "test_type": "payment_failure",
            "created_at": frappe.utils.now(),
        }

        return test_context

    def _create_basic_failure_scenario(self, failure_type, **kwargs):
        """Fallback method for basic failure scenarios when full module unavailable"""
        basic_scenarios = {
            "insufficient_funds": {
                "error_code": "AM04",
                "error_message": "Insufficient funds",
                "retry_eligible": True,
                "retry_days": 3,
                "severity": "medium",
            },
            "account_closed": {
                "error_code": "AC04",
                "error_message": "Account closed",
                "retry_eligible": False,
                "retry_days": 0,
                "severity": "high",
            },
            "invalid_mandate": {
                "error_code": "AM02",
                "error_message": "No valid mandate",
                "retry_eligible": False,
                "retry_days": 0,
                "severity": "high",
            },
        }

        scenario = basic_scenarios.get(failure_type, basic_scenarios["insufficient_funds"])
        scenario.update(kwargs)
        return {"failure_scenario": scenario}

    def simulate_payment_retry_sequence(self, member_name, failure_types=None):
        """
        Simulate a complete payment retry sequence for testing retry logic

        Args:
            member_name: Member to test retry sequence for
            failure_types: Sequence of failure types (defaults to realistic progression)

        Returns:
            List of retry scenarios with timing and context
        """
        try:
            from verenigingen.tests.support.sepa_payment_failure_scenarios import (
                simulate_payment_failure_sequence,
            )

            return simulate_payment_failure_sequence(member_name, failure_types)
        except ImportError:
            # Fallback to basic retry simulation
            if not failure_types:
                failure_types = ["insufficient_funds", "insufficient_funds", "account_closed"]

            sequence = []
            for i, failure_type in enumerate(failure_types):
                scenario = self._create_basic_failure_scenario(failure_type)
                scenario["sequence_number"] = i + 1
                scenario["member"] = member_name
                sequence.append(scenario)

            return sequence

    def validate_sepa_error_handling(self, error_code, expected_behavior):
        """
        Validate that SEPA error codes are handled correctly in tests

        Args:
            error_code: SEPA error code to validate (e.g., "AM04")
            expected_behavior: Expected system behavior dict

        Returns:
            bool indicating if error handling matches expectations
        """
        try:
            from verenigingen.tests.support.sepa_payment_failure_scenarios import SEPA_ERROR_CODES

            if error_code not in SEPA_ERROR_CODES:
                return False

            error_info = SEPA_ERROR_CODES[error_code]

            # Validate key behavior expectations
            checks = [
                error_info.get("retry_eligible") == expected_behavior.get("should_retry", False),
                error_info.get("customer_action_required")
                == expected_behavior.get("requires_customer_action", False),
                error_info.get("severity") == expected_behavior.get("severity", "medium"),
            ]

            return all(checks)
        except ImportError:
            # Basic validation without full module
            basic_expectations = {
                "AM04": {"should_retry": True, "requires_customer_action": False, "severity": "medium"},
                "AC04": {"should_retry": False, "requires_customer_action": True, "severity": "high"},
                "AM02": {"should_retry": False, "requires_customer_action": True, "severity": "high"},
            }

            expected = basic_expectations.get(error_code, {})
            return expected == expected_behavior

    # STREAMLINED FACTORY CONVENIENCE METHODS
    def create_test_member(self, **kwargs):
        """Create test member with automatic tracking"""
        member = self.factory.create_test_member(**kwargs)
        self.track_doc("Member", member.name)
        return member

    def create_test_volunteer(self, **kwargs):
        """Create test volunteer with automatic tracking"""
        volunteer = self.factory.create_test_volunteer(**kwargs)
        self.track_doc("Volunteer", volunteer.name)
        return volunteer

    def create_test_chapter(self, **kwargs):
        """Create test chapter with automatic tracking"""
        chapter = self.factory.create_test_chapter(**kwargs)
        self.track_doc("Chapter", chapter.name)
        return chapter

    def create_test_membership(self, **kwargs):
        """Create test membership with automatic tracking"""
        membership = self.factory.create_test_membership(**kwargs)
        self.track_doc("Membership", membership.name)
        return membership

    def create_complete_test_scenario(self, **kwargs):
        """Create complete test scenario with automatic tracking"""
        scenario = self.factory.create_complete_test_scenario(**kwargs)

        # Track all created documents
        for doc_type, docs in scenario.items():
            for doc in docs:
                self.track_doc(doc.doctype, doc.name)

        return scenario


class VereningingenUnitTestCase(VereningingenTestCase):
    """
    Test case for isolated unit tests.
    Provides utilities for mocking and isolated testing.
    """

    def setUp(self):
        """Set up unit test environment"""
        super().setUp()
        self._mocked_functions = {}

    def tearDown(self):
        """Restore mocked functions"""
        for func_path, original in self._mocked_functions.items():
            module_path, func_name = func_path.rsplit(".", 1)
            module = self._get_module(module_path)
            setattr(module, func_name, original)
        super().tearDown()

    def mock_function(self, function_path, mock_implementation):
        """Mock a function for testing"""
        module_path, func_name = function_path.rsplit(".", 1)
        module = self._get_module(module_path)

        # Store original function
        self._mocked_functions[function_path] = getattr(module, func_name)

        # Replace with mock
        setattr(module, func_name, mock_implementation)

    def _get_module(self, module_path):
        """Get module from dotted path"""
        parts = module_path.split(".")
        module = __import__(parts[0])
        for part in parts[1:]:
            module = getattr(module, part)
        return module

    @contextmanager
    def assert_validates(self):
        """Context manager to assert that code validates without errors"""
        try:
            yield
        except frappe.ValidationError as e:
            self.fail(f"Unexpected validation error: {e}")

    @contextmanager
    def assert_validation_error(self, expected_message=None):
        """Context manager to assert that code raises a validation error"""
        try:
            yield
            self.fail("Expected ValidationError but none was raised")
        except frappe.ValidationError as e:
            if expected_message:
                self.assertIn(expected_message, str(e))


class VereningingenIntegrationTestCase(VereningingenTestCase):
    """
    Test case for integration tests.
    Provides utilities for testing component interactions.
    """

    def setUp(self):
        """Set up integration test environment"""
        super().setUp()
        self._ensure_integration_environment()

    def _ensure_integration_environment(self):
        """Ensure integration test environment is ready"""
        # Ensure ERPNext required data
        self._ensure_erpnext_setup()

    def _ensure_erpnext_setup(self):
        """Ensure ERPNext is properly set up for testing"""
        # Seed ERPNext base masters (Territory tree, Warehouse Types incl.
        # "Transit", Customer Groups, Chart of Accounts, ...) before creating a
        # Company. A `run-tests --module` run skips before_tests, so on a fresh
        # site company creation otherwise fails in create_default_warehouses with
        # "Could not find Warehouse Type: Transit".
        from verenigingen.tests.setup import ensure_member_test_masters

        ensure_member_test_masters()

        # Ensure default company
        if not frappe.db.exists("Company", "Test Company"):
            company = frappe.get_doc(
                {
                    "doctype": "Company",
                    "company_name": "Test Company",
                    "default_currency": "EUR",
                    "country": "Netherlands",
                }
            )
            company.insert(ignore_permissions=True)

        # Ensure default customer group
        if not frappe.db.exists("Customer Group", "All Customer Groups"):
            customer_group = frappe.get_doc(
                {"doctype": "Customer Group", "customer_group_name": "All Customer Groups", "is_group": 1}
            )
            customer_group.insert(ignore_permissions=True)

    def execute_workflow_stage(self, workflow_name, stage_name, context):
        """Execute a specific workflow stage"""
        # This would integrate with actual workflow engine

    def assert_integration_state(self, expected_state):
        """Assert that integrations are in expected state"""
        # Check ERPNext integration state
        # Check email queue state
        # Check payment gateway state


class VereningingenWorkflowTestCase(VereningingenIntegrationTestCase):
    """
    Test case for multi-stage workflow tests.
    Provides utilities for testing complex business processes.
    """

    def setUp(self):
        """Set up workflow test environment"""
        super().setUp()
        self._workflow_context = {}
        self._workflow_stages = []
        # Initialize state manager for tracking state transitions
        from verenigingen.tests.utils.factories import TestStateManager

        self.state_manager = TestStateManager()

    def define_workflow(self, stages):
        """Define workflow stages for testing"""
        self._workflow_stages = stages

    def execute_workflow(self):
        """Execute all workflow stages"""
        for stage in self._workflow_stages:
            self._execute_stage(stage)

    def _execute_stage(self, stage):
        """Execute a single workflow stage"""
        stage.get("name")
        stage_func = stage.get("function")
        validations = stage.get("validations", [])

        # Execute stage function
        result = stage_func(self._workflow_context)

        # Update context
        if isinstance(result, dict):
            self._workflow_context.update(result)

        # Run validations
        for validation in validations:
            validation(self._workflow_context)

    def assert_workflow_state(self, field, expected_value):
        """Assert workflow context state"""
        actual_value = self._workflow_context.get(field)
        self.assertEqual(
            actual_value,
            expected_value,
            f"Expected workflow.{field} to be {expected_value}, got {actual_value}",
        )

    def get_workflow_context(self, field=None):
        """Get workflow context or specific field"""
        if field:
            return self._workflow_context.get(field)
        return self._workflow_context

    @contextmanager
    def workflow_transaction(self):
        """Execute workflow stages within a transaction"""
        # Note: Frappe doesn't allow explicit transactions in test context
        # Using try/except for error handling instead
        try:
            yield
        except Exception:
            # Intentionally catching all exceptions to ensure database rollback
            # before re-raising - this is a standard transaction cleanup pattern
            frappe.db.rollback()
            raise

    def create_persona(self, persona_name):
        """
        Create a test persona by name.

        Args:
            persona_name: Name of the persona (e.g., 'happy_path_hannah', 'payment_problem_peter')

        Returns:
            dict: The created persona data including member, membership, volunteer, etc.
        """
        from verenigingen.tests.fixtures.test_personas import TestPersonas

        # Map persona names to their creation methods
        persona_methods = {
            "happy_path_hannah": TestPersonas.create_happy_path_hannah,
            "payment_problem_peter": TestPersonas.create_payment_problem_peter,
            "sepa_sam": TestPersonas.create_sepa_sam,
            "fee_adjuster_fiona": TestPersonas.create_fee_adjuster_fiona,
            "type_changer_thomas": TestPersonas.create_type_changer_thomas,
            "volunteer_victor": TestPersonas.create_volunteer_victor,
            "terminated_tom": TestPersonas.create_terminated_tom,
            "suspended_susan": TestPersonas.create_suspended_susan,
            "new_member_nancy": TestPersonas.create_new_member_nancy,
            "board_member_bob": TestPersonas.create_board_member_bob,
            "multi_chapter_mary": TestPersonas.create_multi_chapter_mary,
        }

        if persona_name not in persona_methods:
            raise ValueError(f"Unknown persona: {persona_name}. Available: {list(persona_methods.keys())}")

        return persona_methods[persona_name]()
