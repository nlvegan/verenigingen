"""#2817: a service handler called with ``raise_error=False`` must not turn 1213/1205 into a value.

#1190 made ``handle_service_error(raise_error=True)`` re-raise a deadlock / lock-wait timeout
(NON_RESUMABLE_DB_ERRORS) as itself, but left ``raise_error=False`` returning the envelope dict
(or the caller's None / failed OperationResult). A caller's ``except NON_RESUMABLE_DB_ERRORS`` then
could still never fire for those sites. The transaction is already gone, so ``raise_error`` cannot
change that: the class propagates whatever it says. Every other error keeps the envelope.

The lock errors are injected at the DRIVER (``Cursor.execute`` raises a real
``OperationalError(1213|1205)`` that frappe translates), below the swallowing handler of each
site. Every test asserts the injection fired, so a path that never reached the statement cannot pass.
"""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.services.billing.coverage_calculator import CoverageCalculator
from verenigingen.services.billing.invoice_generator import InvoiceGenerator
from verenigingen.services.communication.email_service import EmailService
from verenigingen.services.customer_handling_service import CustomerHandlingService
from verenigingen.services.document.document_portal_service import DocumentPortalService
from verenigingen.services.member.core.member_membership_service import MemberMembershipService
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.service_error_handler import handle_service_error
from verenigingen.utils.transaction_errors import NON_RESUMABLE_DB_ERRORS

DRIVER_LOCK_ERRORS = ((1213, frappe.QueryDeadlockError), (1205, frappe.QueryTimeoutError))

