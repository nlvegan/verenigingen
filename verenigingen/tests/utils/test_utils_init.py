"""
Integration tests for verenigingen.utils.__init__ utility grab-bag.

Covered:
- determine_payment_status (pure read-only computation)
- batch_fetch_with_chunking (real frappe.get_all over real data)
- append_to_text_field (pure)
- format_address / get_membership_status / format_date_range (jinja methods)
- format_currency / status_color (jinja filters)
- DutchTaxExemptionHandler init + apply_exemption_to_invoice (BTW logic)
- generate_btw_report (read-only aggregation)

The format_*/status_color/append_to_text_field/determine_payment_status helpers
are nearly pure and are tested directly with plain data carriers (NOT mocks of
business logic). get_membership_status / generate_btw_report hit the real DB.
"""

import types

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils import (
    DutchTaxExemptionHandler,
    append_to_text_field,
    batch_fetch_with_chunking,
    determine_payment_status,
    format_address,
    format_currency,
    format_date_range,
    generate_btw_report,
    get_membership_status,
    jinja_filters,
    jinja_methods,
    status_color,
)


def _invoice(**kwargs):
    """Plain data carrier mimicking the attributes determine_payment_status reads.

    This is a value object, not a mock of business logic; the function under test
    performs pure computation on these attribute values.
    """
    defaults = {
        "docstatus": 1,
        "status": "Unpaid",
        "outstanding_amount": 100.0,
        "grand_total": 100.0,
    }
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


class TestDeterminePaymentStatus(EnhancedTestCase):
    def test_draft_when_docstatus_zero(self):
        self.assertEqual(
            determine_payment_status(_invoice(docstatus=0, status="Unpaid")), "Draft"
        )

    def test_paid_when_status_paid(self):
        self.assertEqual(
            determine_payment_status(_invoice(status="Paid", outstanding_amount=100.0)),
            "Paid",
        )

    def test_paid_when_no_outstanding(self):
        self.assertEqual(
            determine_payment_status(_invoice(status="Unpaid", outstanding_amount=0)),
            "Paid",
        )

    def test_paid_when_negative_outstanding(self):
        self.assertEqual(
            determine_payment_status(_invoice(status="Unpaid", outstanding_amount=-5)),
            "Paid",
        )

    def test_overdue(self):
        self.assertEqual(
            determine_payment_status(_invoice(status="Overdue", outstanding_amount=50)),
            "Overdue",
        )

    def test_cancelled(self):
        self.assertEqual(
            determine_payment_status(_invoice(status="Cancelled", outstanding_amount=50)),
            "Cancelled",
        )

    def test_partially_paid(self):
        self.assertEqual(
            determine_payment_status(
                _invoice(status="Unpaid", outstanding_amount=60, grand_total=100),
                paid_amount=40,
            ),
            "Partially Paid",
        )

    def test_unpaid_when_no_payment(self):
        self.assertEqual(
            determine_payment_status(
                _invoice(status="Unpaid", outstanding_amount=100, grand_total=100),
                paid_amount=0,
            ),
            "Unpaid",
        )

    def test_full_payment_not_partial(self):
        # paid_amount == grand_total -> NOT "Partially Paid"; falls through to Unpaid
        # (status is not Paid and outstanding still positive in this contrived case)
        self.assertEqual(
            determine_payment_status(
                _invoice(status="Unpaid", outstanding_amount=100, grand_total=100),
                paid_amount=100,
            ),
            "Unpaid",
        )


class TestBatchFetchWithChunking(EnhancedTestCase):
    def test_empty_name_list_returns_empty(self):
        self.assertEqual(
            batch_fetch_with_chunking("Member", [], ["name"]), []
        )

    def test_fetches_real_records_across_chunks(self):
        m1 = self.create_test_member(first_name="Chunk", last_name="One")
        m2 = self.create_test_member(first_name="Chunk", last_name="Two")
        names = [m1.name, m2.name]
        # chunk_size=1 forces multiple chunks; result must still include both
        results = batch_fetch_with_chunking("Member", names, ["name"], chunk_size=1)
        fetched = {r["name"] for r in results}
        self.assertEqual(fetched, set(names))

    def test_additional_filters_are_merged(self):
        m1 = self.create_test_member(first_name="FilterA", last_name="X")
        m2 = self.create_test_member(first_name="FilterB", last_name="Y")
        results = batch_fetch_with_chunking(
            "Member",
            [m1.name, m2.name],
            ["name", "first_name"],
            filters={"first_name": "FilterA"},
        )
        # Only m1 matches the extra filter
        self.assertEqual([r["name"] for r in results], [m1.name])


class TestAppendToTextField(EnhancedTestCase):
    def test_append_to_empty_field(self):
        doc = types.SimpleNamespace(notes=None)
        append_to_text_field(doc, "notes", "first")
        self.assertEqual(doc.notes, "first")

    def test_append_to_existing_field_uses_separator(self):
        doc = types.SimpleNamespace(notes="first")
        append_to_text_field(doc, "notes", "second")
        self.assertEqual(doc.notes, "first\n\nsecond")

    def test_custom_separator(self):
        doc = types.SimpleNamespace(notes="a")
        append_to_text_field(doc, "notes", "b", separator=" | ")
        self.assertEqual(doc.notes, "a | b")

    def test_missing_field_is_noop(self):
        doc = types.SimpleNamespace(other="x")
        append_to_text_field(doc, "notes", "ignored")
        self.assertFalse(hasattr(doc, "notes"))


