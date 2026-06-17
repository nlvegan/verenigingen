"""
Integration coverage for
``verenigingen/templates/pages/mollie_bulk_payment_creation.py``.

This admin page turns a CSV upload into Mollie subscriptions charged against
members' SEPA mandates. It is financially sensitive and was 0% covered. The
entry points are:

  - ``get_context``           - page render + role gate
  - ``has_admin_access``      - role allow/deny logic
  - ``sanitize_csv_field``    - CSV-injection escaping (pure)
  - ``validate_csv_members``  - parse CSV, validate each member + mandate
                                (NO payment creation, reads REAL Member/Mandate)
  - ``create_bulk_payments``  - create Mollie subscriptions in bulk
  - ``get_webhook_url``       - configured webhook URL

Test philosophy (this repo runs an aggressive test-quality-enforcer):
  - ONLY the Mollie SDK boundary is faked. ``FakeSDKClient`` records the calls
    made against it and returns realistic Mollie-shaped objects. No network is
    touched and no live Mollie credentials are needed - the same proven seam as
    ``tests/test_mollie_debug_service.py``: patch
    ``MollieSettings.get_mollie_client`` (so ``sdk_client`` is the fake) and
    ``MollieClient._get_api_key``.
  - The DocType side runs for real: ``validate_csv_members`` looks up REAL
    Member records (with/without a stored ``mollie_mandate_id``) and the
    assertions check the actual classification (valid vs warning vs error) and
    the per-member payload the create path forwards to the SDK.

Hence the integration name (no ``_unit`` suffix).
"""

import json
from unittest.mock import patch

import frappe

# ---------------------------------------------------------------------------
# Module under test.
# ---------------------------------------------------------------------------
import verenigingen.templates.pages.mollie_bulk_payment_creation as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

# ---------------------------------------------------------------------------
# Patch seam (proven). MollieClient.__init__ reads the API key directly, and
# ``sdk_client`` lazily calls MollieSettings.get_mollie_client(); patching both
# lets a real MollieClient be constructed wired to the fake SDK. The page's own
# duplicate-check path calls ``Mollie Settings.get_mollie_client()`` directly,
# which the first patch also covers.
# ---------------------------------------------------------------------------
_GET_MOLLIE_CLIENT = (
    "verenigingen.verenigingen_payments.doctype.mollie_settings."
    "mollie_settings.MollieSettings.get_mollie_client"
)
_GET_API_KEY = "verenigingen.verenigingen_payments.mollie.core.client.MollieClient._get_api_key"

_VALID_IBAN = "NL91ABNA0417164300"


# ---------------------------------------------------------------------------
# Fake Mollie SDK.
#
# Mock justified: the Mollie SDK is a third-party HTTP client for an external
# payment API; it cannot run in tests. This fake mimics only the small slice of
# the SDK surface the page touches (customers.get -> mandates/subscriptions)
# and records create/list calls for assertion.
# ---------------------------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.subscriptions_created = []  # list of (customer_id, data)
        self.customers_fetched = []
        self.subscription_lists = []


class _Sub:
    def __init__(self, sub_id="sub_FAKE0001", status="active", amount=None, start_date=None):
        self.id = sub_id
        self.status = status
        self.amount = amount if amount is not None else {"value": "25.00", "currency": "EUR"}
        self.interval = "1 month"
        self.description = "Fake subscription"
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.startDate = start_date
        self.start_date = start_date
        self.next_payment_date = None


class _Mandate:
    def __init__(self, mandate_id="mdt_FAKE0001", status="valid", method="directdebit"):
        self.id = mandate_id
        self.status = status
        self.method = method
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.signature_date = "2024-12-31"
        self.mandate_reference = "REF-001"
        self.details = {
            "consumerName": "Jan Tester",
            "consumerAccount": _VALID_IBAN,
            "consumerBic": "ABNANL2A",
        }


