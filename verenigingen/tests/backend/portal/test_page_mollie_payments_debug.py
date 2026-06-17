# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""
Integration tests for the Mollie payments debug page controller
(``verenigingen/templates/pages/mollie_payments_debug.py``).

This is an administrative debugging tool that exposes a large set of thin
whitelisted wrappers around ``MollieDebugService``. The behaviours under test:

* ``get_context`` - the login + role gate guarding the page, plus the Mollie
  context population on the allow path.
* ``has_mollie_debug_access`` / ``has_customer_deletion_access`` - the two
  access helpers (the latter is the most restrictive: Verenigingen
  Administrator only).
* The "return {error}"-style read endpoints (``debug_customer``,
  ``debug_subscription``, ``debug_mandate``, ``debug_payment``,
  ``list_customers``, ``list_payments``, ``list_chargebacks``,
  ``search_customers_by_name``): under a non-privileged user they catch the
  access throw and RETURN an error dict; under an admin they pass the service
  result straight through.
* The throw-style admin mutation endpoints (``admin_cancel_subscription``,
  ``admin_revoke_mandate``, ``create_mandate``): admin happy-path passthrough.
* ``admin_delete_customer`` - guarded by ``has_customer_deletion_access`` and
  ``frappe.throw``s on denial, so even Verenigingen Staff is rejected.
* ``create_subscription`` / ``create_scheduled_subscription`` - Verenigingen
  Administrator only; non-admins get a returned error dict (the endpoint
  catches its own throw).
* ``list_subscriptions`` and ``retrieve_customer_payments_for_processing`` /
  ``batch_process_dues_payments`` - access-denied returned-error branch and an
  admin passthrough.

