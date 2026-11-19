# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""#2280 (sweep of #352): an api/ endpoint that called ANOTHER security-decorated endpoint ran the
whole decorator stack twice: a second rate-limit bucket, a second audit row, and a second
authorisation + HTTP-method check that could answer differently from the endpoint's own.

Every test dispatches through ``frappe.handler.execute_cmd`` (the real whitelist + HTTP-method gate)
as a real user, with the in_test bypass of the rate limiter lifted, and reads the LIVE redis
counters back: an endpoint must tick exactly its own bucket, whatever decorated code it reaches.
"""

from unittest.mock import MagicMock, patch

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

    def _user_with_bare_role_2280(self, role):
        """A user holding the ROLE only, no role profile (authorization rule 5: capped at MEDIUM)."""
        email = f"p2280-{frappe.generate_hash(length=8)}@example.com"
        self.create_test_user(email, roles=[role])
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
    def test_check_member_dues_status_keeps_the_critical_post_only_access_it_effectively_had(self):
        """#2280 ruling: the endpoint lists every member needing an invoice (id + full name), and on
        develop only CRITICAL callers on POST got through (its nested call to the CRITICAL, POST-only
        calculate_cutoff_date_for_period refused the rest). The endpoint now enforces that itself, once,
        and ticks only its own bucket."""
        cmd = DUES + "check_member_dues_status"
        refused = {
            "Auditor profile": self._user_with_profile_2280("Verenigingen Auditor"),
            "Volunteer profile": self._user_with_profile_2280("Verenigingen Volunteer"),
            "Chapter Board Member profile": self._user_with_profile_2280("Verenigingen Chapter Board Member"),
            "Staff profile": self._user_with_profile_2280("Verenigingen Staff"),
            "bare-role Staff": self._user_with_bare_role_2280("Verenigingen Staff"),
            "bare-role System Manager": self._user_with_bare_role_2280("System Manager"),
        }
        for label, user in refused.items():
            with self.subTest(caller=label):
                _, error, _ = self._dispatch_2280(cmd, user, "POST")
                self.assertIsInstance(error, frappe.PermissionError)

        treasurer = self._user_with_profile_2280("Verenigingen Treasurer")  # holds CRITICAL
        result, error, buckets = self._dispatch_2280(cmd, treasurer, "POST")
        self.assertIsNone(error)
        self.assertTrue(result["success"], result)
        self.assertTicksOnly(cmd, buckets)

        _, error, _ = self._dispatch_2280(cmd, treasurer, "GET")  # POST-only, as on develop
        self.assertIsInstance(error, frappe.PermissionError)
        # the declaration says so too (it used to advertise GET and POST)
        endpoint = frappe.get_attr(cmd)
        self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[endpoint], ["POST"])

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

    def test_get_next_payment_for_another_member_still_needs_a_real_high_grant(self):
        """Own record: MEDIUM is enough. Another member's id: a real HIGH grant (a role PROFILE), as
        get_payment_schedule's gate required on develop; a bare role is capped at MEDIUM. The
        cross-member read by a HIGH holder still writes the HIGH audit row."""
        cmd = PAY + "get_next_payment"
        other = self.create_test_member(first_name="Other", last_name="Member", status="Active")

        bare_staff = self._user_with_bare_role_2280("Verenigingen Staff")
        self._member_for_user_2280(bare_staff)
        result, error, _ = self._dispatch_2280(cmd, bare_staff, "GET", member=other.name)
        self.assertIsNone(error)
        self.assertFalse(result["success"], "a bare-role caller read another member's next payment")
        self.assertIn("Access denied", result["error"]["message"])
        result, error, _ = self._dispatch_2280(cmd, bare_staff, "GET")  # own record: MEDIUM
        self.assertTrue(result["success"], result)

        for profile in ("Verenigingen Staff", "Verenigingen Treasurer"):
            with self.subTest(profile=profile):
                holder = self._user_with_profile_2280(profile)
                self._member_for_user_2280(holder)
                audited_before = self._audit_counts_2280()
                result, error, _ = self._dispatch_2280(cmd, holder, "GET", member=other.name)
                self.assertIsNone(error)
                self.assertTrue(result["success"], result)
                self.assertEqual(
                    dict(self._audit_counts_2280() - audited_before), {"get_payment_schedule": 1}
                )
                result, _, buckets = self._dispatch_2280(cmd, holder, "GET")  # own record
                self.assertTrue(result["success"], result)
                self.assertTicksOnly(cmd, buckets)

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

    def test_retry_failed_payment_body_still_refuses_a_critical_non_owner_without_write(self):
        """The body's own check (Sales Invoice write or ownership) is independent of the decorator:
        a CRITICAL caller who may not write Sales Invoices and does not own the invoice is refused,
        and nothing is scheduled."""
        member = self.create_test_member(first_name="Retry", last_name="Owner", status="Active")
        invoice = self.create_test_sales_invoice(member=member.name)
        cmd = PAY + "retry_failed_payment"
        outsider = self._user_with_profile_2280("Verenigingen National Board Member")  # holds CRITICAL
        with self.as_user(outsider):
            self.assertFalse(frappe.has_permission("Sales Invoice", "write"))  # precondition
        result, error, buckets = self._dispatch_2280(cmd, outsider, "POST", invoice_id=invoice.name)
        self.assertIsNone(error, "the CRITICAL gate must have passed so the body check is what refuses")
        self.assertFalse(result["success"], result)
        self.assertIn("permission", result["error"]["message"])
        self.assertFalse(frappe.db.exists("SEPA Payment Retry", {"invoice": invoice.name}))
        self.assertTicksOnly(cmd, buckets)

    # ------------------------------------------------------------------ #
    # F2 (#352 N1 class): a failure the caller absorbed was audited only by the nested endpoint
    # ------------------------------------------------------------------ #
    @staticmethod
    def _audit_rows_2280():
        """Counter of 'function:level:event_type' over the API Audit Log (the real rows)."""
        import json
        from collections import Counter

        rows = frappe.get_all("API Audit Log", fields=["event_type", "details"], limit_page_length=0)
        out = Counter()
        for r in rows:
            d = json.loads(r.details or "{}")
            out[f"{d.get('function')}:{d.get('security_level')}:{r.event_type}"] += 1
        return out

    def _new_audit_rows_2280(self, before):
        return dict(self._audit_rows_2280() - before)

    def test_a_refused_dashboard_approval_is_audited_as_failed(self):
        """quick_approve_application swallows the failure (handle_api_error), so its own row says ok;
        before #2280 the nested approve_application audited the refusal as api_call_failed."""
        cmd = "verenigingen.api.chapter_dashboard_api.quick_approve_application"
        before = self._audit_rows_2280()
        result, error, _ = self._dispatch_2280(
            cmd, "Administrator", "POST", application_name="NOSUCH-APPLICATION-2280"
        )
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)  # control: the approval really was refused
        self.assertEqual(
            self._new_audit_rows_2280(before).get("quick_approve_application:high:api_call_failed"), 1
        )

    def test_a_failed_manual_retry_is_audited_as_failed(self):
        """retry_failed_payment returns the failure, so its own row says ok; the nested critical
        schedule_retry used to audit the raise as api_call_failed."""
        member = self.create_test_member(first_name="Retry", last_name="Fails", status="Active")
        invoice = self.create_test_sales_invoice(member=member.name)
        cmd = PAY + "retry_failed_payment"
        before = self._audit_rows_2280()
        # Mock justified: fault injection at the manager's DB step; the endpoint's own path is real
        with patch(
            "verenigingen.verenigingen_payments.utils.payment_retry.PaymentRetryManager."
            "get_or_create_retry_record",
            side_effect=RuntimeError("retry store down"),
        ):
            result, error, _ = self._dispatch_2280(cmd, "Administrator", "POST", invoice_id=invoice.name)
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)
        self.assertEqual(self._new_audit_rows_2280(before).get("retry_failed_payment:critical:api_call_failed"), 1)

    def test_a_failed_cutoff_calculation_in_check_member_dues_status_is_audited_as_failed(self):
        """The endpoint reports the failure in its OperationResult; the nested CRITICAL cutoff endpoint
        used to audit the raise."""
        cmd = DUES + "check_member_dues_status"
        treasurer = self._user_with_profile_2280("Verenigingen Treasurer")
        before = self._audit_rows_2280()
        # Mock justified: fault injection at the service the cutoff comes from
        with patch(
            "verenigingen.services.billing.bulk_invoice_generation_service."
            "BulkInvoiceGenerationService.calculate_cutoff_date",
            side_effect=RuntimeError("settings unreadable"),
        ):
            result, error, _ = self._dispatch_2280(cmd, treasurer, "POST")
        self.assertIsNone(error)
        self.assertFalse(result["success"], result)
        self.assertEqual(
            self._new_audit_rows_2280(before).get("check_member_dues_status:critical:api_call_failed"), 1
        )

    def test_a_failed_diagnosis_in_fix_stuck_schedule_is_audited_once_as_failed(self):
        """fix_stuck_schedule re-raises, so its own decorator audits the failure: exactly one
        api_call_failed row under its name, and the call still raises."""
        member = self.create_test_member(first_name="Diag", last_name="Fails", status="Active")
        membership = frappe.new_doc("Membership")
        membership.member = member.name
        membership.membership_type = self.create_test_membership_type().name
        membership.start_date = frappe.utils.today()
        membership.status = "Active"
        membership.save()
        membership.submit()
        self.track_doc("Membership", membership.name)
        schedule_name = frappe.db.get_value(
            "Membership Dues Schedule", {"member": member.name, "is_template": 0, "status": "Active"}, "name"
        )
        self.assertTrue(schedule_name)
        cmd = "verenigingen.api.fix_stuck_dues_schedule.fix_stuck_schedule"
        real_get_doc = frappe.get_doc

        def member_lookup_fails(doctype, *a, **kw):
            if doctype == "Member":
                raise RuntimeError("member store down")
            return real_get_doc(doctype, *a, **kw)

        before = self._audit_rows_2280()
        # Mock justified: fault injection for the Member read inside the diagnosis
        with patch("frappe.get_doc", side_effect=member_lookup_fails):
            _, error, _ = self._dispatch_2280(cmd, "Administrator", "POST", schedule_name=schedule_name)
        self.assertIsInstance(error, RuntimeError)
        failed = {k: v for k, v in self._new_audit_rows_2280(before).items() if "api_call_failed" in k}
        self.assertEqual(sum(failed.values()), 1, failed)
        self.assertIn("fix_stuck_schedule:high:api_call_failed", failed)

    def test_a_deadlock_in_a_dashboard_approval_is_audited_once(self):
        """A non-resumable DB error escapes handle_api_error, so the decorator audits the call: the
        endpoint's own emit must not add a second api_call_failed row for the same failure."""
        from frappe.exceptions import QueryDeadlockError

        cmd = "verenigingen.api.chapter_dashboard_api.quick_approve_application"
        before = self._audit_rows_2280()
        # Mock justified: fault injection, a deadlock cannot be provoked on demand
        with patch(
            "verenigingen.api.membership_application_review._approve_application",
            side_effect=QueryDeadlockError("deadlock"),
        ):
            _, error, _ = self._dispatch_2280(
                cmd, "Administrator", "POST", application_name="NOSUCH-APPLICATION-2280"
            )
        self.assertIsInstance(error, QueryDeadlockError)
        failed = {k: v for k, v in self._new_audit_rows_2280(before).items() if "api_call_failed" in k}
        self.assertEqual(failed, {"quick_approve_application:high:api_call_failed": 1})
