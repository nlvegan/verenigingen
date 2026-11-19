# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""#2280 (sweep of #352): an api/ endpoint that called ANOTHER security-decorated endpoint ran the
whole decorator stack twice: a second rate-limit bucket, a second audit row, and a second
authorisation + HTTP-method check that could answer differently from the endpoint's own.

Every test dispatches through ``frappe.handler.execute_cmd`` (the real whitelist + HTTP-method gate)
as a real user, with the in_test bypass of the rate limiter lifted, and reads the LIVE redis
counters back: an endpoint must tick exactly its own bucket, whatever decorated code it reaches.
"""

from unittest.mock import MagicMock

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase

DUES = "verenigingen.api.dues_invoice_workflow."
PAY = "verenigingen.api.payment_dashboard."


class TestDoubleDecoratedEndpoints2280(VereningingenTestCase):
    def setUp(self):
        super().setUp()
        self._cleanup_test_mocks()  # drops the harness's validate_rate_limits stub (idempotent)
        self.addCleanup(self._clear_live_buckets)
        self._clear_live_buckets()

    # ------------------------------------------------------------------ #
    # helpers (names unique on purpose: the duplicate-helper census keys on the name)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _live_bucket_redis():
        import redis

        return redis.from_url(frappe.conf.redis_cache)

    def _clear_live_buckets(self):
        r = self._live_bucket_redis()
        for k in r.keys(f"cor_rate_limit:{frappe.local.site}:*"):
            r.delete(k)

    def _live_bucket_operations(self):
        """{operation_key: count} of every live rate-limit counter on this site."""
        r = self._live_bucket_redis()
        out = {}
        for k in r.keys(f"cor_rate_limit:{frappe.local.site}:*"):
            out[k.decode().split(":")[3]] = int(r.get(k))
        return out

    def _user_with_profile_2280(self, profile):
        email = f"p2280-{frappe.generate_hash(length=8)}@example.com"
        user = self.create_test_user(email)
        user.append("role_profiles", {"role_profile": profile})
        user.save(ignore_permissions=True)
        return email

    def _member_for_user_2280(self, email):
        member = self.create_test_member(
            first_name="Dbl", last_name="Decorated", email=email, user=email, status="Active"
        )
        frappe.db.set_value("Member", member.name, "user", email)  # Probe shortcut: link the login
        for cell in frappe.get_attr(PAY + "get_member_from_user").__closure__ or ():
            if isinstance(cell.cell_contents, dict):
                cell.cell_contents.clear()  # cache_with_ttl keeps a user -> member map per process
        return member

    def _dispatch_2280(self, cmd, user, method="POST", **form):
        """Run ``cmd`` through the real whitelist/HTTP-method gate as ``user`` with the limiter live.

        Returns (result_or_None, exception_or_None, {operation: count}).
        """
        saved = (frappe.flags.in_test, getattr(frappe.local, "request", None), frappe.local.form_dict)
        caller_before = frappe.session.user
        self._clear_live_buckets()
        # Mock justified: Infrastructure - the limiter skips itself under in_test and needs a request
        frappe.flags.in_test = False
        frappe.local.request = MagicMock(method=method, environ={"REMOTE_ADDR": "203.0.113.9"})
        frappe.set_user(user)  # resets form_dict, so it is set after
        frappe.local.form_dict = frappe._dict(form)
        result = error = None
        try:
            result = frappe.handler.execute_cmd(cmd)
        except Exception as e:  # noqa: BLE001 - the refusal IS the observation
            error = e
        finally:
            frappe.set_user(caller_before)
            buckets = self._live_bucket_operations()
            frappe.flags.in_test, frappe.local.request, frappe.local.form_dict = saved  # Mock justified
        return result, error, buckets

    @staticmethod
    def _bucket_names(buckets):
        return sorted(buckets)

    def assertTicksOnly(self, cmd, buckets):
        self.assertEqual(
            self._bucket_names(buckets), [cmd], f"{cmd} ticked more than its own bucket: {buckets}"
        )
        self.assertEqual(list(buckets.values()), [1])

    # ------------------------------------------------------------------ #
    # dues_invoice_workflow
    # ------------------------------------------------------------------ #
    def test_check_member_dues_status_answers_for_its_own_level_and_method(self):
        """The endpoint is MEDIUM and GET/POST. It called a CRITICAL, POST-only endpoint, so Staff
        (MEDIUM, no CRITICAL) was refused with 'Required: critical' and a GET with 'Method GET not
        allowed'. Control: a LOW-only caller is still refused by the endpoint's own gate."""
        staff = self._user_with_profile_2280("Verenigingen Staff")
        for user, method in ((staff, "POST"), (staff, "GET")):
            with self.subTest(user=user, method=method):
                cmd = DUES + "check_member_dues_status"
                result, error, buckets = self._dispatch_2280(cmd, user, method)
                self.assertIsNone(error)
                self.assertTrue(result["success"], result)
                self.assertTicksOnly(cmd, buckets)

        member_only = self._user_with_profile_2280("Verenigingen Member")
        _, error, _ = self._dispatch_2280(DUES + "check_member_dues_status", member_only, "POST")
        self.assertIsInstance(error, frappe.PermissionError)

    def test_get_workflow_status_ticks_one_bucket_and_reports_the_real_status(self):
        """get_workflow_status ran two decorated endpoints; when the first was refused it silently
        substituted zeros, so Staff saw an all-zero workflow."""
        staff = self._user_with_profile_2280("Verenigingen Staff")
        cmd = DUES + "get_workflow_status"
        result, error, buckets = self._dispatch_2280(cmd, staff, "POST")
        self.assertIsNone(error)
        self.assertTrue(result["success"], result)
        self.assertTicksOnly(cmd, buckets)

        expected = frappe.db.count("Member", {"status": ["in", ["Active", "Pending", "Suspended"]]})
        self.assertEqual(
            result["data"]["members_analysis"]["total_active_members"],
            expected,
            "the status was served from the all-zero fallback, not from the real analysis",
        )

    # ------------------------------------------------------------------ #
    # payment_dashboard
    # ------------------------------------------------------------------ #
    def test_get_next_payment_serves_a_medium_caller_without_a_high_gate(self):
        """get_next_payment is MEDIUM; it called the HIGH get_payment_schedule, so an Auditor
        (MEDIUM only) got 'Required: high'. Control: a LOW-only caller is refused by its own gate."""
        auditor = self._user_with_profile_2280("Verenigingen Auditor")
        self._member_for_user_2280(auditor)
        cmd = PAY + "get_next_payment"
        result, error, buckets = self._dispatch_2280(cmd, auditor, "GET")
        self.assertIsNone(error)
        self.assertTrue(result["success"], result)
        self.assertTicksOnly(cmd, buckets)

        member_only = self._user_with_profile_2280("Verenigingen Member")
        _, error, _ = self._dispatch_2280(cmd, member_only, "GET")
        self.assertIsInstance(error, frappe.PermissionError)

    def test_payment_dashboard_endpoints_tick_one_bucket_and_audit_once(self):
        treasurer = self._user_with_profile_2280("Verenigingen Treasurer")
        self._member_for_user_2280(treasurer)
        for name in (
            "get_dashboard_data",
            "get_next_payment",
            "export_payment_history_csv",
            "export_all_financial_data",
        ):
            with self.subTest(endpoint=name):
                cmd = PAY + name
                audited_before = self._audit_counts_2280()
                result, error, buckets = self._dispatch_2280(cmd, treasurer, "POST")
                self.assertIsNone(error)
                self.assertTrue(result["success"], result)
                self.assertTicksOnly(cmd, buckets)
                # HIGH endpoints write exactly one audit row, under their own name; MEDIUM writes none
                expected = {} if name == "get_next_payment" else {name: 1}
                self.assertEqual(dict(self._audit_counts_2280() - audited_before), expected)

    @staticmethod
    def _audit_counts_2280():
        """{function: rows} of the API Audit Log, read from the row's own details."""
        import json
        from collections import Counter

        rows = frappe.get_all("API Audit Log", fields=["details"], limit_page_length=0)
        return Counter(json.loads(r.details or "{}").get("function") for r in rows)

    # ------------------------------------------------------------------ #
    # member_management: the loop
    # ------------------------------------------------------------------ #
    def test_bulk_assign_ticks_its_own_bucket_once_not_once_per_assignment(self):
        """N assignments ticked assign_member_to_chapter's bucket N more times. Control: the call still
        runs and reports each assignment, and Staff (no CRITICAL) is refused by the bulk gate."""
        treasurer = self._user_with_profile_2280("Verenigingen Treasurer")
        cmd = "verenigingen.api.member_management.bulk_assign_members_to_chapters"
        chapter = self.create_test_chapter()
        members = [self.create_test_member(first_name=f"Bulk{n}", last_name="Assign") for n in range(3)]
        assignments = [{"member_name": m.name, "chapter_name": chapter.name} for m in members]
        result, error, buckets = self._dispatch_2280(cmd, treasurer, "POST", assignments=assignments)
        self.assertIsNone(error)
        self.assertEqual(result["data"]["success_count"], 3, result)  # every item really ran
        self.assertTicksOnly(cmd, buckets)

        staff = self._user_with_profile_2280("Verenigingen Staff")
        _, error, _ = self._dispatch_2280(cmd, staff, "POST", assignments=assignments)
        self.assertIsInstance(error, frappe.PermissionError)

    # ------------------------------------------------------------------ #
    # fix_stuck_dues_schedule / payment retry
    # ------------------------------------------------------------------ #
    def test_fix_stuck_schedule_ticks_one_bucket_and_audits_once(self):
        treasurer = self._user_with_profile_2280("Verenigingen Treasurer")
        member = self.create_test_member(first_name="Stuck", last_name="Schedule", status="Active")
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = self.create_test_membership_type().name
        membership.start_date = frappe.utils.today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self.track_doc("Membership", membership.name)
        # submitting a Membership creates the member's Active dues schedule
        schedule = frappe._dict(
            name=frappe.db.get_value("Membership Dues Schedule", {"member": member.name, "is_template": 0, "status": "Active"}, "name")
        )
        self.assertTrue(schedule.name, "the membership created no dues schedule to fix")
        cmd = "verenigingen.api.fix_stuck_dues_schedule.fix_stuck_schedule"
        audited_before = self._audit_counts_2280()
        result, error, buckets = self._dispatch_2280(cmd, treasurer, "POST", schedule_name=schedule.name)
        self.assertIsNone(error)
        self.assertIn("success", result)  # the fix may report "no issues"; either way the call really ran
        self.assertTicksOnly(cmd, buckets)
        self.assertEqual(
            dict(self._audit_counts_2280() - audited_before), {"fix_stuck_schedule": 1}
        )

        staff = self._user_with_profile_2280("Verenigingen Staff")  # control: no CRITICAL needed, HIGH is
        _, error, _ = self._dispatch_2280(cmd, staff, "POST", schedule_name=schedule.name)
        self.assertIsNone(error)
        member_only = self._user_with_profile_2280("Verenigingen Member")
        _, error, _ = self._dispatch_2280(cmd, member_only, "POST", schedule_name=schedule.name)
        self.assertIsInstance(error, frappe.PermissionError)

    def test_retry_failed_payment_ticks_one_bucket_and_schedules_the_retry(self):
        member = self.create_test_member(first_name="Retry", last_name="Payment", status="Active")
        invoice = self.create_test_sales_invoice(member=member.name)
        cmd = PAY + "retry_failed_payment"
        audited_before = self._audit_counts_2280()
        result, error, buckets = self._dispatch_2280(cmd, "Administrator", "POST", invoice_id=invoice.name)
        self.assertIsNone(error)
        self.assertTrue(result["success"], result)  # a retry really was scheduled
        self.assertTrue(frappe.db.exists("SEPA Payment Retry", {"invoice": invoice.name}))
        self.assertTicksOnly(cmd, buckets)
        self.assertEqual(dict(self._audit_counts_2280() - audited_before), {"retry_failed_payment": 1})

        # control: the endpoint's own gate still applies (a LOW-only caller is refused before the body)
        member_only = self._user_with_profile_2280("Verenigingen Member")
        _, error, _ = self._dispatch_2280(cmd, member_only, "POST", invoice_id=invoice.name)
        self.assertIsInstance(error, frappe.PermissionError)

    def test_every_split_endpoint_still_refuses_a_caller_below_its_level(self):
        """Control for the whole change: the undecorated bodies are reachable only through the
        endpoints, whose own gate still refuses a LOW-only caller."""
        member_only = self._user_with_profile_2280("Verenigingen Member")
        self._member_for_user_2280(member_only)
        for cmd in (
            DUES + "get_workflow_status",
            PAY + "get_dashboard_data",
            PAY + "export_payment_history_csv",
            PAY + "export_all_financial_data",
        ):
            with self.subTest(endpoint=cmd):
                _, error, buckets = self._dispatch_2280(cmd, member_only, "POST")
                self.assertIsInstance(error, frappe.PermissionError)
                self.assertEqual(buckets, {}, "a refused caller must not tick any bucket")
