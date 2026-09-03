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