class _SubCollection:
    def __init__(self, recorder, customer_id, subs, raise_on_create=False):
        self._recorder = recorder
        self._customer_id = customer_id
        self._subs = subs
        self._raise_on_create = raise_on_create

    def list(self, limit=None):
        self._recorder.subscription_lists.append(self._customer_id)
        return list(self._subs)

    def get(self, subscription_id):
        for s in self._subs:
            if s.id == subscription_id:
                return s
        return _Sub(sub_id=subscription_id)

    def create(self, data=None):
        self._recorder.subscriptions_created.append((self._customer_id, data))
        if self._raise_on_create:
            # Simulate the Mollie SDK rejecting the create (e.g. revoked mandate,
            # API 422). The real MollieClient.create_subscription re-raises and the
            # service turns it into an error response.
            raise RuntimeError("Mollie API rejected subscription create")
        return _Sub(sub_id="sub_CREATED1", status="active", start_date=(data or {}).get("startDate"))


class _MandateCollection:
    def __init__(self, mandates):
        self._mandates = mandates

    def list(self):
        return list(self._mandates)

    def get(self, mandate_id):
        for m in self._mandates:
            if m.id == mandate_id:
                return m
        return _Mandate(mandate_id=mandate_id)


class _FakeCustomer:
    def __init__(self, recorder, customer_id, subs, mandates, raise_on_create=False):
        self.id = customer_id
        self.name = "Test Customer"
        self.email = "customer@example.com"
        self.created_at = "2025-01-01T00:00:00+00:00"
        self.mode = "test"
        self.subscriptions = _SubCollection(recorder, customer_id, subs, raise_on_create=raise_on_create)
        self.mandates = _MandateCollection(mandates)


class _FakeCustomers:
    def __init__(self, recorder, subs, mandates, not_found_ids, raise_on_create=False):
        self._recorder = recorder
        self._subs = subs
        self._mandates = mandates
        self._not_found_ids = not_found_ids or set()
        self._raise_on_create = raise_on_create

    def get(self, customer_id):
        self._recorder.customers_fetched.append(customer_id)
        if customer_id in self._not_found_ids:
            raise RuntimeError(f"No customer exists with token {customer_id}")
        return _FakeCustomer(
            self._recorder, customer_id, self._subs, self._mandates, raise_on_create=self._raise_on_create
        )


class _FakePayments:
    def list(self, **params):
        return []


class FakeSDKClient:
    """Stand-in for ``mollie.api.client.Client``."""

    def __init__(self, subs=None, mandates=None, customer_not_found_ids=None, raise_on_create=False):
        self.recorder = _Recorder()
        subs = subs if subs is not None else []
        mandates = mandates if mandates is not None else [_Mandate()]
        self.customers = _FakeCustomers(
            self.recorder, subs, mandates, customer_not_found_ids, raise_on_create=raise_on_create
        )
        self.payments = _FakePayments()


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
# Helpers for building future-dated charge dates relative to "now" so the page's
# "must be in the future / within 1 year" checks pass deterministically.
# ---------------------------------------------------------------------------
def _future_date(days=30):
    return frappe.utils.add_days(frappe.utils.nowdate(), days)


