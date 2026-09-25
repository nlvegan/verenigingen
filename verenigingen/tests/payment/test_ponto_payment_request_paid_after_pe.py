# Copyright (c) 2026, Verenigingen
"""PontoPaymentRequest status transitions mark a status only after the Payment
Entry it triggers actually succeeds -- #1323, the #1288 class.

Before this fix, both ``refresh_status()`` and ``update_status_from_webhook()``
saved the new status (e.g. "Executed") BEFORE calling ``create_payment_entry()``,
and ``create_payment_entry()`` wrapped its whole body in a bare try/except that
only logged and returned on failure. Any PE failure therefore left the request
permanently stuck at "Executed" with no Payment Entry and no automatic retry --
the only trace was an Error Log row.

Most of this file forces a PE failure by patching ``create_payment_entry()``
itself, to isolate the ORDERING/atomicity half of the fix from PE-creation
correctness (covered separately by test_ponto_payment_entry_creation.py and
test_ponto_doctype_coverage.py). That patch replaces the whole method, so it
cannot discriminate the SECOND half of the fix -- that ``create_payment_entry()``
itself no longer swallows its own exceptions.
TestCreatePaymentEntryPropagatesFailure below forces a REAL failure inside the
unmocked method body instead, specifically to red/green that half.

Usage:
    bench --site test_site_1 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_ponto_payment_request_paid_after_pe
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.ponto_test_data_factory import PaymentStatus, PontoTestDataFactory
from verenigingen.tests.fixtures.singleton_backup import SingletonBackup, singleton_backup
from verenigingen.tests.support.sepa_test_company import get_eur_bank_account, get_eur_test_company
from verenigingen.verenigingen_payments.doctype.ponto_payment_request.ponto_payment_request import (
    PontoPaymentRequest,
)

PAY_CLIENT_PATH = "verenigingen.verenigingen_payments.ponto.clients.payment_client.get_payment_client"
_PE_FAILURE_MESSAGE = "Simulated Payment Entry failure (#1323 test)"


def _mock_ponto_get_payment_client(status="executed"):
    """A get_payment_client() stand-in whose get_payment() reports `status`."""
    client = MagicMock()
    payment = MagicMock()
    payment.status = status
    client.get_payment.return_value = payment
    return client


class _PontoPaymentRequestFixtures:
    """Shared fixture helpers: a real EUR company/bank account (owned, shared
    master data -- see get_eur_test_company()'s own docstring) plus a Ponto
    Settings mapping and Supplier/request builders private to this module.
    """

    TEST_PONTO_ACCOUNT_ID = "ppr-1323-test-account"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = get_eur_test_company()
        cls.bank_account = get_eur_bank_account(cls.company)
        cls._settings_backup = SingletonBackup("Ponto Settings")
        cls._settings_backup.backup()
        cls._create_ponto_settings_mapping()

    @classmethod
    def tearDownClass(cls):
        cls._settings_backup.restore()
        super().tearDownClass()

    @classmethod
    def _create_ponto_settings_mapping(cls):
        """Shared, class-scoped fixture: a Ponto Settings bank-account mapping.

        Named `_create_*` so scan_order_dependence.py's COMMIT_EXEMPT applies --
        the commit below is load-bearing, not a leak: this runs once in
        setUpClass, and EnhancedTestCase's per-test rollback would otherwise
        undo it after the FIRST test method in the class, leaving every later
        method without the mapping.
        """
        settings = frappe.get_single("Ponto Settings")
        settings.sandbox_client_id = "test_client_id"
        settings.sandbox_client_secret = "test_client_secret"
        settings.sandbox_mode = 1
        settings.set("bank_account_mappings", [])
        settings.append(
            "bank_account_mappings",
            {
                "ponto_account_id": cls.TEST_PONTO_ACCOUNT_ID,
                "bank_account": cls.bank_account,
                "enabled": 1,
            },
        )
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        settings.flags.ignore_validate = False
        frappe.db.commit()

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def _create_supplier(self, name_hint):
        supplier = frappe.get_doc(
            {
                "doctype": "Supplier",
                "supplier_name": f"_Test PPR Supplier {name_hint} {frappe.generate_hash(length=6)}",
                "supplier_group": "All Supplier Groups",
                "supplier_type": "Company",
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Supplier", supplier.name)
        return supplier

    def _create_ponto_request(
        self,
        supplier,
        status="Signed",
        amount=42.0,
        ponto_account=None,
        with_reference=True,
        track_priority=0,
    ):
        """A Ponto Payment Request already past signing -- inserted directly at
        the target status/ponto_payment_id rather than driven through submit(),
        matching the existing TestPontoPaymentRequest coverage suite's own
        pattern (test_ponto_doctype_coverage.py), since before_submit() would
        otherwise hit the real Ponto API to create the payment.

        `track_priority` matters only for a test that goes on to create a REAL
        Payment Entry against `supplier`: DRAIN_PRIORITY_BY_DOCTYPE gives
        "Payment Entry" priority 6 so it drains before "Supplier" (unlisted,
        priority 0), but that tiering applies to the harness's OWN
        auto-captured inserts, not to anything tracked through
        track_doc()/track_document() without an explicit priority (those
        default to 0 regardless of doctype) -- so a Ponto Payment Request
        tracked at the default here can still drain AFTER the Payment Entry
        that references it, which (like the Supplier case) fails cleanup with
        "Could not find Party" and leaks the Payment Entry. Pass
        `track_priority=6` (matching test_ponto_doctype_coverage_extra.py's
        identical precedent) whenever the test creates a real PE.
        """
        req = frappe.new_doc("Ponto Payment Request")
        req.ponto_account = ponto_account or self.TEST_PONTO_ACCOUNT_ID
        req.amount = amount
        req.currency = "EUR"
        req.creditor_name = supplier.supplier_name
        req.creditor_iban = "NL91ABNA0417164300"
        req.remittance_info = "Test payment #1323"
        if with_reference:
            req.reference_doctype = "Supplier"
            req.reference_name = supplier.name
        req.status = status
        req.ponto_payment_id = f"ponto_pay_{frappe.generate_hash(length=10)}"
        req.insert(ignore_permissions=True)
        self.factory.track_document("Ponto Payment Request", req.name, priority=track_priority)
        return req

    def _get_or_create_test_bank(self):
        bank_name = "Ponto Test Bank (1323 guards)"
        if not frappe.db.exists("Bank", bank_name):
            frappe.get_doc({"doctype": "Bank", "bank_name": bank_name}).insert(ignore_permissions=True)
        return bank_name

    def _make_bank_account_without_company(self, name_hint):
        """A Bank Account with no Company -- guard #2's scenario. `company` is
        `mandatory_depends_on: is_company_account` in ERPNext's own schema, so
        leaving `is_company_account` unset/0 means Frappe's own mandatory
        check never requires it.

        Leaving `company` unset on the dict is NOT enough: `Document.insert()`
        calls `_set_defaults()`, which fills any missing/falsy field (a bare
        ``company = None`` counts as missing) from a *fresh* `frappe.new_doc()`
        default -- and "company" carries the session's global default company
        as a framework-wide convention, independent of `is_company_account`.
        Measured: an explicit `company = None` before `.insert()` is silently
        overwritten by that default. `frappe.db.set_value()` after insert
        bypasses `_set_defaults()`/`validate()` entirely, so it sticks -- and
        `create_payment_entry()` reads this field via a raw `frappe.db.get_value()`
        too, so this is exactly what it will see.
        """
        account = frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": f"Ponto No-Company Test {name_hint} {frappe.generate_hash(length=6)}",
                "bank": self._get_or_create_test_bank(),
                "is_company_account": 0,
            }
        ).insert(ignore_permissions=True)
        frappe.db.set_value("Bank Account", account.name, "company", None, update_modified=False)
        self.track_doc("Bank Account", account.name)
        return account.name

    def _make_bank_account_without_gl_account(self, name_hint):
        """A Bank Account whose Company resolves but which has no linked GL
        Account -- guard #3's scenario. Same `is_company_account=0` shape as
        above, but with `company` explicitly set so guard #2 does not fire
        first."""
        account = frappe.get_doc(
            {
                "doctype": "Bank Account",
                "account_name": f"Ponto No-GL Test {name_hint} {frappe.generate_hash(length=6)}",
                "bank": self._get_or_create_test_bank(),
                "is_company_account": 0,
                "company": self.company,
            }
        ).insert(ignore_permissions=True)
        self.track_doc("Bank Account", account.name)
        return account.name

    def _make_ponto_mapping(self, ponto_account_id, bank_account):
        """Enter (and return) a `singleton_backup("Ponto Settings")` context
        with `ponto_account_id` freshly mapped to `bank_account`, restored on
        the caller's `ctx.__exit__(...)`. Named `_make_*` so the
        test-quality-enforcer's permission-bypass allowlist covers the
        `ignore_permissions=True` save this performs (mirrors
        test_ponto_doctype_coverage_extra.py's `_mapped_bank_account`, a
        pre-existing helper with the identical shape)."""
        ctx = singleton_backup("Ponto Settings")
        ctx.__enter__()
        settings = frappe.get_single("Ponto Settings")
        settings.append(
            "bank_account_mappings",
            {"ponto_account_id": ponto_account_id, "bank_account": bank_account, "enabled": 1},
        )
        settings.flags.ignore_validate = True
        settings.save(ignore_permissions=True)
        settings.flags.ignore_validate = False
        return ctx


class TestRefreshStatusAtomicity(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """refresh_status(): a PE failure must not leave the status stuck "Executed"."""

    def test_pe_failure_leaves_status_unchanged_and_raises(self):
        req = self._create_ponto_request(self._create_supplier("Refresh"), status="Signed")
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with patch.object(
                PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
            ):
                with self.assertRaises(frappe.ValidationError):
                    req.refresh_status()

        reloaded = frappe.get_doc("Ponto Payment Request", req.name)
        self.assertEqual(
            reloaded.status, "Signed", "status must NOT be stuck at Executed when the PE fails"
        )
        self.assertFalse(reloaded.payment_entry)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": req.name}),
            "no Payment Entry may be left behind for a refused attempt",
        )

    def test_pe_success_updates_status_and_msgprint(self):
        """Control: the happy path still works exactly as before."""
        req = self._create_ponto_request(self._create_supplier("RefreshOK"), status="Signed")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("signed")):
            result = req.refresh_status()

        self.assertEqual(result["status"], "Signed")


class TestCreatePaymentEntryPropagatesFailure(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """create_payment_entry() itself: a real failure must propagate, not be
    logged and swallowed -- the second half of the #1323 fix, which a
    patched-out create_payment_entry() (as used above) cannot discriminate."""

    def test_missing_party_account_propagates_instead_of_being_swallowed(self):
        req = self._create_ponto_request(self._create_supplier("RealFail"), status="Signed")

        # get_party_account() returning None (no configured Payable account
        # anywhere in the resolution chain) is a REAL, unmocked failure mode
        # of create_payment_entry() itself: `pe.paid_to` stays unset and
        # Payment Entry.insert() raises for the missing mandatory field. Only
        # the account-resolution dependency is patched -- create_payment_entry()
        # runs for real.
        #
        # Payment Entry's own set_missing_values() re-derives a blank
        # party_account via a MODULE-LEVEL `from erpnext.accounts.party import
        # get_party_account` in payment_entry.py -- a second, independently
        # bound name that patching only `erpnext.accounts.party.get_party_account`
        # does not touch. Measured: with only that one patch, this test passed
        # in isolation (a cold `frappe.get_cached_value()` -- `bench run-tests`
        # clears frappe.cache() at the start of each invocation) but failed
        # after the misconfiguration-guard tests above warmed that same cache
        # with a real, resolvable default_payable_account for the shared EUR
        # test company -- Payment Entry's own fallback then silently succeeded
        # where this test expects a failure. Patching both names removes the
        # cache-state dependency entirely.
        with patch("erpnext.accounts.party.get_party_account", return_value=None), patch(
            "erpnext.accounts.doctype.payment_entry.payment_entry.get_party_account", return_value=None
        ):
            with self.assertNoErrorLog():
                with self.assertRaises(frappe.MandatoryError):
                    req.create_payment_entry()

        self.assertFalse(
            frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry"),
            "a failed attempt must not be recorded as having created a Payment Entry",
        )
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": req.name}),
            "no Payment Entry may be left behind for a refused attempt",
        )


class TestUpdateStatusFromWebhookAtomicity(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """update_status_from_webhook() has the identical shape as refresh_status()."""

    def test_pe_failure_leaves_status_unchanged_and_raises(self):
        req = self._create_ponto_request(self._create_supplier("Webhook"), status="Signed")

        with patch.object(
            PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
        ):
            with self.assertRaises(RuntimeError):
                req.update_status_from_webhook("Executed")

        reloaded = frappe.get_doc("Ponto Payment Request", req.name)
        self.assertEqual(reloaded.status, "Signed")
        self.assertFalse(reloaded.payment_entry)

    def test_webhook_entrypoint_reports_failure_and_leaves_request_retryable(self):
        """The real webhook entrypoint: handle_payment_request_closed() already
        wraps each row in its own savepoint and rolls back on ANY exception --
        this is what that isolation is FOR once create_payment_entry() stops
        swallowing its own exception. Before this fix the swallow meant that
        savepoint never saw a failure at all: the status save always "succeeded".
        """
        from verenigingen.verenigingen_payments.ponto.api.webhook_handlers import (
            handle_payment_request_closed,
        )

        req = self._create_ponto_request(self._create_supplier("WebhookEntry"), status="Signed")
        self.expectErrorLog(f"Payment webhook status update failed: {req.name}")

        payload = json.loads(
            PontoTestDataFactory.create_payment_request_closed_webhook(
                payment_id=req.ponto_payment_id,
                status=PaymentStatus.EXECUTED,
            )
        )

        with patch.object(
            PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
        ):
            result = handle_payment_request_closed(payload)

        self.assertIn(req.name, result.get("failed_requests") or [])
        self.assertNotIn(req.name, result.get("updated_requests") or [])

        reloaded_status = frappe.db.get_value("Ponto Payment Request", req.name, "status")
        self.assertEqual(
            reloaded_status, "Signed", "a redelivered webhook must be able to retry this request"
        )
        self.assertFalse(frappe.db.get_value("Ponto Payment Request", req.name, "payment_entry"))

    def test_real_success_creates_exactly_one_payment_entry(self):
        """update_status_from_webhook() through a fully valid config, with
        create_payment_entry() running for real (unmocked) -- only
        refresh_status() had this end-to-end coverage before. Both methods
        share the identical _atomic_status_transition() call, but nothing
        else had exercised update_status_from_webhook()'s own success path
        against a real, working bank account/company/Supplier."""
        req = self._create_ponto_request(
            self._create_supplier("WebhookRealPE"), status="Signed", track_priority=6
        )

        req.update_status_from_webhook("Executed")

        req.reload()
        self.assertEqual(req.status, "Executed")
        self.assertTrue(req.payment_entry, "a successful webhook update must latch payment_entry")
        self.factory.track_document("Payment Entry", req.payment_entry, priority=6)

        pe = frappe.get_doc("Payment Entry", req.payment_entry)
        self.assertEqual(pe.docstatus, 1)
        self.assertEqual(pe.party, req.reference_name)

        entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": req.name, "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(entries), 1, f"the payment was posted more than once: {entries}")


class TestRetryCreatesExactlyOnePaymentEntry(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """A retry after a transient PE failure, once the cause is gone, must
    create exactly one real Payment Entry -- not a second one alongside a
    stray first attempt from before the fix."""

    def test_retry_after_pe_failure_creates_exactly_one_payment_entry(self):
        req = self._create_ponto_request(
            self._create_supplier("Retry"), status="Signed", track_priority=6
        )
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with patch.object(
                PontoPaymentRequest, "create_payment_entry", side_effect=RuntimeError(_PE_FAILURE_MESSAGE)
            ):
                with self.assertRaises(frappe.ValidationError):
                    req.refresh_status()

            # No PE from the failed attempt, and the status must still be
            # retryable ("Signed" != "Executed" is what re-drives the PE
            # attempt on the next refresh).
            self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": req.name}))
            self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Signed")

            # Real retry: create_payment_entry() runs for real this time,
            # against the same EUR test company/bank account/Supplier this
            # module owns.
            req.reload()
            result = req.refresh_status()

        self.assertEqual(result["status"], "Executed")
        req.reload()
        self.assertEqual(req.status, "Executed")
        self.assertTrue(req.payment_entry, "a successful retry must latch payment_entry")

        pe = frappe.get_doc("Payment Entry", req.payment_entry)
        self.factory.track_document("Payment Entry", pe.name, priority=6)
        self.assertEqual(pe.docstatus, 1)

        entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": req.name, "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(entries), 1, f"the payment was posted more than once: {entries}")


class TestCreatePaymentEntryMisconfigurationGuards(_PontoPaymentRequestFixtures, EnhancedTestCase):
    """Each of create_payment_entry()'s 4 misconfiguration guards must RAISE,
    not silently return -- an independent review of the first #1323 commit
    found that a plain `return` from any of these guards exits
    refresh_status()'s/update_status_from_webhook()'s
    `with self._atomic_status_transition():` block NORMALLY, releasing the
    savepoint and committing "Executed" with no Payment Entry and no error
    trail -- exactly the bug #1323 exists to fix, just from a different one
    of the method's early-exit branches. `frappe.logger().warning()` (what
    these guards used) also writes to a rotating file handler nothing in CI
    reads.

    All 4 guards are treated as misconfiguration (must raise), not a
    legitimate "no Payment Entry expected" design, based on:
    - Guards 1-3 (no bank account mapping / no Company / no GL Account) are
      Ponto Settings / Bank Account setup gaps -- there is no scenario where
      these are supposed to stay unset.
    - Guard 4 (no reference Supplier/Employee) carries its own #1200 comment
      explicitly grouping it with the other three ("refuse rather than
      guess, matching the no-bank_account/no-company guards already above"),
      and `reference_doctype`/`reference_name` being schema-optional
      (no `reqd` flag) only proves the FIELD is optional, not that a PE is
      never expected when it is empty. The one production caller that ever
      sets a reference (`create_payment_for_supplier`, reference_doctype=
      "Supplier") has zero callers of its own anywhere in the codebase, and
      veg11's production data copy has zero Ponto Payment Request rows at
      all -- so there is no real caller or real data proving a referenceless
      request is an intentional, permanent no-PE design rather than a
      currently-unimplemented one.
    """

    def _assert_refused(self, req_name, prior_status, exception_substring=None):
        reloaded = frappe.get_doc("Ponto Payment Request", req_name)
        self.assertNotEqual(reloaded.status, "Executed", "must not commit Executed when the PE was refused")
        self.assertEqual(reloaded.status, prior_status)
        self.assertFalse(reloaded.payment_entry)
        self.assertFalse(
            frappe.db.exists("Payment Entry", {"reference_no": req_name}),
            "no Payment Entry may be left behind for a refused attempt",
        )

    def test_no_bank_account_mapping_raises(self):
        """Guard 1: ponto_account has no Ponto Settings mapping at all."""
        supplier = self._create_supplier("NoMapping")
        unmapped_account = f"ppr-1323-unmapped-{frappe.generate_hash(length=6)}"
        req = self._create_ponto_request(supplier, status="Signed", ponto_account=unmapped_account)
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with self.assertRaises(frappe.ValidationError) as cm:
                req.refresh_status()
        self.assertIn("No bank account is mapped", str(cm.exception))

        self._assert_refused(req.name, "Signed")

    def test_no_company_on_bank_account_raises(self):
        """Guard 2: the mapped Bank Account has no Company."""
        supplier = self._create_supplier("NoCompany")
        ponto_account = f"ppr-1323-nocompany-{frappe.generate_hash(length=6)}"
        bank_account = self._make_bank_account_without_company("NoCompany")

        ctx = self._make_ponto_mapping(ponto_account, bank_account)
        try:
            req = self._create_ponto_request(supplier, status="Signed", ponto_account=ponto_account)
            self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

            with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                with self.assertRaises(frappe.ValidationError) as cm:
                    req.refresh_status()
            self.assertIn("has no Company set", str(cm.exception))

            self._assert_refused(req.name, "Signed")
        finally:
            ctx.__exit__(None, None, None)

    def test_no_gl_account_on_bank_account_raises(self):
        """Guard 3: the mapped Bank Account resolves a Company but has no
        linked GL Account (Bank Account.account)."""
        supplier = self._create_supplier("NoGLAccount")
        ponto_account = f"ppr-1323-nogl-{frappe.generate_hash(length=6)}"
        bank_account = self._make_bank_account_without_gl_account("NoGLAccount")

        ctx = self._make_ponto_mapping(ponto_account, bank_account)
        try:
            req = self._create_ponto_request(supplier, status="Signed", ponto_account=ponto_account)
            self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

            with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                with self.assertRaises(frappe.ValidationError) as cm:
                    req.refresh_status()
            self.assertIn("has no linked GL Account", str(cm.exception))

            self._assert_refused(req.name, "Signed")
        finally:
            ctx.__exit__(None, None, None)

    def test_no_reference_party_raises(self):
        """Guard 4: a working bank account mapping, but the request itself has
        no reference Supplier/Employee to resolve a payable account for."""
        supplier = self._create_supplier("NoReference")
        req = self._create_ponto_request(supplier, status="Signed", with_reference=False)
        self.assertFalse(req.reference_doctype)
        self.assertFalse(req.reference_name)
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with self.assertRaises(frappe.ValidationError) as cm:
                req.refresh_status()
        self.assertIn("no reference Supplier or Employee", str(cm.exception))

        self._assert_refused(req.name, "Signed")

    def test_retry_after_fixing_missing_bank_account_mapping_creates_exactly_one_pe(self):
        """Representative branch (guard 1, the one #1323's own issue body
        names): once the misconfiguration is fixed, a retry creates exactly
        one Payment Entry -- not a second one alongside a stray first
        attempt."""
        supplier = self._create_supplier("RetryGuard1")
        unmapped_account = f"ppr-1323-retry-{frappe.generate_hash(length=6)}"
        req = self._create_ponto_request(
            supplier, status="Signed", ponto_account=unmapped_account, track_priority=6
        )
        self.expectErrorLog(f"Ponto status refresh failed: {req.name}")

        with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
            with self.assertRaises(frappe.ValidationError):
                req.refresh_status()

        self.assertFalse(frappe.db.exists("Payment Entry", {"reference_no": req.name}))
        self.assertEqual(frappe.db.get_value("Ponto Payment Request", req.name, "status"), "Signed")

        # Fix the config: map the previously-unmapped Ponto account to the
        # module's real, working bank account.
        ctx = self._make_ponto_mapping(unmapped_account, self.bank_account)
        try:
            req.reload()
            with patch(PAY_CLIENT_PATH, return_value=_mock_ponto_get_payment_client("executed")):
                result = req.refresh_status()
        finally:
            ctx.__exit__(None, None, None)

        self.assertEqual(result["status"], "Executed")
        req.reload()
        self.assertEqual(req.status, "Executed")
        self.assertTrue(req.payment_entry)
        self.factory.track_document("Payment Entry", req.payment_entry, priority=6)

        entries = frappe.get_all(
            "Payment Entry",
            filters={"reference_no": req.name, "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(len(entries), 1, f"the payment was posted more than once: {entries}")