Everything runs against the real role machinery via ``self.as_role``. The ONLY
external boundary stubbed is the Mollie API: the controller builds a real
``MollieDebugService`` (whose ``__init__`` constructs a real MollieClient that
would need live credentials). We patch the ``MollieDebugService`` symbol at the
controller's import seam with ``FakeMollieDebugService`` so the controller's own
guard + passthrough logic is exercised unmodified, never the business logic.
"""

from unittest.mock import patch

import frappe

from verenigingen.templates.pages import mollie_payments_debug as page
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.constants import Roles


class FakeMollieDebugService:
    """Stand-in for MollieDebugService exposing only what the controller calls.

    Every method records the args it was called with and returns a sentinel
    dict so tests can assert the controller passed the result through verbatim.
    A single fake serves every endpoint; methods we don't assert on simply
    return a recognisable sentinel.
    """

    def __init__(self, *args, **kwargs):
        # Record that the controller actually constructed the service.
        type(self).instantiated = True

    def _sentinel(self, name, **kwargs):
        type(self).last_call = (name, kwargs)
        return {"_fake": name, **kwargs}

    def debug_customer(self, customer_id):
        return self._sentinel("debug_customer", customer_id=customer_id)

    def debug_subscription(self, subscription_id, customer_id=None):
        return self._sentinel("debug_subscription", subscription_id=subscription_id, customer_id=customer_id)

    def debug_mandate(self, mandate_id, customer_id=None):
        return self._sentinel("debug_mandate", mandate_id=mandate_id, customer_id=customer_id)

    def debug_payment(self, payment_id):
        return self._sentinel("debug_payment", payment_id=payment_id)

    def list_customers(self, limit):
        return self._sentinel("list_customers", limit=limit)

    def search_customers_by_name(self, search_term, limit):
        return self._sentinel("search_customers_by_name", search_term=search_term, limit=limit)

    def list_payments(self, customer_id, limit, status_filter):
        return self._sentinel(
            "list_payments", customer_id=customer_id, limit=limit, status_filter=status_filter
        )

    def list_chargebacks(self, customer_id, limit):
        return self._sentinel("list_chargebacks", customer_id=customer_id, limit=limit)

    def admin_cancel_subscription(self, customer_id, subscription_id, reason):
        return self._sentinel(
            "admin_cancel_subscription",
            customer_id=customer_id,
            subscription_id=subscription_id,
            reason=reason,
        )

    def admin_revoke_mandate(self, customer_id, mandate_id, reason):
        return self._sentinel(
            "admin_revoke_mandate", customer_id=customer_id, mandate_id=mandate_id, reason=reason
        )

    def create_mandate(self, **kwargs):
        return self._sentinel("create_mandate", **kwargs)

    def admin_delete_customer(self, customer_id, reason, confirmation_text):
        return self._sentinel(
            "admin_delete_customer",
            customer_id=customer_id,
            reason=reason,
            confirmation_text=confirmation_text,
        )

    def create_subscription(self, customer_id, amount, interval, description, mandate_id, start_date):
        return self._sentinel(
            "create_subscription",
            customer_id=customer_id,
            amount=amount,
            interval=interval,
        )

    def create_scheduled_subscription(
        self, customer_id, amount, interval_count, interval_unit, description, times, start_date, mandate_id
    ):
        return self._sentinel(
            "create_scheduled_subscription",
            customer_id=customer_id,
            amount=amount,
            interval_unit=interval_unit,
        )

    def list_subscriptions(self, customer_id, limit, active_only):
        return self._sentinel(
            "list_subscriptions", customer_id=customer_id, limit=limit, active_only=active_only
        )

    def create_test_payment(self, amount, description, customer_id, due_date):
        return self._sentinel(
            "create_test_payment", amount=amount, description=description, customer_id=customer_id
        )

    def retrieve_customer_payments_for_processing(self, customer_id, limit):
        return self._sentinel(
            "retrieve_customer_payments_for_processing", customer_id=customer_id, limit=limit
        )

    def batch_process_dues_payments(self, payment_ids, customer_id):
        return self._sentinel("batch_process_dues_payments", payment_ids=payment_ids, customer_id=customer_id)


class TestPageMolliePaymentsDebug(EnhancedTestCase):
    def setUp(self):
        self._original_user = frappe.session.user
        super().setUp()
        self._original_form_dict = frappe.local.form_dict
        frappe.local.form_dict = frappe._dict()
        FakeMollieDebugService.instantiated = False
        FakeMollieDebugService.last_call = None

    def tearDown(self):
        frappe.local.form_dict = self._original_form_dict
        if hasattr(self, "_original_user"):
            frappe.set_user(self._original_user)
        super().tearDown()

    def _patch_service(self):
        return patch.object(page, "MollieDebugService", FakeMollieDebugService)

    # A valid Mollie payment id format so validate_mollie_payment_ids passes.
    VALID_PAYMENT_ID = "tr_WDqYK6vllg"

    # The whitelisted endpoints are wrapped by @high_security_api, which gates on
    # the HIGH security level via the role-profile authorization table BEFORE the
    # function body runs. "Verenigingen Volunteer" only grants MEDIUM/LOW, so the
    # *decorator* denies it (raising frappe.PermissionError) and the controller's
    # own guard is never reached. To exercise the controller's *own* access guards
    # (has_mollie_debug_access / has_customer_deletion_access / the
    # Verenigingen-Administrator-only checks) we need a role that PASSES the HIGH
    # decorator gate but FAILS the controller guard. "Verenigingen Chapter Board
    # Member" is exactly that: the authorization table grants it HIGH, but it is
    # not in has_mollie_debug_access()'s allowed list.
    CONTROLLER_GUARD_ROLE = "Verenigingen Chapter Board Member"

    # ------------------------------------------------------------------
    # get_context - login + role gate
    # ------------------------------------------------------------------

    def test_get_context_denies_guest_with_permission_error(self):
        """A Guest (not logged in) is rejected by require_login with PermissionError."""
        with self.as_user("Guest"):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                page.get_context(context)

    def test_get_context_denies_volunteer_with_permission_error(self):
        """A logged-in non-privileged user (Volunteer) is denied by the role gate."""
        with self.as_role(Roles.VOLUNTEER):
            context = frappe._dict()
            with self.assertRaises(frappe.PermissionError):
                page.get_context(context)

    def test_get_context_allows_admin_and_populates_mollie(self):
        """A Verenigingen Administrator gets a titled context with CSRF + Mollie fields."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            context = frappe._dict()
            page.get_context(context)
            self.assertEqual(context.title, "Mollie Payments Debug")
            self.assertEqual(context.no_cache, 1)
            self.assertTrue(context.show_sidebar)
            self.assertTrue(context.csrf_token)
            # populate_mollie_context always sets this key.
            self.assertIn("mollie_configured", context)

    # ------------------------------------------------------------------
    # access helpers
    # ------------------------------------------------------------------

    def test_has_mollie_debug_access_true_for_staff(self):
        with self.as_role(Roles.VERENIGINGEN_STAFF):
            self.assertTrue(page.has_mollie_debug_access())

    def test_has_mollie_debug_access_false_for_volunteer(self):
        with self.as_role(Roles.VOLUNTEER):
            self.assertFalse(page.has_mollie_debug_access())

    def test_has_customer_deletion_access_true_only_for_admin(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN):
            self.assertTrue(page.has_customer_deletion_access())

    def test_has_customer_deletion_access_false_for_staff(self):
        """Staff has general debug access but NOT the stricter deletion access."""
        with self.as_role(Roles.VERENIGINGEN_STAFF):
            self.assertTrue(page.has_mollie_debug_access())
            self.assertFalse(page.has_customer_deletion_access())

    # ------------------------------------------------------------------
    # @high_security_api decorator gate (HIGH level) - denies Volunteer
    # before the controller body runs.
    # ------------------------------------------------------------------

    def test_decorator_denies_volunteer_before_body_runs(self):
        """Volunteer only grants MEDIUM/LOW, so the HIGH decorator gate raises."""
        with self.as_role(Roles.VOLUNTEER), self._patch_service():
            with self.assertRaises(frappe.PermissionError):
                page.debug_customer("cst_x")
        # The body never ran, so the service was never constructed.
        self.assertFalse(FakeMollieDebugService.instantiated)

    def test_decorator_denies_volunteer_on_mutation_endpoint(self):
        with self.as_role(Roles.VOLUNTEER), self._patch_service():
            with self.assertRaises(frappe.PermissionError):
                page.admin_cancel_subscription("cst_x", "sub_x")

    # ------------------------------------------------------------------
    # "return {error}"-style read endpoints - controller's OWN guard.
    #
    # A Chapter Board Member passes the HIGH decorator gate but is NOT in
    # has_mollie_debug_access()'s allow-list, so it reaches the body and the
    # controller's own guard fires. For these endpoints the throw is caught
    # and an error dict is returned.
    # ------------------------------------------------------------------

    def test_debug_customer_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.debug_customer("cst_x")
        self.assertIn("error", result)
        self.assertEqual(result["customer_id"], "cst_x")

    def test_debug_subscription_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.debug_subscription("sub_x")
        self.assertIn("error", result)
        self.assertEqual(result["subscription_id"], "sub_x")

    def test_debug_mandate_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.debug_mandate("mdt_x")
        self.assertIn("error", result)
        self.assertEqual(result["mandate_id"], "mdt_x")

    def test_debug_payment_guard_raises(self):
        """debug_payment has NO try/except around the access check, so denial raises."""
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            with self.assertRaises(frappe.ValidationError):
                page.debug_payment("tr_x")

    def test_list_customers_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.list_customers(limit=5)
        self.assertIn("error", result)
        self.assertEqual(result["limit"], 5)

    def test_list_payments_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.list_payments(customer_id="cst_x")
        self.assertIn("error", result)
        self.assertEqual(result["customer_id"], "cst_x")

    def test_list_chargebacks_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.list_chargebacks(customer_id="cst_x")
        self.assertIn("error", result)
        self.assertEqual(result["customer_id"], "cst_x")

    def test_search_customers_by_name_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.search_customers_by_name(search_term="alice")
        self.assertIn("error", result)
        self.assertEqual(result["search_term"], "alice")

    # ------------------------------------------------------------------
    # "return {error}"-style read endpoints - admin passthrough
    # ------------------------------------------------------------------

    def test_debug_customer_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.debug_customer("cst_abc")
        self.assertEqual(result, {"_fake": "debug_customer", "customer_id": "cst_abc"})

    def test_debug_subscription_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.debug_subscription("sub_abc", customer_id="cst_abc")
        self.assertEqual(result["_fake"], "debug_subscription")
        self.assertEqual(result["subscription_id"], "sub_abc")
        self.assertEqual(result["customer_id"], "cst_abc")

    def test_debug_mandate_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.debug_mandate("mdt_abc")
        self.assertEqual(result["_fake"], "debug_mandate")
        self.assertEqual(result["mandate_id"], "mdt_abc")

    def test_debug_payment_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.debug_payment("tr_abc")
        self.assertEqual(result, {"_fake": "debug_payment", "payment_id": "tr_abc"})

    def test_list_customers_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.list_customers(limit=7)
        self.assertEqual(result["_fake"], "list_customers")
        self.assertEqual(result["limit"], 7)

    def test_list_payments_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.list_payments(customer_id="cst_p", limit=3, status_filter="paid")
        self.assertEqual(result["_fake"], "list_payments")
        self.assertEqual(result["customer_id"], "cst_p")
        self.assertEqual(result["status_filter"], "paid")

    def test_list_chargebacks_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.list_chargebacks(customer_id="cst_c", limit=4)
        self.assertEqual(result["_fake"], "list_chargebacks")
        self.assertEqual(result["customer_id"], "cst_c")

    def test_search_customers_by_name_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.search_customers_by_name(search_term="bob", limit=9)
        self.assertEqual(result["_fake"], "search_customers_by_name")
        self.assertEqual(result["search_term"], "bob")
        self.assertEqual(result["limit"], 9)

    # ------------------------------------------------------------------
    # throw-style admin mutation endpoints
    # ------------------------------------------------------------------

    def test_admin_cancel_subscription_guard_raises(self):
        """Controller guard frappe.throws (re-raised by the generic handler)."""
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            with self.assertRaises(frappe.ValidationError):
                page.admin_cancel_subscription("cst_x", "sub_x")

    def test_admin_cancel_subscription_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.admin_cancel_subscription("cst_x", "sub_x", reason="cleanup")
        self.assertEqual(result["_fake"], "admin_cancel_subscription")
        self.assertEqual(result["reason"], "cleanup")

    def test_admin_revoke_mandate_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.admin_revoke_mandate("cst_x", "mdt_x")
        self.assertEqual(result["_fake"], "admin_revoke_mandate")
        self.assertEqual(result["mandate_id"], "mdt_x")

    def test_create_mandate_guard_raises(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            with self.assertRaises(frappe.ValidationError):
                page.create_mandate("cst_x", "Jane Doe", "NL91ABNA0417164300")

    def test_create_mandate_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.create_mandate("cst_x", "Jane Doe", "NL91ABNA0417164300", consumer_bic="ABNANL2A")
        self.assertEqual(result["_fake"], "create_mandate")
        self.assertEqual(result["customer_id"], "cst_x")
        self.assertEqual(result["consumer_name"], "Jane Doe")

    # ------------------------------------------------------------------
    # admin_delete_customer - strictest gate (Verenigingen Administrator only).
    # Staff PASSES the HIGH decorator gate but has_customer_deletion_access()
    # rejects it -> frappe.throw (re-raised).
    # ------------------------------------------------------------------

    def test_admin_delete_customer_denied_for_staff_raises(self):
        with self.as_role(Roles.VERENIGINGEN_STAFF), self._patch_service():
            with self.assertRaises(frappe.ValidationError):
                page.admin_delete_customer("cst_x", confirmation_text="DELETE")

    def test_admin_delete_customer_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.admin_delete_customer("cst_x", reason="gdpr", confirmation_text="DELETE cst_x")
        self.assertEqual(result["_fake"], "admin_delete_customer")
        self.assertEqual(result["reason"], "gdpr")
        self.assertEqual(result["confirmation_text"], "DELETE cst_x")

    # ------------------------------------------------------------------
    # create_subscription / create_scheduled_subscription - Verenigingen
    # Administrator only (checked inside the body). Staff PASSES the HIGH
    # decorator gate but fails the in-body admin check; the throw is CAUGHT
    # and returned as an error dict.
    # ------------------------------------------------------------------

    def test_create_subscription_denied_for_staff_returns_error(self):
        with self.as_role(Roles.VERENIGINGEN_STAFF), self._patch_service():
            result = page.create_subscription("cst_x", 10.0, "1 month", "Dues")
        self.assertIn("error", result)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["customer_id"], "cst_x")

    def test_create_subscription_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.create_subscription("cst_x", 10.0, "1 month", "Dues")
        self.assertEqual(result["_fake"], "create_subscription")
        self.assertEqual(result["amount"], 10.0)
        self.assertEqual(result["interval"], "1 month")

    def test_create_scheduled_subscription_denied_for_staff_returns_error(self):
        with self.as_role(Roles.VERENIGINGEN_STAFF), self._patch_service():
            result = page.create_scheduled_subscription("cst_x", 10.0, 1, "months", "Dues")
        self.assertIn("error", result)
        self.assertEqual(result["status"], "error")

    def test_create_scheduled_subscription_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.create_scheduled_subscription("cst_x", 25.0, 2, "weeks", "Dues")
        self.assertEqual(result["_fake"], "create_scheduled_subscription")
        self.assertEqual(result["interval_unit"], "weeks")

    # ------------------------------------------------------------------
    # create_test_payment - debug-access endpoint
    # ------------------------------------------------------------------

    def test_create_test_payment_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.create_test_payment(5.0, "Test")
        self.assertIn("error", result)
        self.assertEqual(result["status"], "error")

    def test_create_test_payment_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.create_test_payment(5.0, "Test payment")
        self.assertEqual(result["_fake"], "create_test_payment")
        self.assertEqual(result["amount"], 5.0)
        self.assertEqual(result["description"], "Test payment")

    # ------------------------------------------------------------------
    # list_subscriptions - debug-access + input sanitisation
    # ------------------------------------------------------------------

    def test_list_subscriptions_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.list_subscriptions("cst_x")
        self.assertIn("error", result)
        self.assertEqual(result["customer_id"], "cst_x")

    def test_list_subscriptions_admin_passthrough_with_sanitised_limit(self):
        """An out-of-range limit is clamped to 50 and a string active_only is coerced."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.list_subscriptions("cst_x", limit=99999, active_only="false")
        self.assertEqual(result["_fake"], "list_subscriptions")
        self.assertEqual(result["limit"], 50)
        self.assertIs(result["active_only"], False)

    # ------------------------------------------------------------------
    # two-stage dues processing (POST endpoints)
    # ------------------------------------------------------------------

    def test_retrieve_customer_payments_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.retrieve_customer_payments_for_processing("cst_x")
        self.assertIn("error", result)
        self.assertEqual(result["customer_id"], "cst_x")

    def test_retrieve_customer_payments_admin_passthrough(self):
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            result = page.retrieve_customer_payments_for_processing("cst_x", limit=10)
        self.assertEqual(result["_fake"], "retrieve_customer_payments_for_processing")
        self.assertEqual(result["customer_id"], "cst_x")
        self.assertEqual(result["limit"], 10)

    def test_batch_process_dues_payments_guard_returns_error(self):
        with self.as_role(self.CONTROLLER_GUARD_ROLE), self._patch_service():
            result = page.batch_process_dues_payments([self.VALID_PAYMENT_ID])
        self.assertIn("error", result)

    def test_batch_process_dues_payments_admin_passthrough(self):
        """Admin happy path; clear the per-user rate-limit cache key first."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            # Rate-limit key is per session user; clear it under the scratch user.
            frappe.cache().delete_value(f"dues_batch_limit:{frappe.session.user}")
            result = page.batch_process_dues_payments([self.VALID_PAYMENT_ID], customer_id="cst_x")
        self.assertEqual(result["_fake"], "batch_process_dues_payments")
        self.assertEqual(result["payment_ids"], [self.VALID_PAYMENT_ID])
        self.assertEqual(result["customer_id"], "cst_x")

    def test_batch_process_dues_payments_invalid_id_returns_error(self):
        """A bad-format payment id is rejected by validate_mollie_payment_ids."""
        with self.as_role(Roles.VERENIGINGEN_ADMIN), self._patch_service():
            frappe.cache().delete_value(f"dues_batch_limit:{frappe.session.user}")
            result = page.batch_process_dues_payments(["not-a-valid-id"])
        self.assertIn("error", result)
