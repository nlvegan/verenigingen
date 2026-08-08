"""
Real-integration tests for ``verenigingen/utils/membership_dues_integration.py``.

This module was only ~9% covered. It contains the dues-schedule lifecycle
helpers that bridge memberships, dues schedules and invoices:

  - ``create_dues_schedule_from_application`` (application-approval path)
  - ``calculate_next_invoice_date`` (frequency arithmetic)
  - ``handle_membership_termination`` (cancel active schedules)
  - ``get_member_billing_status`` (comprehensive billing snapshot)
  - ``_calculate_member_paid_ytd_optimized`` / ``_calculate_member_paid_ytd_python``
  - ``adjust_dues_schedule`` (whitelisted edit endpoint)

The secondary target ``verenigingen/utils/schedule_naming_helper.py``
(``generate_dues_schedule_name``) is exercised through real schedule creation.

All tests build real Members, Memberships, Customers, Sales Invoices and
Membership Dues Schedules and assert real DB state. No business-logic mocking.

Note on invoice/payment lookups: a member's invoices and payments are filed
under the member's linked ERPNext *Customer* (``Member.customer``), not under
the Member name. The billing-status / YTD helpers therefore resolve the
member's customer before querying Sales Invoice / Payment Entry.
"""

import types

import frappe
from frappe.utils import add_months, getdate, today

from verenigingen.tests.utils.base import VereningingenTestCase
from verenigingen.utils import membership_dues_integration as mdi
from verenigingen.utils.schedule_naming_helper import generate_dues_schedule_name