class _BulkPageTest(EnhancedTestCase):
    """Common base: administrator user."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")

    def tearDown(self):
        frappe.set_user("Administrator")
        super().tearDown()

    # --- factory helpers (ignore_permissions only lives in helpers) ----------
    def _make_member(self, customer_id, mandate_id=None, status="Active"):
        kwargs = {"mollie_customer_id": customer_id, "status": status}
        if mandate_id is not None:
            kwargs["mollie_mandate_id"] = mandate_id
        return self.create_test_member(**kwargs)

    def _csv(self, *customer_ids, header="customer_id"):
        lines = [header] + list(customer_ids)
        return "\n".join(lines) + "\n"

    def _make_unprivileged_user(self):
        """Create + track a low-privilege Website User (none of the admin roles)."""
        email = f"cdeny-{frappe.generate_hash(length=8)}@example.com"
        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": "CDeny",
                "send_welcome_email": 0,
                "user_type": "Website User",
            }
        )
        user.insert(ignore_permissions=True)
        self.track_doc("User", user.name)
        return user.name


# ===========================================================================
# sanitize_csv_field - CSV-injection escaping (pure)
# ===========================================================================
class TestSanitizeCsvField(EnhancedTestCase):
    def test_escapes_each_dangerous_leading_char(self):
        for ch in ("=", "+", "-", "@", "\t", "\r"):
            payload = f"{ch}cmd|calc"
            escaped = page.sanitize_csv_field(payload)
            self.assertTrue(
                escaped.startswith("'"),
                f"field starting with {ch!r} must be prefixed with an apostrophe",
            )
            self.assertEqual(escaped, "'" + payload)

    def test_safe_value_is_unchanged(self):
        self.assertEqual(page.sanitize_csv_field("cst_12345"), "cst_12345")
        self.assertEqual(page.sanitize_csv_field("Jan Tester"), "Jan Tester")

    def test_empty_and_falsey_passthrough(self):
        self.assertEqual(page.sanitize_csv_field(""), "")
        self.assertIsNone(page.sanitize_csv_field(None))


# ===========================================================================
# has_admin_access / get_context - role gate
# ===========================================================================
class TestRoleGate(_BulkPageTest):
    def test_administrator_is_allowed(self):
        # setUp already runs as Administrator.
        self.assertTrue(page.has_admin_access())

    def test_plain_member_user_is_denied(self):
        # A user with none of the privileged roles the page requires.
        user = self._make_unprivileged_user()
        with self.set_user(user):
            self.assertFalse(page.has_admin_access())

    def test_get_context_denies_unprivileged_user(self):
        user = self._make_unprivileged_user()
        with self.set_user(user):
            ctx = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                page.get_context(ctx)

    def test_get_context_allows_administrator(self):
        # setUp already runs as Administrator.
        with _patch_sdk(FakeSDKClient()):
            ctx = frappe._dict()
            returned = page.get_context(ctx)
        self.assertEqual(returned.no_cache, 1)
        self.assertTrue(returned.show_sidebar)


# ===========================================================================
# validate_csv_members - REAL Member + mandate classification (no creation)
# ===========================================================================
class TestValidateCsvMembers(_BulkPageTest):
    def test_member_with_stored_valid_mandate_is_valid(self):
        cid = "cst_VAL0001"
        self._make_member(cid, mandate_id="mdt_VAL0001", status="Active")
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_VAL0001", status="valid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="25.00",
                global_description="Dues",
            )

        self.assertEqual(res["status"], "success")
        row = res["results"][0]
        self.assertEqual(row["customer_id"], cid)
        self.assertEqual(row["status"], "valid")
        self.assertTrue(row["mandate_valid"])
        self.assertEqual(row["mandate_id"], "mdt_VAL0001")
        self.assertEqual(row["amount"], 25.0)

    def test_unknown_customer_id_is_error(self):
        # No member exists with this Mollie customer id.
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(
                self._csv("cst_NOBODY99"),
                global_charge_date=_future_date(30),
                global_amount="25.00",
            )
        row = res["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("Member not found with this customer ID", row["issues"])

    def test_member_with_invalid_stored_mandate_is_error(self):
        cid = "cst_BADMDT01"
        self._make_member(cid, mandate_id="mdt_BAD0001", status="Active")
        # SDK reports the mandate is invalid (e.g. revoked).
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_BAD0001", status="invalid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="25.00",
            )
        row = res["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertFalse(row["mandate_valid"])
        self.assertTrue(any("Mandate status is invalid" in i for i in row["issues"]))

    def test_member_without_stored_mandate_discovers_valid_one_from_mollie(self):
        cid = "cst_DISC0001"
        # No mollie_mandate_id stored -> page falls back to debug_customer() and
        # scans the customer's mandates for a valid one.
        self._make_member(cid, mandate_id=None, status="Active")
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_DISC0001", status="valid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="25.00",
            )
        row = res["results"][0]
        self.assertTrue(row["mandate_valid"])
        self.assertEqual(row["mandate_id"], "mdt_DISC0001")
        self.assertTrue(any("Mandate found via Mollie API" in i for i in row["issues"]))

    def test_member_without_mandate_and_none_valid_is_error(self):
        cid = "cst_NOMDT001"
        self._make_member(cid, mandate_id=None, status="Active")
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_X", status="invalid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="25.00",
            )
        row = res["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("No valid mandate found", row["issues"])

    def test_inactive_member_is_warning_not_blocking(self):
        cid = "cst_INACT001"
        self._make_member(cid, mandate_id="mdt_INACT01", status="Suspended")
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_INACT01", status="valid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="25.00",
            )
        row = res["results"][0]
        # Valid mandate but non-Active status -> warning, with a status issue.
        self.assertEqual(row["status"], "warning")
        self.assertTrue(any("Member status is Suspended" in i for i in row["issues"]))

    def test_missing_amount_is_error(self):
        cid = "cst_NOAMT001"
        self._make_member(cid, mandate_id="mdt_NOAMT01", status="Active")
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_NOAMT01", status="valid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="",  # no amount anywhere
            )
        row = res["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertIn("Amount is required", row["issues"])

    def test_member_id_suffix_appended_to_description(self):
        cid = "cst_SUFFIX01"
        member = self._make_member(cid, mandate_id="mdt_SUF0001", status="Active")
        sdk = FakeSDKClient(mandates=[_Mandate("mdt_SUF0001", status="valid")])

        with _patch_sdk(sdk):
            res = page.validate_csv_members(
                self._csv(cid),
                global_charge_date=_future_date(30),
                global_amount="25.00",
                global_description="Dues",
                include_member_id_suffix=True,
            )
        row = res["results"][0]
        self.assertIn("voor lidnummer", row["description"])
        self.assertIn(str(member.member_id), row["description"])

    # -- input guards ---------------------------------------------------------
    def test_invalid_interval_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(self._csv("cst_x"), payment_interval="5 months")
        self.assertEqual(res["status"], "error")
        self.assertIn("Invalid interval", res["error"])

    def test_payment_times_below_one_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(self._csv("cst_x"), payment_times=0)
        self.assertEqual(res["status"], "error")
        self.assertIn("at least 1", res["error"])

    def test_payment_times_over_cap_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(self._csv("cst_x"), payment_times=101)
        self.assertEqual(res["status"], "error")
        self.assertIn("cannot exceed 100", res["error"])

    def test_oversized_csv_rejected(self):
        big = "customer_id\n" + ("cst_x\n" * 1) + ("A" * (page.MAX_CSV_SIZE + 10))
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(big)
        self.assertEqual(res["status"], "error")
        self.assertIn("too large", res["error"])

    def test_too_many_rows_rejected(self):
        rows = [f"cst_{i}" for i in range(page.MAX_CSV_ROWS + 1)]
        csv_content = self._csv(*rows)
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(
                csv_content,
                global_charge_date=_future_date(30),
                global_amount="25.00",
            )
        self.assertEqual(res["status"], "error")
        self.assertIn("Too many rows", res["error"])

    def test_missing_customer_id_column_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members("wrong_column\ncst_x\n")
        self.assertEqual(res["status"], "error")
        self.assertIn("Required column: customer_id", res["error"])

    def test_past_global_charge_date_rejected(self):
        past = frappe.utils.add_days(frappe.utils.nowdate(), -5)
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(
                self._csv("cst_x"),
                global_charge_date=past,
                global_amount="25.00",
            )
        self.assertEqual(res["status"], "error")
        self.assertIn("must be in the future", res["error"])

    def test_negative_global_amount_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.validate_csv_members(
                self._csv("cst_x"),
                global_charge_date=_future_date(30),
                global_amount="-10",
            )
        self.assertEqual(res["status"], "error")
        self.assertIn("must be positive", res["error"])

    def test_access_denied_for_unprivileged_user(self):
        # The @high_security_api decorator enforces authentication BEFORE the
        # function body runs and raises a framework PermissionError for a user
        # with no privileged profile/role. (The body's own has_admin_access()
        # guard never executes for such users - the decorator blocks first.)
        self._make_member("cst_VDENY001")
        user = self._make_unprivileged_user()
        with self.set_user(user):
            with _patch_sdk(FakeSDKClient()):
                with self.assertRaises(frappe.PermissionError):
                    page.validate_csv_members(self._csv("cst_VDENY001"))


# ===========================================================================
# create_bulk_payments - stub ONLY the Mollie subscription-creation boundary
# ===========================================================================
class TestCreateBulkPayments(_BulkPageTest):
    def _payment(self, **over):
        base = {
            "customer_id": "cst_CREATE01",
            "member_name": "Jan Tester",
            "amount": 25.0,
            "charge_date": _future_date(30),
            "description": "Membership payment",
            "mandate_id": "mdt_CREATE01",
            "interval": "1 month",
            "times": 1,
        }
        base.update(over)
        return base

    def test_creates_subscription_with_correct_payload(self):
        sdk = FakeSDKClient()
        payment = self._payment()
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))

        self.assertEqual(res["status"], "completed")
        self.assertEqual(res["summary"]["success"], 1)
        self.assertEqual(res["summary"]["errors"], 0)
        self.assertEqual(res["summary"]["total_amount"], 25.0)

        # The SDK received exactly one create with the per-member payload.
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)
        cust, data = sdk.recorder.subscriptions_created[0]
        self.assertEqual(cust, "cst_CREATE01")
        self.assertEqual(data["mandateId"], "mdt_CREATE01")
        self.assertEqual(data["interval"], "1 month")
        self.assertEqual(data["times"], 1)
        self.assertEqual(data["startDate"], payment["charge_date"])
        self.assertEqual(data["amount"], {"currency": "EUR", "value": "25.00"})

        row = res["results"][0]
        self.assertEqual(row["status"], "success")
        self.assertEqual(row["payment_id"], "sub_CREATED1")

    def test_times_defaults_to_one_when_omitted(self):
        # When the per-payment JSON omits ``times`` (e.g. an older frontend, or a
        # row built before the field existed), the create path must default to a
        # single charge - it must NOT fall through to an unlimited subscription.
        sdk = FakeSDKClient()
        payment = self._payment()
        del payment["times"]
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))

        self.assertEqual(res["summary"]["success"], 1)
        _cust, data = sdk.recorder.subscriptions_created[0]
        self.assertEqual(data.get("times"), 1)

    def test_multi_payment_times_forwarded(self):
        # A multi-payment plan selected during validation (e.g. 12 charges) must
        # reach the SDK as times=12 - it must not silently collapse to one.
        sdk = FakeSDKClient()
        payment = self._payment(times=12)
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))

        self.assertEqual(res["summary"]["success"], 1)
        _cust, data = sdk.recorder.subscriptions_created[0]
        self.assertEqual(data["times"], 12)
        self.assertEqual(data["interval"], "1 month")

    def test_service_error_is_reported_and_excluded_from_total(self):
        # When the underlying create fails (SDK rejects it), the row is an error
        # and its amount must NOT inflate the batch total_amount.
        sdk = FakeSDKClient(raise_on_create=True)
        payment = self._payment(amount=25.0)
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))

        # The create was attempted (reached the SDK) but failed.
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)
        self.assertEqual(res["summary"]["errors"], 1)
        self.assertEqual(res["summary"]["success"], 0)
        self.assertEqual(res["summary"]["total_amount"], 0.0)
        row = res["results"][0]
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["payment_id"])

    def test_missing_mandate_is_reported_error_without_sdk_call(self):
        sdk = FakeSDKClient()
        payment = self._payment(mandate_id=None)
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))
        self.assertEqual(res["summary"]["errors"], 1)
        self.assertEqual(res["results"][0]["error"], "No valid mandate ID")
        self.assertEqual(len(sdk.recorder.subscriptions_created), 0)

    def test_non_positive_amount_is_reported_error(self):
        sdk = FakeSDKClient()
        payment = self._payment(amount=0)
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))
        self.assertEqual(res["summary"]["errors"], 1)
        self.assertEqual(res["results"][0]["error"], "Invalid amount")
        self.assertEqual(len(sdk.recorder.subscriptions_created), 0)

    def test_missing_charge_date_is_reported_error(self):
        sdk = FakeSDKClient()
        payment = self._payment(charge_date=None)
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))
        self.assertEqual(res["summary"]["errors"], 1)
        self.assertIn("Charge date is required", res["results"][0]["error"])
        self.assertEqual(len(sdk.recorder.subscriptions_created), 0)

    def test_duplicate_subscription_is_skipped(self):
        charge = _future_date(30)
        # An existing ACTIVE subscription with the same start date + amount.
        existing = _Sub(sub_id="sub_EXISTING", status="active", start_date=charge)
        existing.amount = {"value": "25.00", "currency": "EUR"}
        sdk = FakeSDKClient(subs=[existing])
        payment = self._payment(charge_date=charge, amount=25.0)

        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))

        self.assertEqual(res["summary"]["skipped"], 1)
        self.assertEqual(res["summary"]["success"], 0)
        row = res["results"][0]
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["payment_id"], "sub_EXISTING")
        # No new subscription was created.
        self.assertEqual(len(sdk.recorder.subscriptions_created), 0)

    def test_cancelled_existing_subscription_does_not_block_creation(self):
        charge = _future_date(30)
        cancelled = _Sub(sub_id="sub_CANCELLED", status="canceled", start_date=charge)
        cancelled.amount = {"value": "25.00", "currency": "EUR"}
        sdk = FakeSDKClient(subs=[cancelled])
        payment = self._payment(charge_date=charge, amount=25.0)

        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([payment]))

        # Cancelled sub is ignored -> a fresh subscription is created.
        self.assertEqual(res["summary"]["success"], 1)
        self.assertEqual(len(sdk.recorder.subscriptions_created), 1)

    def test_mixed_batch_counts_success_and_error(self):
        sdk = FakeSDKClient()
        good = self._payment(customer_id="cst_GOOD", mandate_id="mdt_GOOD")
        bad = self._payment(customer_id="cst_BAD", mandate_id=None)
        with _patch_sdk(sdk):
            res = page.create_bulk_payments(json.dumps([good, bad]))
        self.assertEqual(res["summary"]["total"], 2)
        self.assertEqual(res["summary"]["success"], 1)
        self.assertEqual(res["summary"]["errors"], 1)

    def test_empty_payload_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.create_bulk_payments("")
        self.assertEqual(res["status"], "error")
        self.assertIn("Payments data is required", res["error"])

    def test_oversized_payload_rejected(self):
        big = "[" + ("0" * (page.MAX_PAYMENTS_PAYLOAD_SIZE + 10)) + "]"
        with _patch_sdk(FakeSDKClient()):
            res = page.create_bulk_payments(big)
        self.assertEqual(res["status"], "error")
        self.assertIn("payload too large", res["error"])

    def test_invalid_json_rejected(self):
        with _patch_sdk(FakeSDKClient()):
            res = page.create_bulk_payments("{not json")
        self.assertEqual(res["status"], "error")
        self.assertIn("Invalid JSON", res["error"])

    def test_access_denied_for_unprivileged_user(self):
        user = self._make_unprivileged_user()
        with self.set_user(user):
            # @high_security_api blocks the unprivileged caller at the decorator
            # boundary, before the body's has_admin_access() guard.
            with _patch_sdk(FakeSDKClient()):
                with self.assertRaises(frappe.PermissionError):
                    page.create_bulk_payments(json.dumps([self._payment()]))


# ===========================================================================
# get_webhook_url - environment parameter from Mollie Settings
# ===========================================================================
class TestGetWebhookUrl(_BulkPageTest):
    def test_url_targets_webhook_method_and_has_env_param(self):
        url = page.get_webhook_url()
        self.assertIn(
            "/api/method/verenigingen.utils.payment_gateways.mollie_payment_webhook",
            url,
        )
        self.assertRegex(url, r"\?env=(test|live)$")