class TestFormatHelpers(EnhancedTestCase):
    def test_format_address_full(self):
        result = format_address(
            {
                "address_line1": "Main St 1",
                "address_line2": "Apt 2",
                "city": "Amsterdam",
                "state": "NH",
                "postal_code": "1011AA",
                "country": "Netherlands",
            }
        )
        self.assertIn("Main St 1", result)
        self.assertIn("Apt 2", result)
        self.assertIn("Amsterdam, NH", result)
        self.assertIn("1011AA", result)
        self.assertIn("Netherlands", result)
        self.assertIn("<br>", result)

    def test_format_address_empty(self):
        self.assertEqual(format_address(None), "")
        self.assertEqual(format_address({}), "")

    def test_format_address_partial(self):
        result = format_address({"address_line1": "Solo St 9", "city": "Utrecht"})
        self.assertEqual(result, "Solo St 9<br>Utrecht")

    def test_format_date_range_both(self):
        result = format_date_range("2026-01-01", "2026-12-31")
        self.assertIn(" - ", result)
        self.assertNotIn("Indefinite", result)

    def test_format_date_range_open_ended(self):
        result = format_date_range("2026-01-01", None)
        self.assertIn("Indefinite", result)

    def test_format_date_range_no_start(self):
        self.assertEqual(format_date_range(None, "2026-12-31"), "")

    def test_format_currency_value(self):
        result = format_currency(1234.5)
        self.assertIn("1,234", result.replace(".", ","))  # locale-tolerant digit check

    def test_format_currency_zero_and_none(self):
        # Both should produce a formatted zero amount, not crash
        self.assertTrue(format_currency(0))
        self.assertTrue(format_currency(None))

    def test_status_color_known(self):
        self.assertEqual(status_color("Active"), "green")
        self.assertEqual(status_color("Pending"), "orange")
        self.assertEqual(status_color("Expired"), "red")
        self.assertEqual(status_color("Cancelled"), "grey")
        self.assertEqual(status_color("Draft"), "blue")

    def test_status_color_unknown_default(self):
        self.assertEqual(status_color("Whatever"), "grey")

    def test_jinja_methods_and_filters_registry(self):
        methods = jinja_methods()
        self.assertIn("format_address", methods)
        self.assertIn("get_membership_status", methods)
        self.assertIn("format_date_range", methods)
        filters = jinja_filters()
        self.assertIn("format_currency", filters)
        self.assertIn("status_color", filters)


class TestGetMembershipStatus(EnhancedTestCase):
    def test_unknown_when_no_member_name(self):
        self.assertEqual(get_membership_status(None), "Unknown")
        self.assertEqual(get_membership_status(""), "Unknown")

    def test_inactive_when_no_membership(self):
        member = self.create_test_member(first_name="NoMem", last_name="Ship")
        self.assertEqual(get_membership_status(member.name), "Inactive")

    def test_active_when_membership_exists(self):
        member = self.create_test_member(first_name="HasMem", last_name="Ship")
        self.create_test_membership(member_name=member.name)
        self.assertEqual(get_membership_status(member.name), "Active")


class TestDutchTaxExemptionHandler(EnhancedTestCase):
    def test_handler_init_reads_company(self):
        handler = DutchTaxExemptionHandler()
        self.assertTrue(handler.company)
        self.assertEqual(
            handler.company,
            frappe.get_single("Verenigingen Settings").company,
        )

    def test_apply_exemption_sets_btw_fields(self):
        # Use a plain data carrier representing a Sales Invoice with BTW fields.
        # apply_exemption_to_invoice performs pure field assignment + a template
        # existence check; no business logic is mocked.
        handler = DutchTaxExemptionHandler()
        invoice = types.SimpleNamespace(
            membership=None,
            donation=None,
            btw_exemption_reason=None,
            taxes_and_charges=None,
            exempt_from_tax=0,
        )
        handler.apply_exemption_to_invoice(invoice, "EXEMPT_MEMBERSHIP")
        self.assertEqual(invoice.exempt_from_tax, 1)
        self.assertEqual(invoice.btw_exemption_type, "EXEMPT_MEMBERSHIP")
        # Reporting category mapped from BTW_REPORTING_CATEGORIES
        self.assertEqual(invoice.btw_reporting_category, "1a")
        # Reason defaulted from BTW_CODES
        self.assertIn("Art. 11-1-l", invoice.btw_exemption_reason)

    def test_apply_exemption_default_for_membership_invoice(self):
        handler = DutchTaxExemptionHandler()
        invoice = types.SimpleNamespace(
            membership="MEM-001",
            donation=None,
            btw_exemption_reason=None,
            taxes_and_charges=None,
            exempt_from_tax=0,
        )
        handler.apply_exemption_to_invoice(invoice)  # no explicit type
        self.assertEqual(invoice.btw_exemption_type, "EXEMPT_MEMBERSHIP")

    def test_apply_exemption_with_input_uses_box_3(self):
        handler = DutchTaxExemptionHandler()
        invoice = types.SimpleNamespace(
            membership=None,
            donation=None,
            btw_exemption_reason=None,
            taxes_and_charges=None,
            exempt_from_tax=0,
        )
        handler.apply_exemption_to_invoice(invoice, "EXEMPT_WITH_INPUT")
        self.assertEqual(invoice.btw_reporting_category, "3")


class TestGenerateBtwReport(EnhancedTestCase):
    def test_report_has_all_categories_and_total(self):
        report = generate_btw_report("2020-01-01", "2020-01-02")
        # Structure must always be present even with zero invoices in the window
        for box in ["1a", "1b", "2a", "3", "5d", "total"]:
            self.assertIn(box, report)
        # An empty window yields zeroed totals
        self.assertEqual(report["total"], 0)