class TestMembershipDuesIntegration(VereningingenTestCase):
    """Exercise the dues-integration helpers end to end."""

    def setUp(self):
        super().setUp()
        self.member = self.create_test_member(
            first_name="Dues",
            last_name="Integration",
            email=f"dues.integration.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )
        self.membership_type = self.create_test_membership_type(
            membership_type_name=f"DuesIntType{frappe.generate_hash(length=6)}",
        )
        # Submitting the membership runs on_submit which creates the member's
        # active membership record (status Active, docstatus 1) that the
        # integration helpers look up.
        self.membership = self.create_test_membership(
            member=self.member.name,
            membership_type=self.membership_type.name,
        )
        self.membership.submit()
        self.membership.reload()

    # ------------------------------------------------------------------ helpers

    def _ensure_customer(self):
        """Ensure the member has a linked ERPNext Customer; return its name.

        The customer's default currency is aligned with the billing company's
        currency. Invoice generation pulls the company from Verenigingen Settings
        and lets ERPNext default the Sales Invoice currency from the customer. On
        an accumulated dev site the customer happens to end up matching, but on a
        fresh CI site the customer defaults to the system currency (e.g. USD)
        while the company's receivable account is EUR, so invoice generation
        fails with "Party Account currency ... and document currency ... should
        be same". Forcing the customer currency to the company currency makes
        these tests deterministic regardless of the site's default currency.
        """
        self.member.reload()
        customer = self.member.customer
        if not customer:
            # create_test_sales_invoice creates and links a Customer when given member=
            self.create_test_sales_invoice(member=self.member.name)
            self.member.reload()
            customer = self.member.customer

        self._align_customer_currency(customer)
        return customer

    def _align_customer_currency(self, customer):
        """Set the customer's default_currency to the billing company's currency."""
        if not customer:
            return
        company = frappe.db.get_single_value("Verenigingen Settings", "company")
        if not company:
            return
        company_currency = frappe.db.get_value("Company", company, "default_currency")
        if not company_currency:
            return
        if frappe.db.get_value("Customer", customer, "default_currency") != company_currency:
            frappe.db.set_value(
                "Customer", customer, "default_currency", company_currency, update_modified=False
            )

    def _active_schedule_for_member(self):
        return frappe.get_all(
            "Membership Dues Schedule",
            filters={"member": self.member.name, "is_template": 0},
            pluck="name",
        )

    # ------------------------------------------------ calculate_next_invoice_date

    def test_calculate_next_invoice_date_annual(self):
        result = mdi.calculate_next_invoice_date("2025-01-15", "Annual")
        self.assertEqual(getdate(result), getdate(add_months("2025-01-15", 12)))

    def test_calculate_next_invoice_date_semi_annual(self):
        result = mdi.calculate_next_invoice_date("2025-01-15", "Semi-Annual")
        self.assertEqual(getdate(result), getdate(add_months("2025-01-15", 6)))

    def test_calculate_next_invoice_date_quarterly(self):
        result = mdi.calculate_next_invoice_date("2025-01-15", "Quarterly")
        self.assertEqual(getdate(result), getdate(add_months("2025-01-15", 3)))

    def test_calculate_next_invoice_date_monthly(self):
        result = mdi.calculate_next_invoice_date("2025-01-15", "Monthly")
        self.assertEqual(getdate(result), getdate(add_months("2025-01-15", 1)))

    def test_calculate_next_invoice_date_unknown_defaults_annual(self):
        result = mdi.calculate_next_invoice_date("2025-01-15", "Fortnightly")
        self.assertEqual(getdate(result), getdate(add_months("2025-01-15", 12)))

    # --------------------------------------- create_dues_schedule_from_application

    def _fake_application(self, **overrides):
        """Build a duck-typed membership application object.

        create_dues_schedule_from_application reads .member, .membership_type,
        .fee_amount, .payment_id and .name. There is no Membership Application
        DocType in this app, so production callers pass an object with these
        attributes; we mirror that with a SimpleNamespace.
        """
        data = {
            "member": self.member.name,
            "membership_type": self.membership_type.name,
            "fee_amount": 42.0,
            "payment_id": None,
            "name": f"APP-{frappe.generate_hash(length=6)}",
        }
        data.update(overrides)
        return types.SimpleNamespace(**data)

    def test_create_dues_schedule_from_application_generates_invoice(self):
        # Remove the schedule the membership.on_submit already created so the
        # application path can create its own (one schedule per member).
        for name in self._active_schedule_for_member():
            frappe.delete_doc("Membership Dues Schedule", name, force=True)
        self._ensure_customer()

        app = self._fake_application(fee_amount=33.0)
        schedule_name, invoice = mdi.create_dues_schedule_from_application(app)

        self.track_doc("Membership Dues Schedule", schedule_name)
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(schedule.member, self.member.name)
        self.assertEqual(float(schedule.dues_rate), 33.0)
        self.assertEqual(schedule.status, "Active")
        self.assertEqual(schedule.billing_frequency, "Annual")
        # No payment_id -> first invoice generated
        self.assertIsNotNone(invoice)
        if invoice:
            self.track_doc("Sales Invoice", invoice.name)

    def test_create_dues_schedule_from_application_prepaid_no_invoice(self):
        for name in self._active_schedule_for_member():
            frappe.delete_doc("Membership Dues Schedule", name, force=True)
        self._ensure_customer()

        app = self._fake_application(payment_id="PAY-123", fee_amount=50.0)
        schedule_name, invoice = mdi.create_dues_schedule_from_application(app)

        self.track_doc("Membership Dues Schedule", schedule_name)
        # Payment already made -> no invoice generated, last_invoice_date set
        self.assertIsNone(invoice)
        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(getdate(schedule.last_invoice_date), getdate(today()))
        self.assertEqual(
            getdate(schedule.next_invoice_date),
            getdate(mdi.calculate_next_invoice_date(today(), "Annual")),
        )
        self.assertIn("Initial payment made", schedule.notes)

    def test_create_dues_schedule_from_application_no_membership_throws(self):
        # A member with no active membership cannot get an application schedule.
        lone = self.create_test_member(
            first_name="Lone",
            last_name="Applicant",
            email=f"lone.applicant.{frappe.generate_hash(length=6)}@test.invalid",
        )
        app = self._fake_application(member=lone.name)
        with self.assertRaises(frappe.exceptions.ValidationError):
            mdi.create_dues_schedule_from_application(app)

    def test_create_dues_schedule_from_application_fallback_to_template_amount(self):
        for name in self._active_schedule_for_member():
            frappe.delete_doc("Membership Dues Schedule", name, force=True)
        self._ensure_customer()

        # No fee_amount on application -> falls back to template suggested_amount.
        app = self._fake_application(fee_amount=0)
        schedule_name, invoice = mdi.create_dues_schedule_from_application(app)
        self.track_doc("Membership Dues Schedule", schedule_name)
        if invoice:
            self.track_doc("Sales Invoice", invoice.name)

        schedule = frappe.get_doc("Membership Dues Schedule", schedule_name)
        # Template default suggested amount is 15.0 (Membership Type after_insert).
        self.assertGreater(float(schedule.dues_rate), 0)

    # ------------------------------------------------- handle_membership_termination

    def test_handle_membership_termination_cancels_active_schedules(self):
        schedules = self._active_schedule_for_member()
        self.assertTrue(schedules, "membership submit should have created a schedule")

        mdi.handle_membership_termination(self.member.name)

        for name in schedules:
            status = frappe.db.get_value("Membership Dues Schedule", name, "status")
            self.assertEqual(status, "Cancelled")
            notes = frappe.db.get_value("Membership Dues Schedule", name, "notes")
            self.assertIn("Cancelled due to membership termination", notes)

    def test_handle_membership_termination_no_active_schedules_noop(self):
        # A fresh member with no schedules: function must not raise.
        other = self.create_test_member(
            first_name="NoSchedule",
            last_name="Member",
            email=f"noschedule.{frappe.generate_hash(length=6)}@test.invalid",
        )
        mdi.handle_membership_termination(other.name, termination_date=today())  # no raise

    # ----------------------------------------------------- get_member_billing_status

    def test_get_member_billing_status_active_schedule(self):
        status = mdi.get_member_billing_status(self.member.name)
        self.assertTrue(status["has_active_schedule"])
        self.assertTrue(status["schedules"])
        self.assertIsNotNone(status["next_invoice_date"])
        self.assertEqual(status["total_paid_ytd"], 0.0)

    def test_get_member_billing_status_counts_pending_invoice(self):
        self._ensure_customer()
        invoice = self.create_test_sales_invoice(member=self.member.name)
        invoice.submit()  # submitted + unpaid -> Overdue/Unpaid
        self.track_doc("Sales Invoice", invoice.name)

        status = mdi.get_member_billing_status(self.member.name)
        pending_names = [row["name"] for row in status["pending_invoices"]]
        self.assertIn(invoice.name, pending_names)

    def test_get_member_billing_status_no_schedule_member(self):
        other = self.create_test_member(
            first_name="Billing",
            last_name="Empty",
            email=f"billing.empty.{frappe.generate_hash(length=6)}@test.invalid",
        )
        status = mdi.get_member_billing_status(other.name)
        self.assertFalse(status["has_active_schedule"])
        self.assertEqual(status["pending_invoices"], [])
        self.assertEqual(status["total_paid_ytd"], 0.0)

    # -------------------------------------------------------- paid YTD calculation

    def test_calculate_paid_ytd_counts_paid_invoice(self):
        customer = self._ensure_customer()
        # Create + submit + pay an invoice in the current year.
        #
        # Pin a per-test-unique naming series. The default Sales Invoice series
        # (``ACC-SINV-.YYYY.-``) draws its counter from the shared ``tabSeries``
        # row, which every parallel CI shard contends on against ONE fresh DB.
        # Under that contention a sibling shard's rolled-back transaction can
        # leave our just-submitted invoice row clobbered, so a later
        # ``invoice.reload()`` raised ``DoesNotExistError`` (the invoice
        # "vanished" after pe.submit()). A unique series per test gives the
        # invoice a globally-collision-free name, structurally removing the race.
        unique_series = f"TDUES-{frappe.generate_hash(length=8).upper()}-.#####"
        invoice = self.create_test_sales_invoice(member=self.member.name, naming_series=unique_series)
        invoice.submit()
        self.track_doc("Sales Invoice", invoice.name)
        invoice_name = invoice.name
        self._pay_invoice(invoice)

        # Re-resolve the invoice by the per-test-unique naming_series — a field
        # this test fully controls and which NO sibling shard can collide on.
        # Relying on the raw name alone was fragile: when the SI used the shared
        # default series (ACC-SINV-.YYYY.-), two shards could draw the SAME name
        # from the contended ``tabSeries`` counter, and a sibling's rolled-back
        # transaction would then delete the row THIS test submitted ("invoice
        # vanished after pe.submit()"). The unique series makes the name
        # collision-free; re-querying by that series confirms the row survived
        # without depending on any globally-raced identifier.
        surviving = frappe.get_all(
            "Sales Invoice",
            filters={"naming_series": unique_series, "docstatus": 1},
            pluck="name",
        )
        self.assertEqual(
            surviving,
            [invoice_name],
            "submitted invoice must survive payment",
        )
        self.assertEqual(frappe.db.get_value("Sales Invoice", invoice_name, "status"), "Paid")

        # The YTD helpers query Sales Invoice by Customer (Member.customer).
        ytd = mdi._calculate_member_paid_ytd_optimized(customer)
        self.assertGreater(ytd, 0)
        # Python fallback must match SQL result.
        ytd_py = mdi._calculate_member_paid_ytd_python(customer)
        self.assertEqual(ytd, ytd_py)

    def test_calculate_paid_ytd_no_invoices_zero(self):
        # A customer with no paid invoices yields zero from both paths.
        customer = frappe.new_doc("Customer")
        customer.customer_name = f"YTD Empty {frappe.generate_hash(length=6)}"
        customer.customer_type = "Individual"
        customer.save()
        self.track_doc("Customer", customer.name)
        self.assertEqual(mdi._calculate_member_paid_ytd_optimized(customer.name), 0.0)
        self.assertEqual(mdi._calculate_member_paid_ytd_python(customer.name), 0.0)

    def _pay_invoice(self, invoice):
        """Mark a submitted Sales Invoice as Paid via a Payment Entry."""
        from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

        pe = get_payment_entry("Sales Invoice", invoice.name)
        pe.reference_no = "TEST-PAY"
        pe.reference_date = today()
        pe.save()
        pe.submit()
        self.track_doc("Payment Entry", pe.name)
        # Re-resolve the invoice from the DB by name (only if it still exists)
        # instead of reloading the in-memory doc unconditionally. Reloading a doc
        # whose row was lost raises DoesNotExistError; callers that need the fresh
        # state should query by the known name with an existence guard.
        if frappe.db.exists("Sales Invoice", invoice.name):
            invoice.reload()
        return pe

    # ---------------------------------------------------------- adjust_dues_schedule

    def test_adjust_dues_schedule_changes_amount_and_frequency(self):
        schedule_name = self._active_schedule_for_member()[0]
        original = frappe.get_doc("Membership Dues Schedule", schedule_name)

        result = mdi.adjust_dues_schedule(
            schedule_name,
            new_amount=99.0,
            new_frequency="Monthly",
            reason="rate review",
        )
        self.assertTrue(result["success"])
        self.assertEqual(len(result["changes"]), 2)

        updated = frappe.get_doc("Membership Dues Schedule", schedule_name)
        self.assertEqual(float(updated.dues_rate), 99.0)
        self.assertEqual(updated.billing_frequency, "Monthly")
        self.assertIn("rate review", updated.notes)
        self.assertNotEqual(float(original.dues_rate), 99.0)

    def test_adjust_dues_schedule_next_date(self):
        schedule_name = self._active_schedule_for_member()[0]
        new_date = add_months(today(), 2)
        result = mdi.adjust_dues_schedule(schedule_name, new_next_date=new_date)
        self.assertTrue(result["success"])
        updated = frappe.db.get_value("Membership Dues Schedule", schedule_name, "next_invoice_date")
        self.assertEqual(getdate(updated), getdate(new_date))

    def test_adjust_dues_schedule_no_changes(self):
        schedule_name = self._active_schedule_for_member()[0]
        result = mdi.adjust_dues_schedule(schedule_name)
        self.assertFalse(result["success"])
        self.assertIn("No changes", result["message"])

    # ---------------------------------------------------- schedule_naming_helper

    def test_generate_dues_schedule_name_sequence(self):
        # The membership already created schedule 001 for this member+type.
        existing = frappe.get_all(
            "Membership Dues Schedule",
            filters={
                "member": self.member.name,
                "membership_type": self.membership_type.name,
                "is_template": 0,
            },
            pluck="name",
        )
        name = generate_dues_schedule_name(self.member.name, self.membership_type.name)
        self.assertTrue(name.startswith(f"Schedule-{self.member.name}-{self.membership_type.name}-"))
        # Sequence is existing_count + 1, zero-padded to 3 digits.
        expected_seq = f"{len(existing) + 1:03d}"
        self.assertTrue(name.endswith(expected_seq))

    def test_generate_dues_schedule_name_uniqueness_on_collision(self):
        # When a schedule_name already matches the computed name, the helper
        # increments the sequence until unique.
        member_id = self.member.name
        mtype = self.membership_type.name
        first = generate_dues_schedule_name(member_id, mtype)
        # Materialise a schedule under that exact name so the next call must skip it.
        existing = self._active_schedule_for_member()
        if existing:
            frappe.db.set_value("Membership Dues Schedule", existing[0], "schedule_name", first)
            second = generate_dues_schedule_name(member_id, mtype)
            self.assertNotEqual(second, first)


class TestMemberPaidYtdFailsLoudly(VereningingenTestCase):
    """The Python fallback is the LAST line of defence, so its failure is real.

    `_calculate_member_paid_ytd_optimized` already degrades to this fallback when
    the SQL aggregation fails. If the fallback fails too, that is infrastructure
    failure -- per-invoice conversion errors are absorbed by its own loop. It used
    to return 0.0, reporting "paid nothing year-to-date".
    """

    def test_raises_when_both_paths_fail(self):
        """Drive the PUBLIC entry point with BOTH tiers failing.

        Calling the Python fallback directly would never exercise the SQL tier,
        so it could not prove the "both paths failed" claim this class is named
        for. Failing frappe.db.sql sends _optimized into the fallback, and
        failing frappe.get_all fails the fallback too.
        """
        from unittest.mock import patch

        with patch.object(frappe.db, "sql", side_effect=RuntimeError("database is down")):
            with patch.object(frappe, "get_all", side_effect=RuntimeError("database is down")):
                with self.assertRaises(RuntimeError):
                    mdi._calculate_member_paid_ytd_optimized("CUST-0001")

    def test_sql_failure_alone_still_degrades_to_the_python_fallback(self):
        """The tier that must KEEP working: SQL down, Python path answers.

        This is the control that makes the test above meaningful -- without it,
        making _optimized raise unconditionally would still pass.
        """
        from unittest.mock import patch

        with patch.object(frappe.db, "sql", side_effect=RuntimeError("database is down")):
            with patch.object(frappe, "get_all", return_value=[]):
                self.assertEqual(mdi._calculate_member_paid_ytd_optimized("CUST-0001"), 0.0)

    def test_still_returns_zero_when_there_are_no_invoices(self):
        """The control: a genuine zero is still 0.0, which is what made the
        swallow easy to miss in the first place."""
        from unittest.mock import patch

        with patch.object(frappe, "get_all", return_value=[]):
            self.assertEqual(mdi._calculate_member_paid_ytd_python("CUST-0001"), 0.0)
