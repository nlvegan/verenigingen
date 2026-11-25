# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""#2927 (services/doctype half of #2280): internal code called ``member_doc.get_current_membership_fee()``,
the ``@whitelist`` + ``@standard_api`` METHOD. Each such call ran the endpoint's security stack inside
an already-authorised flow: a second rate-limit bucket, a second audit row and a MEDIUM gate.

Each test drives one real internal caller as a real user with the rate limiter live (the harness's
in_test bypass lifted) and reads the LIVE redis counters back: the internal caller must tick no bucket
of the decorated method. A control asserts the amount still comes from the fee service, so a fix that
merely stops calling anything cannot pass. The whitelisted endpoint itself must stay whitelisted.
"""

from types import SimpleNamespace

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

FEE_ENDPOINT = "get_current_membership_fee"


class TestMembershipFeeInternalCallers2927(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._cleanup_test_mocks()  # drops the harness's validate_rate_limits stub (idempotent)
        self.addCleanup(self._clear_buckets_2927)
        self._clear_buckets_2927()
        self.member = self.create_test_member(
            first_name="Fee2927",
            last_name="Caller",
            email=f"fee2927.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"Fee2927Type{frappe.generate_hash(length=6)}"
        )
        self.membership = self.create_test_membership(
            member=self.member.name, membership_type=self.membership_type.name
        )
        self.membership.submit()
        self.membership.reload()
        self.caller = f"fee2927.user.{frappe.generate_hash(length=6)}@test.invalid"
        user = self.create_test_user(self.caller)
        user.append("role_profiles", {"role_profile": "Verenigingen Administrator"})
        user.save(ignore_permissions=True)

    @staticmethod
    def _redis_2927():
        import redis

        return redis.from_url(frappe.conf.redis_cache)

    def _clear_buckets_2927(self):
        r = self._redis_2927()
        for k in r.keys(f"cor_rate_limit:{frappe.local.site}:*"):
            r.delete(k)

    def _live_run_2927(self, fn):
        """Run ``fn`` as ``self.caller`` with the limiter live; return (result, error, {operation: count})."""
        saved = (frappe.flags.in_test, getattr(frappe.local, "request", None), frappe.local.form_dict)
        before_user = frappe.session.user
        self._clear_buckets_2927()
        # Mock justified: Infrastructure - the limiter skips itself under in_test and needs a request
        frappe.flags.in_test = False
        frappe.local.request = SimpleNamespace(
            method="POST",
            environ={"REMOTE_ADDR": "203.0.113.9"},
            headers={},
            host="localhost",
            scheme="http",
            host_url="http://localhost/",
            url="http://localhost/",
            path="/",
        )
        frappe.set_user(self.caller)
        result = error = None
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - a refusal IS the observation
            error = e
        finally:
            frappe.set_user(before_user)
            r = self._redis_2927()
            buckets = {
                k.decode().split(":")[3]: int(r.get(k))
                for k in r.keys(f"cor_rate_limit:{frappe.local.site}:*")
            }
            frappe.flags.in_test, frappe.local.request, frappe.local.form_dict = saved  # Mock justified
        return result, error, buckets

    def _assert_no_fee_endpoint_tick_2927(self, buckets):
        ticked = [op for op in buckets if op.endswith(FEE_ENDPOINT)]
        self.assertEqual(ticked, [], f"an internal caller ticked the endpoint's bucket: {buckets}")

    def _expected_fee_2927(self):
        from verenigingen.services.member.financial.member_fee_calculation_service import (
            get_member_fee_calculation_service,
        )

        return get_member_fee_calculation_service().get_current_membership_fee(
            frappe.get_doc("Member", self.member.name)
        )

    def test_the_fee_endpoint_itself_is_still_dispatchable_and_ticks_its_bucket(self):
        """Control for the bucket reader: the real endpoint DOES tick (so zero ticks above means something),
        and it is still whitelisted for HTTP callers."""
        path = "verenigingen.verenigingen.doctype.member.member.get_current_membership_fee"
        frappe.is_whitelisted(frappe.get_attr(path))  # raises PermissionError when not whitelisted
        self.assertIn(frappe.get_attr(path), frappe.whitelisted)
        _, error, buckets = self._live_run_2927(
            lambda: frappe.get_doc("Member", self.member.name).get_current_membership_fee()
        )
        self.assertIsNone(error)
        self.assertTrue([op for op in buckets if op.endswith(FEE_ENDPOINT)], buckets)

    def test_approval_invoice_creation_ticks_no_fee_endpoint_bucket(self):
        from verenigingen.services.member.approval.membership_creation_service import (
            get_membership_creation_service,
        )

        from verenigingen.services.member.approval.application_payments import get_membership_item

        # Build the lazily-created Item now: the live-limiter run below lifts in_test, under which the
        # invoice path's Item insert is refused for the caller (that refusal is not what is under test).
        get_membership_item(self.membership_type)
        service = get_membership_creation_service()
        member_doc = frappe.get_doc("Member", self.member.name)
        invoice, error, buckets = self._live_run_2927(
            lambda: service._create_membership_invoice(member_doc, self.membership, self.membership_type)
        )
        self._assert_no_fee_endpoint_tick_2927(buckets)
        self.assertIsNone(error)
        self.assertIsNotNone(invoice, "invoice creation was swallowed")
        self.track_doc("Sales Invoice", invoice.name)
        self.assertEqual(invoice.grand_total, self._expected_fee_2927()["amount"])

    def test_amendment_set_current_details_ticks_no_fee_endpoint_bucket(self):
        # Probe shortcut: cancel the dues schedule the submit created, to reach the legacy-fee fallback.
        for name in frappe.get_all("Membership Dues Schedule", {"member": self.member.name}, pluck="name"):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")
        amendment = frappe.get_doc(
            {
                "doctype": "Contribution Amendment Request",
                "membership": self.membership.name,
                "member": self.member.name,
                "amendment_type": "Fee Change",
                "requested_amount": 25.0,
                "reason": "test",
                "status": "Draft",
            }
        )
        _, error, buckets = self._live_run_2927(amendment.set_current_details)
        self._assert_no_fee_endpoint_tick_2927(buckets)
        self.assertIsNone(error)
        self.assertEqual(amendment.current_amount, self._expected_fee_2927()["amount"])

    def test_membership_adjustment_effective_fee_ticks_no_fee_endpoint_bucket(self):
        from verenigingen.templates.pages.membership_adjustment import get_effective_fee_for_member

        for name in frappe.get_all("Membership Dues Schedule", {"member": self.member.name}, pluck="name"):
            frappe.db.set_value("Membership Dues Schedule", name, "status", "Cancelled")  # Probe shortcut
        frappe.db.set_value("Member", self.member.name, "dues_rate", 0)
        member_doc = frappe.get_doc("Member", self.member.name)
        fee, error, buckets = self._live_run_2927(
            lambda: get_effective_fee_for_member(member_doc, self.membership)
        )
        self._assert_no_fee_endpoint_tick_2927(buckets)
        self.assertIsNone(error)
        self.assertEqual(fee["amount"], self._expected_fee_2927()["amount"])

    def test_dues_invoice_debugger_page_ticks_no_workflow_status_bucket(self):
        """Sibling named in the issue thread: www/dues_invoice_debugger.py called the decorated
        get_workflow_status() endpoint in-process during the page render."""
        from verenigingen.www.dues_invoice_debugger import get_context

        context = frappe._dict()
        _, error, buckets = self._live_run_2927(lambda: get_context(context))
        self.assertIsNone(error)
        self.assertEqual(
            [op for op in buckets if op.endswith("get_workflow_status")], [], f"page ticked: {buckets}"
        )
        self.assertIn("workflow_status", context, "the page lost its workflow data")
        self.assertTrue(context.workflow_status.success, context.workflow_status)
