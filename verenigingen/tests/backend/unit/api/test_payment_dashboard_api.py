"""
Real-DB integration coverage for verenigingen/api/payment_dashboard.py.

Exercises the payment-dashboard endpoints against genuine Member / SEPA Mandate /
Membership Dues Schedule / Sales Invoice / Payment Entry fixtures created via the
Enhanced Test Factory. NO business-logic mocking: expected values are derived from
the data each test creates.

The @*_api security decorators serialize each OperationResult into a plain dict for
in-process calls, so every assertion targets the dict shape the caller receives
(``result["success"]`` / ``result["data"]`` / ``result["error"]["message"]``), not
the internal OperationResult object.
"""

import frappe
from frappe.utils import add_days, add_months, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase

from verenigingen.api.payment_dashboard import (
    download_payment_receipt,
    export_all_financial_data,
    export_payment_history_csv,
    get_dashboard_data,
    get_mandate_history,
    get_member_from_user,
    get_next_payment,
    get_payment_history,
    get_payment_method,
    get_payment_schedule,
    retry_failed_payment,
    save_notification_settings,
    validate_member_exists,
)


class TestPaymentDashboardAPI(EnhancedTestCase):
    """Genuine business-logic assertions for the payment dashboard API."""

    def setUp(self):
        super().setUp()
        # get_member_from_user is wrapped in @cache_with_ttl(300) whose cache lives
        # in a module-level closure dict that persists across tests in the same
        # process. The cache key for a no-arg call (user=None) is constant, so a
        # value resolved under one session leaks into later tests/users. Clear it so
        # each test resolves freshly.
        self._clear_member_user_cache()
        self.member = self.create_test_member(
            first_name="PayDash",
            last_name="Member",
            status="Active",
        )

    @staticmethod
    def _clear_member_user_cache():
        for cell in (get_member_from_user.__closure__ or ()):
            contents = cell.cell_contents
            if isinstance(contents, dict):
                contents.clear()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _ensure_customer(self):
        """Create + link an ERPNext Customer for the member, returning its name."""
        member_doc = frappe.get_doc("Member", self.member.name)
        if not member_doc.customer:
            member_doc.create_customer()
            member_doc.reload()
        return member_doc.customer

    @staticmethod
    def _op_result_shape(result):
        """(success, error message, data) for an OperationResult dict, dropping
        its `timestamp` field -- two calls a millisecond apart are otherwise
        never equal, which is noise unrelated to what #1314's oracle tests
        compare (whether the RESPONSE distinguishes "doesn't exist" from
        "exists but isn't yours")."""
        return (
            result.get("success"),
            (result.get("error") or {}).get("message"),
            result.get("data"),
        )

    # ------------------------------------------------------------------
    # validate_member_exists / get_member_from_user
    # ------------------------------------------------------------------
    def test_validate_member_exists_returns_member_id(self):
        # Passing a real member id round-trips through get_member_from_user.
        resolved = validate_member_exists(self.member.name)
        self.assertEqual(resolved, self.member.name)

    def test_validate_member_exists_raises_for_unknown(self):
        with self.assertRaises(frappe.DoesNotExistError):
            validate_member_exists("MEMBER-DOES-NOT-EXIST-XYZ")

    def test_get_member_from_user_guest_returns_none(self):
        with self.set_user("Guest"):
            self.assertIsNone(get_member_from_user())

    def test_get_member_from_user_resolves_by_user_link(self):
        # Link a real User to the member, then resolve from that user's session.
        user_email = f"paydash.user.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "PayDash",
                    "last_name": "Linked",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        frappe.db.set_value("Member", self.member.name, "user", user_email)
        frappe.db.commit()
        # bust the cache_with_ttl memoization keyed on the user argument
        resolved = get_member_from_user(user_email)
        self.assertEqual(resolved, self.member.name)

    # ------------------------------------------------------------------
    # get_dashboard_data
    # ------------------------------------------------------------------
    def test_get_dashboard_data_no_customer(self):
        # Member with no linked customer: counters are zero, no failed payments.
        result = get_dashboard_data(self.member.name)
        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        self.assertEqual(data["total_paid_year"], 0.0)
        self.assertEqual(data["payment_count"], 0)
        self.assertFalse(data["has_failed_payments"])
        self.assertFalse(data["mandate_expiring_soon"])

    def test_get_dashboard_data_member_not_found(self):
        result = get_dashboard_data("MEMBER-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("not found", (result["error"]["message"] or "").lower())

    def test_get_dashboard_data_mandate_expiring_soon(self):
        # An active mandate expiring inside 30 days flips mandate_expiring_soon True.
        self.create_test_sepa_mandate(
            member=self.member.name,
            status="Active",
            expiry_date=add_days(today(), 10),
        )
        result = get_dashboard_data(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["data"]["mandate_expiring_soon"])

    def test_get_dashboard_data_mandate_far_expiry_not_flagged(self):
        # An active mandate expiring far in the future is NOT flagged.
        self.create_test_sepa_mandate(
            member=self.member.name,
            status="Active",
            expiry_date=add_days(today(), 200),
        )
        result = get_dashboard_data(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertFalse(result["data"]["mandate_expiring_soon"])

    # ------------------------------------------------------------------
    # get_payment_method
    # ------------------------------------------------------------------
    def test_get_payment_method_no_mandate(self):
        result = get_payment_method(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertFalse(result["data"]["has_active_mandate"])

    def test_get_payment_method_with_active_mandate(self):
        mandate = self.create_test_sepa_mandate(
            member=self.member.name,
            status="Active",
        )
        result = get_payment_method(self.member.name)
        self.assertTrue(result["success"], msg=result)
        data = result["data"]
        self.assertTrue(data["has_active_mandate"])
        self.assertEqual(data["mandate"]["mandate_id"], mandate.mandate_id)
        self.assertEqual(data["mandate"]["status"], "Active")
        # IBAN is returned formatted (grouped in 4s) -> strip whitespace to compare
        # against the stored (unformatted) value.
        self.assertEqual(
            data["mandate"]["iban"].replace(" ", ""),
            mandate.iban.replace(" ", ""),
        )

    def test_get_payment_method_member_not_found(self):
        result = get_payment_method("MEMBER-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result["success"])
        self.assertIn("not found", (result["error"]["message"] or "").lower())

    # ------------------------------------------------------------------
    # get_mandate_history
    # ------------------------------------------------------------------
    def test_get_mandate_history_empty(self):
        result = get_mandate_history(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"], [])

    def test_get_mandate_history_enriches_records(self):
        mandate = self.create_test_sepa_mandate(member=self.member.name, status="Active")
        result = get_mandate_history(self.member.name)
        self.assertTrue(result["success"], msg=result)
        rows = result["data"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["mandate_id"], mandate.mandate_id)
        # Enrichment fields added by the endpoint.
        self.assertIn("iban_formatted", row)
        self.assertIn("bank_name", row)
        self.assertTrue(row["is_active"])

    def test_get_mandate_history_member_not_found(self):
        result = get_mandate_history("MEMBER-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result["success"])

    # ------------------------------------------------------------------
    # get_payment_schedule / get_next_payment
    # ------------------------------------------------------------------
    def test_get_payment_schedule_no_active_schedule(self):
        result = get_payment_schedule(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"], [])

    def _active_schedule(self):
        """Return the member's single active (non-template) dues schedule doc.

        A Membership's after_insert auto-creates one active schedule; the factory
        reuses it rather than inserting a second (production allows only one active
        schedule per member). Expected values are therefore derived from the live
        schedule the endpoint actually reads, not from arbitrary factory args.
        """
        name = frappe.db.get_value(
            "Membership Dues Schedule",
            {"member": self.member.name, "is_template": 0, "status": "Active"},
            "name",
        )
        self.assertIsNotNone(name, "Expected an active dues schedule for the member")
        return frappe.get_doc("Membership Dues Schedule", name)

    def test_get_payment_schedule_monthly_generates_future_entries(self):
        # Membership is required so an active dues schedule exists.
        self.create_test_membership(member_name=self.member.name)
        next_date = add_days(today(), 5)
        sched = self._active_schedule()
        sched.next_invoice_date = next_date
        sched.last_invoice_date = None
        sched.save()

        result = get_payment_schedule(self.member.name)
        self.assertTrue(result["success"], msg=result)
        schedule = result["data"]
        self.assertGreater(len(schedule), 0)
        first = schedule[0]
        # Amount is read straight from the schedule's dues_rate.
        self.assertEqual(first["amount"], frappe.utils.flt(sched.dues_rate, 2))
        self.assertEqual(first["status"], "Scheduled")
        # First scheduled date is the next_invoice_date (in the future).
        self.assertEqual(getdate(first["date"]), getdate(next_date))
        # All entries must be today or later (past dates are skipped).
        for entry in schedule:
            self.assertGreaterEqual(getdate(entry["date"]), getdate(today()))

    def test_get_payment_schedule_stops_at_last_invoice_date(self):
        self.create_test_membership(member_name=self.member.name)
        next_date = add_days(today(), 5)
        sched = self._active_schedule()
        sched.next_invoice_date = next_date
        # last_invoice_date caps generation: no entry may exceed it.
        last_allowed_date = add_months(next_date, 1)
        sched.last_invoice_date = last_allowed_date
        sched.save()

        result = get_payment_schedule(self.member.name)
        self.assertTrue(result["success"], msg=result)
        schedule = result["data"]
        last_allowed = getdate(last_allowed_date)
        for entry in schedule:
            self.assertLessEqual(getdate(entry["date"]), last_allowed)

    def test_get_next_payment_returns_first_schedule_entry(self):
        # Regression guard: get_next_payment calls get_payment_schedule (also a
        # @*_api endpoint) which returns a serialized dict in-process. Before the
        # fix it accessed .success/.data on that dict and always errored out.
        self.create_test_membership(member_name=self.member.name)
        next_date = add_days(today(), 7)
        sched = self._active_schedule()
        sched.next_invoice_date = next_date
        sched.last_invoice_date = None
        sched.save()

        schedule_result = get_payment_schedule(self.member.name)
        expected_first = schedule_result["data"][0]
        result = get_next_payment(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertIsNotNone(result["data"])
        self.assertEqual(result["data"]["date"], expected_first["date"])
        self.assertEqual(result["data"]["amount"], expected_first["amount"])
        self.assertEqual(result["data"]["description"], expected_first["description"])

    def test_get_next_payment_none_when_no_schedule(self):
        result = get_next_payment(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertIsNone(result["data"])

    # ------------------------------------------------------------------
    # get_payment_history
    # ------------------------------------------------------------------
    def test_get_payment_history_no_customer(self):
        result = get_payment_history(self.member.name)
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"], [])

    def test_get_payment_history_with_invoice(self):
        customer = self._ensure_customer()
        invoice = self.create_test_sales_invoice(customer=customer)
        invoice.submit()
        result = get_payment_history(self.member.name)
        self.assertTrue(result["success"], msg=result)
        history = result["data"]
        ids = [h["id"] for h in history]
        self.assertIn(invoice.name, ids)
        entry = next(h for h in history if h["id"] == invoice.name)
        self.assertEqual(entry["type"], "invoice")
        self.assertEqual(entry["amount"], invoice.grand_total)

    def test_get_payment_history_status_filter(self):
        customer = self._ensure_customer()
        invoice = self.create_test_sales_invoice(customer=customer)
        invoice.submit()
        # Filtering on a status no row has yields an empty list.
        result = get_payment_history(self.member.name, status="NoSuchStatus")
        self.assertTrue(result["success"], msg=result)
        self.assertEqual(result["data"], [])

    def test_get_payment_history_year_filter_excludes_other_years(self):
        customer = self._ensure_customer()
        invoice = self.create_test_sales_invoice(customer=customer)
        invoice.submit()
        # Filter to a year far in the past -> current invoice excluded.
        result = get_payment_history(self.member.name, year=2000)
        self.assertTrue(result["success"], msg=result)
        self.assertNotIn(invoice.name, [h["id"] for h in result["data"]])

    def test_get_payment_history_member_not_found(self):
        result = get_payment_history("MEMBER-DOES-NOT-EXIST-XYZ")
        self.assertFalse(result["success"])

    # ------------------------------------------------------------------
    # export_payment_history_csv
    # ------------------------------------------------------------------
    def _admin_user_linked_to_member(self):
        """Create a real User with admin privileges linked to self.member.

        export_payment_history_csv is @high_security_api, so the acting user must
        hold an admin role PROFILE to clear the decorator AND be linked to the
        member so get_member_from_user() resolves the record. After the audit #2
        Rule-5 cap a bare role tops out at MEDIUM, so the same-named role profile
        ("Verenigingen Administrator") is required to reach HIGH.
        """
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        user_email = f"csv.admin.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Csv",
                    "last_name": "Admin",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Administrator"}, {"role": "System Manager"}],
                }
            ).insert()
        grant_matching_role_profiles(user_email, "Verenigingen Administrator")
        frappe.db.set_value("Member", self.member.name, "user", user_email)
        frappe.db.commit()
        return user_email

    def test_export_payment_history_csv_sets_response_file(self):
        user_email = self._admin_user_linked_to_member()
        with self.set_user(user_email):
            result = export_payment_history_csv()
        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["data"]["filename"].endswith(".csv"))
        self.assertEqual(frappe.local.response.type, "csv")
        # The CSV always carries the header row even with no payment history.
        self.assertIn("Date", frappe.local.response.filecontent)

    def test_export_payment_history_csv_includes_invoice_row(self):
        # Regression guard for the dict-vs-OperationResult unwrap in the CSV path.
        customer = self._ensure_customer()
        invoice = self.create_test_sales_invoice(customer=customer)
        invoice.submit()
        user_email = self._admin_user_linked_to_member()
        with self.set_user(user_email):
            result = export_payment_history_csv()
        self.assertTrue(result["success"], msg=result)
        self.assertIn(invoice.name, frappe.local.response.filecontent)

    # ------------------------------------------------------------------
    # export_all_financial_data (#430 -- verenigingen.api.payment_dashboard had
    # never defined this; templates/pages/payment_dashboard.html's "Export All
    # Data" button called a method that did not exist)
    # ------------------------------------------------------------------
    def test_export_all_financial_data_sets_response_file(self):
        # Both section headers are unconditional writer.writerow() calls, so
        # asserting only their presence would pass even with zero rows in either
        # loop -- seed a real invoice and mandate so the row-writing code paths
        # actually run.
        customer = self._ensure_customer()
        invoice = self.create_test_sales_invoice(customer=customer)
        invoice.submit()
        mandate = self.create_test_sepa_mandate(member=self.member.name, status="Active")

        user_email = self._admin_user_linked_to_member()
        with self.set_user(user_email):
            result = export_all_financial_data()

        self.assertTrue(result["success"], msg=result)
        self.assertTrue(result["data"]["filename"].endswith(".csv"))
        self.assertEqual(frappe.local.response.type, "csv")
        self.assertIn("Payment History", frappe.local.response.filecontent)
        self.assertIn("SEPA Mandate History", frappe.local.response.filecontent)
        self.assertIn(invoice.name, frappe.local.response.filecontent)
        self.assertIn(mandate.mandate_id, frappe.local.response.filecontent)

    def test_export_all_financial_data_no_member_for_user(self):
        with self.set_user("Administrator"):
            self._clear_member_user_cache()
            result = export_all_financial_data()
        self.assertFalse(result["success"], msg=result)
        self.assertEqual(result["error"]["message"], "No member found for current user")

    # ------------------------------------------------------------------
    # save_notification_settings (#430 -- also never defined; the dashboard's
    # "Save Settings" button called it directly)
    # ------------------------------------------------------------------
    def test_save_notification_settings_persists_only_known_keys(self):
        user_email = self._admin_user_linked_to_member()
        with self.set_user(user_email):
            result = save_notification_settings(
                {
                    "email_notifications": True,
                    "reminder_notifications": False,
                    "not_a_real_setting": "should be dropped",
                }
            )
        self.assertTrue(result["success"], msg=result)
        stored = frappe.parse_json(
            frappe.db.get_value("Member", self.member.name, "payment_notification_preferences")
        )
        self.assertEqual(
            stored,
            # cbool (not bool()) normalizes to 0/1 -- see save_notification_settings.
            {"email_notifications": 1, "reminder_notifications": 0},
        )

    def test_save_notification_settings_ignores_member_override(self):
        """A caller cannot use the ``member`` frontend sends to edit someone else's row.

        The frontend always sends a ``member`` arg alongside ``settings``
        (templates/pages/payment_dashboard.html:1720-1721); frappe.call() drops
        any kwarg the target function doesn't declare, so this pins that
        save_notification_settings never grows a ``member`` parameter that
        would let a caller edit someone else's preferences.
        """
        other_member = self.create_test_member(first_name="Other", last_name="PayDash")
        user_email = self._admin_user_linked_to_member()
        with self.set_user(user_email):
            result = frappe.call(
                save_notification_settings,
                settings={"email_notifications": True},
                member=other_member.name,
            )
        self.assertTrue(result["success"], msg=result)
        self.assertIsNone(
            frappe.db.get_value("Member", other_member.name, "payment_notification_preferences")
        )
        self.assertIsNotNone(
            frappe.db.get_value("Member", self.member.name, "payment_notification_preferences")
        )

    # ------------------------------------------------------------------
    # retry_failed_payment
    # ------------------------------------------------------------------
    def test_retry_failed_payment_invoice_not_found(self):
        result = retry_failed_payment("ACC-SINV-DOES-NOT-EXIST")
        self.assertFalse(result["success"])
        self.assertIn("not found", (result["error"]["message"] or "").lower())

    # ------------------------------------------------------------------
    # cross-member ownership (#957-adjacent): a caller-supplied `member` must
    # be the caller's own record unless the caller holds an admin role.
    # ------------------------------------------------------------------
    def _board_member_user(self):
        """A non-admin user whose Role Profile clears the HIGH security level.

        "Verenigingen Chapter Board Member" is a real, common elected role
        that satisfies Rule 4 of the authorization policy (HIGH access via
        role profile), but holds none of Roles.ADMIN_ROLES -- see
        role_profile_helper.py's docstring for the Rule-5 cap this works
        around. That security-LEVEL check is orthogonal to member OWNERSHIP,
        which is what this test targets.
        """
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        user_email = f"board.probe.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "Board",
                    "last_name": "Probe",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        grant_matching_role_profiles(user_email, "Verenigingen Chapter Board Member")

        attacker_member = self.create_test_member(first_name="Board", last_name="Probe", status="Active")
        frappe.db.set_value("Member", attacker_member.name, "user", user_email)

        from verenigingen.utils.constants import Roles

        self.assertFalse(
            set(frappe.get_roles(user_email)) & Roles.ADMIN_ROLES,
            "test setup: attacker must NOT hold an admin role",
        )
        return user_email, attacker_member.name

    def test_get_dashboard_data_refuses_cross_member_for_non_admin_board_role(self):
        user_email, _attacker_member = self._board_member_user()
        with self.set_user(user_email):
            result = get_dashboard_data(self.member.name)
        self.assertFalse(result["success"], msg=result)
        self.assertIn("permission", (result["error"]["message"] or "").lower())

    def test_get_dashboard_data_allows_own_member_for_non_admin_board_role(self):
        # Same non-admin board-profile user, reading their OWN dashboard, must
        # still succeed -- the ownership fix must not break self-service.
        user_email, attacker_member = self._board_member_user()
        with self.set_user(user_email):
            result = get_dashboard_data(attacker_member)
        self.assertTrue(result["success"], msg=result)

    def test_get_next_payment_refuses_cross_member_for_non_admin_board_role(self):
        # get_next_payment resolves `member` itself rather than going through
        # validate_member_exists -- a separate code path, needs its own test.
        user_email, _attacker_member = self._board_member_user()
        with self.set_user(user_email):
            result = get_next_payment(self.member.name)
        self.assertFalse(result["success"], msg=result)
        self.assertIn("permission", (result["error"]["message"] or "").lower())

    # ------------------------------------------------------------------
    # #1314: existence oracle. get_doc-before-permission-check let an
    # unauthorized caller tell "id doesn't exist" from "id exists but isn't
    # mine" apart -- for validate_member_exists (used by get_dashboard_data,
    # get_payment_method, get_payment_history, get_mandate_history,
    # get_payment_schedule), get_next_payment (its own code path),
    # retry_failed_payment (Sales Invoice id) and download_payment_receipt
    # (Payment Entry id). Each fix must make BOTH outcomes identical (same
    # exception type/message, or same OperationResult) for an unauthorized
    # caller, while a genuine owner or admin/staff still gets in.
    # ------------------------------------------------------------------

    def test_validate_member_exists_unauthorized_cannot_distinguish_unknown_from_foreign(self):
        """A non-admin board-profile user who is not the target member must get
        the IDENTICAL refusal (exception type AND message) for an unknown member
        id and an existing-but-foreign one -- otherwise the response shape leaks
        whether a Member id exists."""
        user_email, _attacker_member = self._board_member_user()

        def _call(member_id):
            with self.set_user(user_email):
                try:
                    validate_member_exists(member_id)
                    return (None, None)
                except Exception as e:
                    return (type(e), str(e))

        unknown = _call("MEMBER-DOES-NOT-EXIST-XYZ-1314")
        # self.member exists but is not the board-profile probe's own record.
        foreign = _call(self.member.name)

        self.assertEqual(unknown, foreign)
        self.assertIs(unknown[0], frappe.PermissionError)

    def test_get_next_payment_unauthorized_cannot_distinguish_unknown_from_foreign(self):
        """get_next_payment resolves `member` itself (not via validate_member_exists)
        and used to reveal a missing id as a silent success ("No member found for
        current user") while an existing-but-foreign id failed with a permission
        message -- distinguishable outcomes for an unauthorized caller."""
        user_email, _attacker_member = self._board_member_user()

        with self.set_user(user_email):
            unknown = get_next_payment("MEMBER-DOES-NOT-EXIST-XYZ-1314")
            foreign = get_next_payment(self.member.name)

        self.assertEqual(self._op_result_shape(unknown), self._op_result_shape(foreign))
        self.assertFalse(unknown["success"], msg=unknown)
        self.assertIn("permission", (unknown["error"]["message"] or "").lower())

    # ------------------------------------------------------------------
    # retry_failed_payment (Sales Invoice id) -- #1314
    # ------------------------------------------------------------------

    def _national_board_member_user(self):
        """A caller whose Role Profile clears CRITICAL security level but has no
        Sales Invoice write access -- the specific unauthorized shape
        retry_failed_payment's own check (frappe.has_permission("Sales
        Invoice", "write")) cares about.

        Unlike "Verenigingen Chapter Board Member" (HIGH/MEDIUM/LOW only),
        retry_failed_payment is @critical_api (CRITICAL tier), so the probe
        needs a Role Profile from ROLE_PROFILE_SECURITY_MAPPING that reaches
        CRITICAL. Every such profile on this site (checked via `Role
        Profile.roles`) bundles "Verenigingen Staff" -- so, unlike
        _board_member_user()'s probe, this one is NOT usable to test
        validate_member_exists's Roles.ADMIN_ROLES check (it WOULD clear
        that). "Verenigingen National Board Member" is used here because its
        bundle carries no Accounts User/Manager, so
        frappe.has_permission("Sales Invoice", "write") is still False for
        it -- confirmed below -- isolating retry_failed_payment's OWNERSHIP
        branch (is_owner, not has_write) from its security-tier gate.
        """
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        user_email = f"natboard.probe.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "National",
                    "last_name": "BoardProbe",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        grant_matching_role_profiles(user_email, "Verenigingen National Board Member")

        attacker_member = self.create_test_member(
            first_name="National", last_name="BoardProbe", status="Active"
        )
        frappe.db.set_value("Member", attacker_member.name, "user", user_email)

        with self.set_user(user_email):
            self.assertFalse(
                frappe.has_permission("Sales Invoice", "write"),
                "test setup: probe must NOT have Sales Invoice write access",
            )
        return user_email, attacker_member.name

    def test_retry_failed_payment_unauthorized_cannot_distinguish_unknown_from_foreign(self):
        user_email, _attacker_member = self._national_board_member_user()
        victim_invoice = self.create_test_sales_invoice(self.member.name, grand_total=50.0)
        victim_invoice.db_set("member", self.member.name)

        with self.set_user(user_email):
            unknown = retry_failed_payment("ACC-SINV-DOES-NOT-EXIST-1314")
            foreign = retry_failed_payment(victim_invoice.name)

        self.assertEqual(self._op_result_shape(unknown), self._op_result_shape(foreign))
        self.assertFalse(unknown["success"], msg=unknown)
        self.assertIn("permission", (unknown["error"]["message"] or "").lower())

    def test_retry_failed_payment_allows_own_invoice_for_non_admin_board_role(self):
        """Positive control: the ownership branch (no Sales Invoice write, but
        the invoice IS the caller's own) must still let the caller through --
        the fix must not turn is_owner into unreachable dead code."""
        user_email, attacker_member = self._national_board_member_user()
        own_invoice = self.create_test_sales_invoice(attacker_member, grand_total=50.0)
        own_invoice.db_set("member", attacker_member)

        with self.set_user(user_email):
            result = retry_failed_payment(own_invoice.name)

        # Ownership passes; the call proceeds into the real retry-scheduling
        # logic (which may itself succeed or fail depending on SEPA state) --
        # what matters here is that it is NOT refused for lack of permission.
        if not result["success"]:
            self.assertNotIn("permission", (result["error"]["message"] or "").lower())

    def test_retry_failed_payment_admin_gets_clear_not_found(self):
        """Positive control: a caller who DOES hold Sales Invoice write access
        (ambient Administrator session, same convention as
        test_retry_failed_payment_invoice_not_found) must still get a distinct
        "Invoice not found" for a genuinely missing id."""
        result = retry_failed_payment("ACC-SINV-DOES-NOT-EXIST-1314")
        self.assertFalse(result["success"], msg=result)
        self.assertIn("not found", (result["error"]["message"] or "").lower())

    # ------------------------------------------------------------------
    # Regression guard (PR #1335 review): `member` is a custom, OPTIONAL
    # field on Sales Invoice -- measured on veg11: 3009 of 3471 Sales
    # Invoices have it NULL, 1495 of those outstanding. The first version of
    # the #1314 fix used a single `invoice_member is None` check for BOTH
    # "no such invoice" and "a real invoice whose member is blank", so a
    # staff caller (has_write=True, who never needed ownership at all) got a
    # false "Invoice not found" on a real, common-case invoice.
    # ------------------------------------------------------------------

    def test_retry_failed_payment_staff_succeeds_on_null_member_invoice(self):
        """A real invoice with member=NULL must not read as "doesn't exist"
        for a staff caller (ambient Administrator, has Sales Invoice write)."""
        invoice = self.create_test_sales_invoice(self.member.name, grand_total=50.0)
        invoice.db_set("member", None)

        result = retry_failed_payment(invoice.name)

        # The call must reach the real retry-scheduling logic (which may
        # itself succeed or fail on SEPA-state grounds) -- what must NOT
        # happen is the existence/ownership guard misreporting "not found".
        if not result["success"]:
            self.assertNotIn("not found", (result["error"]["message"] or "").lower())

    def test_retry_failed_payment_unauthorized_null_member_matches_unknown_message(self):
        """A null-member invoice must fail CLOSED for a non-staff caller, with
        the IDENTICAL refusal an unknown id gets -- not a distinguishable
        "not found" that would reopen #1314's oracle for the common
        null-member case."""
        user_email, _attacker_member = self._national_board_member_user()
        invoice = self.create_test_sales_invoice(self.member.name, grand_total=50.0)
        invoice.db_set("member", None)

        with self.set_user(user_email):
            null_member = retry_failed_payment(invoice.name)
            unknown = retry_failed_payment("ACC-SINV-DOES-NOT-EXIST-1314-B")

        self.assertEqual(self._op_result_shape(null_member), self._op_result_shape(unknown))
        self.assertFalse(null_member["success"], msg=null_member)
        self.assertIn("permission", (null_member["error"]["message"] or "").lower())

    def test_retry_failed_payment_null_member_does_not_match_caller_with_no_member(self):
        """The is_owner comparison must not let None == None grant access: a
        caller who resolves to no Member record at all must not match a
        null-member invoice."""
        from verenigingen.tests.fixtures.role_profile_helper import grant_matching_role_profiles

        user_email = f"nomember.probe.{self.member.name}@example.com".lower()
        if not frappe.db.exists("User", user_email):
            frappe.get_doc(
                {
                    "doctype": "User",
                    "email": user_email,
                    "first_name": "NoMember",
                    "last_name": "Probe",
                    "send_welcome_email": 0,
                    "roles": [{"role": "Verenigingen Member"}],
                }
            ).insert()
        # Deliberately NOT linked to any Member record -- get_member_from_user()
        # must resolve to None for this user.
        grant_matching_role_profiles(user_email, "Verenigingen National Board Member")

        invoice = self.create_test_sales_invoice(self.member.name, grand_total=50.0)
        invoice.db_set("member", None)

        with self.set_user(user_email):
            self.assertIsNone(
                get_member_from_user(), "test setup: probe must resolve to no Member record"
            )
            result = retry_failed_payment(invoice.name)

        self.assertFalse(result["success"], msg=result)
        self.assertIn("permission", (result["error"]["message"] or "").lower())

    # ------------------------------------------------------------------
    # download_payment_receipt (Payment Entry id) -- #1314
    # ------------------------------------------------------------------

    def test_download_payment_receipt_unauthorized_cannot_distinguish_unknown_from_foreign(self):
        user_email, attacker_member = self._board_member_user()

        victim_customer = self._ensure_customer()
        victim_payment = self.create_test_payment_entry(
            party_type="Customer", party=victim_customer, paid_amount=25.0
        )

        with self.set_user(user_email):
            unknown = download_payment_receipt("ACC-PAY-DOES-NOT-EXIST-1314")
            foreign = download_payment_receipt(victim_payment.name)

        self.assertEqual(self._op_result_shape(unknown), self._op_result_shape(foreign))
        self.assertFalse(unknown["success"], msg=unknown)
        self.assertIn("permission", (unknown["error"]["message"] or "").lower())

    def test_download_payment_receipt_allows_own_payment(self):
        """Positive control: a caller downloading a receipt for a Payment Entry
        that genuinely belongs to them (party == their own Customer) must clear
        the OWNERSHIP check -- the fix must not turn it into unreachable dead
        code. PDF rendering itself (wkhtmltopdf) needs network access this
        sandbox doesn't have, so a non-permission failure past the ownership
        check is not what this test is about; only the ownership branch is
        asserted on."""
        user_email, attacker_member = self._board_member_user()

        # create_customer() is itself @critical_api-gated; "Verenigingen Chapter
        # Board Member" only clears HIGH/MEDIUM/LOW (see
        # _national_board_member_user's docstring), so this setup step runs
        # under the ambient (Administrator) test session, not the probe user.
        attacker_doc = frappe.get_doc("Member", attacker_member)
        attacker_doc.create_customer()
        attacker_doc.reload()
        own_customer = attacker_doc.customer

        own_payment = self.create_test_payment_entry(
            party_type="Customer", party=own_customer, paid_amount=25.0
        )

        with self.set_user(user_email):
            result = download_payment_receipt(own_payment.name)

        if not result["success"]:
            self.assertNotIn("permission", (result["error"]["message"] or "").lower())
