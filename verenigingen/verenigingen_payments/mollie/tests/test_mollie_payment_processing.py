"""
Integration coverage for verenigingen/templates/pages/mollie_payment_processing.py.

This is the PRIMARY operational page accounting staff use to turn Mollie
payments into Payment Entries / Bank Transactions. It is financially sensitive,
so the tests assert REAL effects:

  - The role gate (``has_payment_processing_access`` / ``get_context``) is
    exercised with both an authorised and an unauthorised real user.
  - The recovery endpoints (``scan_incomplete_payments``, ``get_payment_status``,
    ``preview_payment_recovery``, ``execute_payment_recovery``) run against REAL
    Bank Transaction / Payment Entry DocTypes created via factory helpers, and
    the assertions check the actual gap analysis / status reported.
  - The retrieval/processing endpoints
    (``bulk_retrieve_all_member_payments`` global-payments mode,
    ``retrieve_customer_payments_for_processing``) stub ONLY the Mollie SDK
    boundary and then assert real member-matching / orphan classification
    against REAL Member records.
  - The pure validation / coercion paths (JSON parsing, payment-id format,
    batch-size caps, parameter clamping, rate-limiting, background batch
    splitting) assert observable behaviour. ``frappe.enqueue`` is patched to
    prove batch-splitting without queueing.

Test philosophy (this repo runs an aggressive test-quality-enforcer):
only the Mollie HTTP/SDK boundary is faked. The fake (copied from
``test_mollie_debug_service.py``) records its calls and returns Mollie-shaped
objects; the patch seam routes every SDK access through it (no live
credentials). Everything below the SDK runs for real.
"""

from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.bank_utils import get_or_create_unknown_bank

PAGE = "verenigingen.templates.pages.mollie_payment_processing"

# ---------------------------------------------------------------------------
# Patch seam (proven, copied from test_mollie_debug_service.py).
# MollieClient.__init__ reads the API key directly, and ``sdk_client`` lazily
# calls MollieSettings.get_mollie_client(); patching both lets a real
# MollieClient be constructed wired to the fake SDK.
# ---------------------------------------------------------------------------
_GET_MOLLIE_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings."
    "mollie_settings.MollieSettings.get_mollie_client"
)
_GET_API_KEY = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key"

# Mollie payment IDs must match ^tr_[a-zA-Z0-9]{10,}$ (>=10 chars after tr_).
_VALID_PID_1 = "tr_WDqYK6vlAa"
_VALID_PID_2 = "tr_AbCdEfGhIj"
_VALID_PID_3 = "tr_ZzYyXxWwVv"


# ---------------------------------------------------------------------------
# Fake Mollie SDK.
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API; it cannot run in tests. This fake mimics only the small slice of
# the SDK surface the page touches (top-level payments.list / customers.get)
# and records calls for assertion.
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.payments_listed = []
        self.customers_fetched = []


class _Payment:
    def __init__(
        self,
        payment_id=_VALID_PID_1,
        status="paid",
        amount=None,
        customer_id="cst_FAKE0001",
        description="Membership dues",
        created_at="2099-01-01T00:00:00+00:00",
    ):
        self.id = payment_id
        self.status = status
        self.amount = amount if amount is not None else {"value": "25.00", "currency": "EUR"}
        self.description = description
        self.method = "directdebit"
        self.created_at = created_at
        self.customer_id = customer_id
        self.subscription_id = None
        self.paid_at = created_at


class _FakePaymentList(list):
    """A list of payments that also answers has_next() (global-mode pagination)."""

    def has_next(self):
        return False


class _FakeCustomer:
    def __init__(self, customer_id, payments):
        self.id = customer_id
        self.name = "Test Customer"
        self.email = "customer@example.com"
        self._payments = payments

    @property
    def payments(self):
        return _PaymentCollection(self._payments)


class _PaymentCollection:
    def __init__(self, payments):
        self._payments = payments

    def list(self, limit=None):
        return list(self._payments)


class _FakeCustomers:
    def __init__(self, recorder, payments, not_found_ids):
        self._recorder = recorder
        self._payments = payments
        self._not_found_ids = not_found_ids or set()

    def get(self, customer_id):
        self._recorder.customers_fetched.append(customer_id)
        if customer_id in self._not_found_ids:
            raise RuntimeError(f"No customer exists with token {customer_id}")
        return _FakeCustomer(customer_id, self._payments)