class TestServiceHandlersRaiseErrorFalseLockErrors2817(EnhancedTestCase):
    def _lock_fault_at_driver_2817(self, code, verb, fragment, hits, also=None):
        """Cursor.execute raises a real driver OperationalError(code) on *verb* statements of *fragment*."""
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if (
                isinstance(query, str)
                and query.lstrip().upper().startswith(verb)
                and fragment in query
                and (also is None or also(args))
            ):
                hits.append(query)
                raise frappe.db.OperationalError(code, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute)

    def _assert_lock_error_propagates(self, call, code, error, verb, fragment, also=None):
        hits = []
        with self._lock_fault_at_driver_2817(code, verb, fragment, hits, also=also):
            with self.assertRaises(error):
                call()
        self.assertTrue(hits, f"the {code} injection never fired on {verb} {fragment}")

    # -- the shared handler -------------------------------------------------------------------

    def test_handle_service_error_raises_a_lock_error_even_when_raise_error_is_false(self):
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                err = error(f"({code}, 'injected')")
                with self.assertRaises(NON_RESUMABLE_DB_ERRORS) as ctx:
                    handle_service_error(err, "svc_2817", "op", raise_error=False)
                self.assertIs(ctx.exception, err)

    def test_control_an_ordinary_error_still_returns_the_envelope_when_raise_error_is_false(self):
        self.expectErrorLog("svc_2817_ctrl Error")
        boom = ValueError("ordinary")
        result = handle_service_error(boom, "svc_2817_ctrl", "op", raise_error=False)
        self.assertEqual(result["success"], False)
        self.assertEqual(result["error"], "ordinary")

    def test_a_caller_with_a_recorded_reason_can_opt_out_and_keep_the_envelope(self):
        """EmailService (#2996) opts out for 1205; the opt-out must still return the envelope."""
        self.expectErrorLog("svc_2817_optout Error")
        result = handle_service_error(
            frappe.QueryTimeoutError("(1205, 'injected')"),
            "svc_2817_optout",
            "op",
            raise_error=False,
            propagate_non_resumable=False,
        )
        self.assertEqual(result["success"], False)

    # -- the sites the issue names, each below its own except -----------------------------------

    def test_get_organization_documents_propagates_a_lock_error(self):
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                self._assert_lock_error_propagates(
                    lambda: DocumentPortalService().get_organization_documents("Chapter", "Nowhere"),
                    code,
                    error,
                    "SELECT",
                    "`tabOrganization Document`",
                )

    def test_get_all_accessible_documents_propagates_a_lock_error(self):
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                self._assert_lock_error_propagates(
                    lambda: DocumentPortalService().get_all_accessible_documents("Administrator"),
                    code,
                    error,
                    "SELECT",
                    "`tabOrganization Document`",
                )

    def test_get_upload_context_propagates_a_lock_error(self):
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                self._assert_lock_error_propagates(
                    lambda: DocumentPortalService().get_upload_context("Administrator"),
                    code,
                    error,
                    "SELECT",
                    "`tabMember`",
                )

    def test_ensure_donor_customer_exists_propagates_a_lock_error(self):
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                name = f"Donor 2817 {frappe.generate_hash(length=6)}"
                self._assert_lock_error_propagates(
                    lambda: CustomerHandlingService().ensure_donor_customer_exists(name),
                    code,
                    error,
                    "INSERT",
                    "`tabCustomer`",
                )

    def test_control_ensure_donor_customer_exists_still_returns_an_envelope_for_an_ordinary_error(self):
        self.expectErrorLog("CustomerHandlingService Error")
        hits = []
        with self._lock_fault_at_driver_2817(1048, "INSERT", "`tabCustomer`", hits):
            result = CustomerHandlingService().ensure_donor_customer_exists(
                f"Donor 2817 ctrl {frappe.generate_hash(length=6)}"
            )
        self.assertTrue(hits, "the ordinary-error injection never fired")
        self.assertFalse(result["success"])

    # -- sites that need a member with a membership and a dues schedule -------------------------

    def _monthly_member_with_schedule(self):
        first_of_this_month = getdate(today()).replace(day=1)
        join_date = getdate(add_days(first_of_this_month, -1)).replace(day=3)
        membership_type = self.create_test_membership_type(
            membership_type_name="Lock 2817 Type", amount=10.0, contribution_mode="Fixed Amount"
        )
        member, schedule = self.create_test_member_with_schedule(
            first_name="Lock2817",
            last_name="Member",
            membership_type_name=membership_type.name,
            start_date=join_date,
        )
        schedule.billing_frequency = "Monthly"
        schedule.save()
        return member, schedule, join_date

    def test_get_active_membership_propagates_a_lock_error_from_the_membership_load(self):
        member, _schedule, _join = self._monthly_member_with_schedule()
        membership_name = frappe.db.get_value("Membership", {"member": member.name}, "name")
        self.assertTrue(membership_name)
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                self._assert_lock_error_propagates(
                    lambda: MemberMembershipService().get_active_membership(member.name),
                    code,
                    error,
                    "SELECT",
                    "`tabMembership`",
                    also=lambda args: membership_name in repr(args),
                )

    def test_calculate_next_coverage_period_propagates_a_lock_error(self):
        member, schedule, _join = self._monthly_member_with_schedule()
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                self._assert_lock_error_propagates(
                    lambda: CoverageCalculator(schedule).calculate_next_coverage_period(
                        member, use_sequential=True
                    ),
                    code,
                    error,
                    "SELECT",
                    "`tabMembership`",
                )

    def test_generate_invoice_propagates_a_lock_error_from_the_invoice_write(self):
        member, schedule, join_date = self._monthly_member_with_schedule()
        end = add_days(add_months(join_date, 1), -1)
        for code, error in DRIVER_LOCK_ERRORS:
            with self.subTest(code=code):
                self._assert_lock_error_propagates(
                    lambda: InvoiceGenerator(schedule).generate_invoice(
                        coverage_start=join_date, coverage_end=end, member_doc=member
                    ),
                    code,
                    error,
                    "INSERT",
                    "`tabSales Invoice`",
                )

    def test_control_generate_invoice_still_returns_a_failed_result_for_an_ordinary_error(self):
        self.expectErrorLog("InvoiceGenerator Error")
        member, schedule, join_date = self._monthly_member_with_schedule()
        end = add_days(add_months(join_date, 1), -1)
        hits = []
        with self._lock_fault_at_driver_2817(1048, "INSERT", "`tabSales Invoice`", hits):
            result = InvoiceGenerator(schedule).generate_invoice(
                coverage_start=join_date, coverage_end=end, member_doc=member
            )
        self.assertTrue(hits, "the ordinary-error injection never fired")
        self.assertFalse(result.success)

    # -- EmailService keeps its recorded #2996 choice: 1205 stays a failure result ---------------

    def test_email_service_still_returns_a_failure_result_for_a_lock_timeout(self):
        """#2996: a best-effort send must not abort its caller on 1205 (deadlock still escapes).

        The 1205 is injected inside template RENDERING (a cached template whose Jinja reads
        ``tabTag``). ``_render_template`` re-raises, ``_get_template``/``_get_default_context``/
        ``_send_email_internal`` do not swallow it past that point, so it reaches the OUTER
        ``handle_service_error`` of send_templated_email/send_notification, where the
        ``propagate_non_resumable=False`` opt-out decides its fate. (An injection into a statement
        a helper swallows itself never reaches the opt-out and proves nothing.)
        send_bulk_emails and send_simple_email carry the same clause and are not pinned here.
        """
        self.expectErrorLog("EmailService Error")
        recipient = f"t2817.{frappe.generate_hash(length=8)}@test.invalid"
        reading_template = {
            "subject": "s2817",
            "content": "{{ frappe.db.get_value('Tag', 'no-such-tag-2817', 'name') }}",
        }
        for name, template_name, call_name in (
            ("send_templated_email", "T2817 render", "send_templated_email"),
            ("send_notification", "membership_application_approved", "send_notification"),
        ):
            with self.subTest(method=name):
                service = EmailService()
                service.template_cache.set(template_name, reading_template)
                if call_name == "send_templated_email":
                    call = lambda: service.send_templated_email(template_name, [recipient], {})
                else:
                    call = lambda: service.send_notification("member_approval", [recipient], {})
                hits = []
                with patch.object(EmailService, "_has_active_email_account", return_value=True):
                    with self._lock_fault_at_driver_2817(1205, "SELECT", "`tabTag`", hits):
                        result = call()
                self.assertTrue(hits, f"{name}: the 1205 injection never fired")
                self.assertFalse(result.success)