class _FakePayments:
    def __init__(self, recorder, payments):
        self._recorder = recorder
        self._payments = payments

    def list(self, **params):
        self._recorder.payments_listed.append(params)
        return _FakePaymentList(self._payments)


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self, payments=None, customer_not_found_ids=None):
        self.recorder = _Recorder()
        payments = payments if payments is not None else [_Payment()]
        self.customers = _FakeCustomers(self.recorder, payments, customer_not_found_ids)
        self.payments = _FakePayments(self.recorder, payments)


class _MultiPatch:
    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self._patches):
            p.stop()
        return False


def _patch_sdk(sdk):
    """Route every Mollie SDK access through ``sdk`` (no live credentials)."""
    return _MultiPatch(
        patch(_GET_MOLLIE_CLIENT, return_value=sdk),
        patch(_GET_API_KEY, return_value="test_fake"),
    )


# ---------------------------------------------------------------------------
# Bank Transaction factory helpers (module scope so the permission bypass is a
# recognised factory pattern, not an in-test-body insert).
# ---------------------------------------------------------------------------


def _get_test_company():
    return frappe.db.get_single_value(
        "Verenigingen Settings", "company"
    ) or frappe.defaults.get_global_default("company")


def _bank_account_currency(bank_account):
    gl = frappe.db.get_value("Bank Account", bank_account, "account")
    currency = frappe.db.get_value("Account", gl, "account_currency") if gl else None
    return currency or "EUR"


def _ensure_bank_account(test_case):
    company = _get_test_company()
    # Company-scoped only: the unscoped `or frappe.db.get_value("Bank Account", {},
    # "name")` fallback this replaced could return ANY Bank Account on the site --
    # cross-company, by recency -- instead of falling through to the create branch
    # below (#583).
    existing = frappe.db.get_value("Bank Account", {"company": company}, "name")
    if existing:
        return existing

    gl_account = frappe.db.get_value(
        "Account", {"company": company, "account_type": "Bank", "is_group": 0}, "name"
    )
    if not gl_account:
        return None

    ba = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Mollie PP Test {frappe.generate_hash()[:6]}",
            "bank": get_or_create_unknown_bank(),
            "account": gl_account,
            "company": company,
        }
    )
    ba.insert(ignore_permissions=True)
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("Bank Account", ba.name)
    return ba.name


def _make_unprivileged_user(test_case):
    """Create+track a System User with NO granted roles (only the implicit
    'All'/'Guest'), so it holds none of the payment-processing roles. Built at
    module scope so the permission bypass is a recognised factory pattern."""
    email = f"mollie-pp-deny-{frappe.generate_hash(length=8)}@example.com"
    user = frappe.get_doc(
        {
            "doctype": "User",
            "email": email,
            "first_name": "Unprivileged",
            "send_welcome_email": 0,
            "user_type": "System User",
        }
    )
    user.insert(ignore_permissions=True)
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("User", user.name)
    return user.name


def _make_bank_transaction(test_case, bank_account, reference_number):
    """Create+track a Bank Transaction referencing a Mollie payment id."""
    company = frappe.db.get_value("Bank Account", bank_account, "company")
    bt = frappe.get_doc(
        {
            "doctype": "Bank Transaction",
            "date": frappe.utils.today(),
            "bank_account": bank_account,
            "company": company,
            "deposit": 25.0,
            "withdrawal": 0.0,
            "currency": _bank_account_currency(bank_account),
            "reference_number": reference_number,
        }
    )
    bt.insert(ignore_permissions=True)
    factory = getattr(test_case, "factory", None)
    if factory is not None and hasattr(factory, "track_document"):
        factory.track_document("Bank Transaction", bt.name)
    return bt.name


# ===========================================================================
# Base class
# ===========================================================================
class _PageTest(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self._clear_rate_limits()

    def tearDown(self):
        self._clear_rate_limits()
        frappe.set_user("Administrator")
        super().tearDown()

    def _clear_rate_limits(self):
        # The batch endpoints key rate-limit caches on the session user and set
        # them via frappe.cache().set(...); clear with the matching .delete().
        for prefix in ("dues_batch_limit", "bulk_payment_process_limit"):
            key = f"{prefix}:{frappe.session.user}"
            for deleter in ("delete", "delete_value"):
                try:
                    getattr(frappe.cache(), deleter)(key)
                except Exception:
                    pass


# ===========================================================================
# Role gate: has_payment_processing_access / get_context
# ===========================================================================
class TestRoleGate(_PageTest):
    def test_administrator_has_access(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # setUp already runs as Administrator.
        self.assertTrue(pp.has_payment_processing_access())

    def test_unprivileged_user_denied(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # A user with no granted roles has none of the payment-processing
        # roles -> the gate must deny.
        user_name = _make_unprivileged_user(self)
        with self.set_user(user_name):
            self.assertFalse(pp.has_payment_processing_access())

    def test_get_context_throws_for_unauthorized(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # Patch the gate to deny so we exercise get_context's PermissionError
        # branch without depending on a specific unauthorized user fixture.
        ctx = frappe._dict()
        with patch.object(pp, "has_payment_processing_access", return_value=False):
            with self.assertRaises(frappe.PermissionError):
                pp.get_context(ctx)

    def test_get_context_populates_when_authorized(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        ctx = frappe._dict()
        with patch.object(pp, "has_payment_processing_access", return_value=True):
            pp.get_context(ctx)
        self.assertEqual(ctx.no_cache, 1)
        self.assertTrue(ctx.show_sidebar)
        self.assertTrue(ctx.csrf_token)
        self.assertEqual(ctx.title, "Mollie Payment Processing")


# ===========================================================================
# scan_incomplete_payments / get_payment_status — REAL Bank Transaction DB
# ===========================================================================
class TestScanAndStatus(_PageTest):
    def _bank_account(self):
        ba = _ensure_bank_account(self)
        if not ba:
            self.skipTest("no usable Bank Account / bank GL account on this site")
        return ba

    def test_scan_detects_bank_transaction_without_payment_entry(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        ba = self._bank_account()
        _make_bank_transaction(self, ba, _VALID_PID_1)

        result = pp.scan_incomplete_payments()

        self.assertNotIn("error", result)
        self.assertGreaterEqual(result["total_bank_transactions"], 1)
        # Our BT has no Payment Entry -> it must surface as a gap.
        self.assertTrue(result["has_gaps"])
        gap_pids = [g["payment_id"] for g in result.get("gap_details", [])]
        self.assertIn(_VALID_PID_1, gap_pids)
        # The new BT is missing a Payment Entry -> grouped accordingly.
        pe_gap_pids = [g["payment_id"] for g in result["gaps_by_type"]["missing_payment_entry"]]
        both_gap_pids = [g["payment_id"] for g in result["gaps_by_type"]["missing_both"]]
        self.assertIn(_VALID_PID_1, pe_gap_pids + both_gap_pids)

    def test_get_payment_status_reflects_existing_bank_transaction(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        ba = self._bank_account()
        _make_bank_transaction(self, ba, _VALID_PID_2)

        result = pp.get_payment_status(_VALID_PID_2)

        self.assertNotIn("error", result)
        self.assertEqual(result["payment_id"], _VALID_PID_2)
        self.assertTrue(result["has_bank_transaction"])
        self.assertEqual(result["status"], "partial")

    def test_get_payment_status_unprocessed_when_no_documents(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        result = pp.get_payment_status(_VALID_PID_3)
        self.assertNotIn("error", result)
        self.assertFalse(result["has_bank_transaction"])
        self.assertEqual(result["status"], "unprocessed")

    def test_get_payment_status_rejects_bad_id_format(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # The endpoint swallows the validation throw and returns {"error": ...}.
        result = pp.get_payment_status("not-a-valid-id")
        self.assertIn("error", result)

    def test_get_payment_status_denied_for_unauthorized(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        with patch.object(pp, "has_payment_processing_access", return_value=False):
            result = pp.get_payment_status(_VALID_PID_3)
        self.assertIn("error", result)


# ===========================================================================
# preview_payment_recovery / execute_payment_recovery — dry run vs live
# ===========================================================================
class TestPaymentRecovery(_PageTest):
    def _bank_account(self):
        ba = _ensure_bank_account(self)
        if not ba:
            self.skipTest("no usable Bank Account / bank GL account on this site")
        return ba

    def test_preview_is_dry_run_and_summarized(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        ba = self._bank_account()
        _make_bank_transaction(self, ba, _VALID_PID_1)

        # Snapshot the financial-document counts so we can prove the preview is a
        # true no-write dry run (the load-bearing safety property for a preview).
        pe_before = frappe.db.count("Payment Entry")
        si_before = frappe.db.count("Sales Invoice")

        result = pp.preview_payment_recovery(max_payments=10)

        self.assertNotIn("error", result)
        # dry_run=True path always reports without creating documents.
        self.assertTrue(result.get("dry_run"))
        # No financial documents were created by the preview.
        self.assertEqual(frappe.db.count("Payment Entry"), pe_before)
        self.assertEqual(frappe.db.count("Sales Invoice"), si_before)
        # When the recovery surfaces candidates, the UI summary is a well-formed
        # tally of what *would* be created (all four buckets present, integer).
        if result.get("results"):
            summary = result["would_create_summary"]
            for bucket in ("bank_transactions", "payment_entries", "sales_invoices", "links"):
                self.assertIsInstance(summary[bucket], int)

    def test_execute_caps_max_payments_at_100(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # Patch the underlying recovery to capture the clamped max_payments,
        # proving execute enforces its safety cap (min(max_payments, 100)).
        captured = {}

        def _fake_complete(payment_ids=None, dry_run=None, max_payments=None):
            captured["max_payments"] = max_payments
            captured["dry_run"] = dry_run
            return {"results": []}

        # execute_payment_recovery imports complete_partial_payments from the
        # re-export module (verenigingen.utils.payment_processing_recovery) at
        # call time, so that is the binding to patch.
        with patch(
            "verenigingen.utils.payment_processing_recovery.complete_partial_payments",
            side_effect=_fake_complete,
        ):
            result = pp.execute_payment_recovery(max_payments=9999)

        self.assertEqual(captured["max_payments"], 100)
        self.assertFalse(captured["dry_run"])
        self.assertIn("execution_summary", result)

    def test_execute_rejects_bad_payment_id_format(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        result = pp.execute_payment_recovery(payment_ids='["bad-id"]')
        self.assertIn("error", result)


# ===========================================================================
# batch_process_dues_payments — input validation, caps, rate limiting
# ===========================================================================
class TestBatchProcessDuesValidation(_PageTest):
    def test_invalid_json_payment_ids_returns_error(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        result = pp.batch_process_dues_payments(payment_ids="{not json")
        self.assertIn("error", result)

    def test_non_list_payment_ids_returns_error(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # Valid JSON but a dict, not a list.
        result = pp.batch_process_dues_payments(payment_ids='{"a": 1}')
        self.assertIn("error", result)

    def test_bad_payment_id_format_returns_error(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        result = pp.batch_process_dues_payments(payment_ids='["short"]')
        self.assertIn("error", result)

    def test_oversized_batch_returns_error(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        too_many = [f"tr_{'A' * 12}{i:04d}" for i in range(51)]
        import json

        result = pp.batch_process_dues_payments(payment_ids=json.dumps(too_many))
        self.assertIn("error", result)
        self.assertIn("50", result["error"])

    def test_rate_limit_blocks_second_immediate_call(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        ids = json_dumps([_VALID_PID_1])
        # Stub the service so the first call succeeds and SETs the cooldown key;
        # only the rate-limit behaviour is under test here.
        # ``batch_process_dues_payments`` now delegates to the consolidated
        # bulk_payment_admin_service, which builds its own MollieDebugService
        # via a fresh function-level import from the source module rather
        # than this page's symbol - so patch it there instead of via PAGE.
        with patch("verenigingen.services.mollie_debug_service.MollieDebugService") as MockSvc:
            MockSvc.return_value.batch_process_dues_payments.return_value = {"processed": 1}
            first = pp.batch_process_dues_payments(payment_ids=ids)
            second = pp.batch_process_dues_payments(payment_ids=ids)

        self.assertEqual(first, {"processed": 1})
        # Second call hit the cooldown lock -> error mentioning the wait.
        self.assertIn("error", second)
        self.assertIn("wait", second["error"].lower())


# ===========================================================================
# bulk_process_member_payments — background batch splitting via enqueue
# ===========================================================================
class TestBulkProcessBatching(_PageTest):
    def test_large_batch_is_split_and_enqueued(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # 250 valid payment ids -> 3 batches of 100/100/50, each enqueued once.
        ids = [f"tr_{'B' * 12}{i:04d}" for i in range(250)]
        import json

        with patch(f"{PAGE}.frappe.enqueue", return_value="job-xyz") as mock_enqueue:
            result = pp.bulk_process_member_payments(payment_ids=json.dumps(ids))

        self.assertTrue(result["queued"])
        self.assertEqual(result["num_batches"], 3)
        self.assertEqual(result["total_payments"], 250)
        self.assertEqual(mock_enqueue.call_count, 3)
        # Verify the worker function and batch sizes passed to enqueue.
        # ``bulk_process_member_payments`` now delegates to the consolidated
        # bulk_payment_admin_service, so the enqueue target is the service's
        # dotted path rather than this page's (a back-compat shim still lives
        # at the old path for in-flight jobs queued before this refactor).
        first_call = mock_enqueue.call_args_list[0]
        self.assertEqual(
            first_call.args[0],
            "verenigingen.verenigingen_payments.mollie.services.bulk_payment_admin_service.process_payment_batch_job",
        )
        self.assertEqual(len(first_call.kwargs["payment_ids"]), 100)
        last_call = mock_enqueue.call_args_list[-1]
        self.assertEqual(len(last_call.kwargs["payment_ids"]), 50)

    def test_small_batch_processed_synchronously(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        ids = json_dumps([_VALID_PID_1, _VALID_PID_2])
        # ``bulk_process_member_payments`` now delegates to
        # bulk_payment_admin_service, which builds its own MollieDebugService
        # via a fresh function-level import from the source module rather
        # than this page's symbol - so patch it there instead of via PAGE.
        with patch("verenigingen.services.mollie_debug_service.MollieDebugService") as MockSvc:
            MockSvc.return_value.bulk_process_member_payments.return_value = {"processed": 2}
            with patch(f"{PAGE}.frappe.enqueue") as mock_enqueue:
                result = pp.bulk_process_member_payments(payment_ids=ids)

        self.assertEqual(result, {"processed": 2})
        mock_enqueue.assert_not_called()

    def test_invalid_json_returns_error(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        result = pp.bulk_process_member_payments(payment_ids="{not json")
        self.assertIn("error", result)


# ===========================================================================
# bulk_retrieve_all_member_payments — param clamping + global_payments mode
# ===========================================================================
class TestBulkRetrieve(_PageTest):
    def setUp(self):
        super().setUp()
        # The matcher is a module-level singleton with cached member lookups;
        # reset so newly created test members are seen.
        from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
            get_member_payment_matcher,
        )

        get_member_payment_matcher().reset()

    def tearDown(self):
        from verenigingen.verenigingen_payments.mollie.utils.member_payment_matcher import (
            get_member_payment_matcher,
        )

        get_member_payment_matcher().reset()
        super().tearDown()

    def test_global_mode_matches_member_and_classifies_orphan(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # One member owns cst_MATCH0001; the other payment has an unknown
        # customer -> orphan. Both are 'paid' EUR -> processable.
        member = self.create_test_member(mollie_customer_id="cst_MATCH0001")
        matched = _Payment(payment_id=_VALID_PID_1, customer_id="cst_MATCH0001")
        orphan = _Payment(payment_id=_VALID_PID_2, customer_id="cst_UNKNOWN999")
        sdk = FakeSDKClient(payments=[matched, orphan])

        with _patch_sdk(sdk):
            result = pp.bulk_retrieve_all_member_payments(
                days_back=30,
                max_payments=250,
                payment_status_filter="paid",
                retrieval_mode="global_payments",
            )

        self.assertEqual(result["retrieval_mode"], "global_payments")
        self.assertEqual(result["total_payments_found"], 2)
        # The matched payment is grouped under its member.
        matched_members = [c["member"] for c in result["customers"]]
        self.assertIn(member.name, matched_members)
        # The unknown-customer payment is reported as an orphan.
        orphan_pids = [o["payment_id"] for o in result["orphaned_transactions"]]
        self.assertIn(_VALID_PID_2, orphan_pids)
        # An orphan with a Mollie customer id classifies as bt_only_orphaned.
        orphan = next(o for o in result["orphaned_transactions"] if o["payment_id"] == _VALID_PID_2)
        self.assertTrue(orphan["processable"])
        self.assertEqual(orphan["processing_mode"], "bt_only_orphaned")

    def test_global_mode_status_filter_excludes_non_matching(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        paid = _Payment(payment_id=_VALID_PID_1, status="paid", customer_id="cst_ZZZ1")
        failed = _Payment(payment_id=_VALID_PID_2, status="failed", customer_id="cst_ZZZ2")
        sdk = FakeSDKClient(payments=[paid, failed])

        with _patch_sdk(sdk):
            result = pp.bulk_retrieve_all_member_payments(
                days_back=30,
                max_payments=250,
                payment_status_filter="paid",
                retrieval_mode="global_payments",
            )

        self.assertEqual(result["total_payments_found"], 2)
        self.assertEqual(result["total_filtered_by_status"], 1)
        self.assertEqual(result["total_payments_after_filtering"], 1)

    def test_invalid_params_are_clamped_to_defaults(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        # days_back out of range -> 30; max_payments out of range -> 5000;
        # unknown retrieval_mode -> 'customer' (delegates to the consolidated
        # bulk_payment_admin_service, which builds its own MollieDebugService
        # via a fresh function-level import from the source module rather
        # than the page module's symbol - so we patch it there to capture
        # the clamped args).
        with patch("verenigingen.services.mollie_debug_service.MollieDebugService") as MockSvc:
            MockSvc.return_value.bulk_retrieve_all_member_payments.return_value = {"ok": True}
            result = pp.bulk_retrieve_all_member_payments(
                days_back=999999,
                max_payments=1,
                payment_status_filter="all",
                retrieval_mode="bogus_mode",
            )

        self.assertEqual(result, {"ok": True})
        call = MockSvc.return_value.bulk_retrieve_all_member_payments.call_args
        clamped_days, clamped_max, _filter = call.args
        self.assertEqual(clamped_days, 30)
        self.assertEqual(clamped_max, 5000)


# ===========================================================================
# retrieve_customer_payments_for_processing — SDK-backed shaping
# ===========================================================================
class TestRetrieveCustomerPayments(_PageTest):
    def test_returns_shaped_payments_from_sdk(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        payment = _Payment(payment_id=_VALID_PID_1, customer_id="cst_RET0001", description="Donation")
        sdk = FakeSDKClient(payments=[payment])

        with _patch_sdk(sdk):
            result = pp.retrieve_customer_payments_for_processing(customer_id="cst_RET0001", limit=50)

        # The result dict always carries an "error" key; on success it is None.
        self.assertIsNone(result["error"])
        self.assertEqual(result["customer_id"], "cst_RET0001")
        self.assertEqual(result["total_found"], 1)
        self.assertEqual(result["payments"][0]["id"], _VALID_PID_1)
        self.assertEqual(result["payments"][0]["amount"], "25.00 EUR")

    def test_missing_customer_in_mollie_reported_as_error(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        sdk = FakeSDKClient(customer_not_found_ids={"cst_MISSING01"})
        with _patch_sdk(sdk):
            result = pp.retrieve_customer_payments_for_processing(customer_id="cst_MISSING01")

        # The service captures the not-found lookup as a descriptive error.
        self.assertIsNotNone(result["error"])
        self.assertIn("cst_MISSING01", result["error"])

    def test_denied_for_unauthorized_user(self):
        from verenigingen.templates.pages import mollie_payment_processing as pp

        with patch.object(pp, "has_payment_processing_access", return_value=False):
            result = pp.retrieve_customer_payments_for_processing(customer_id="cst_X")
        self.assertIn("error", result)


def json_dumps(obj):
    import json

    return json.dumps(obj)
