"""
Real-integration tests for verenigingen/verenigingen_payments/api/sepa_batch_ui.py
(previously 0% coverage).

Drives the whitelisted SEPA Batch UI endpoints against real Member / SEPA Mandate /
Membership / Membership Dues Schedule / Sales Invoice / Direct Debit Batch documents
built by SEPATestDataFactory. Nothing is mocked.

Tests run as Administrator, which satisfies the @critical_api / @high_security_api
authorization gates.

Return-shape notes (verified live on test_site_1):
    * Endpoints wrapped with @handle_api_error return a *dict* on error, in the
      OperationResult.to_dict() shape:
          {"success": False, "error": {"message": ..., "code": ...}, "meta": {...}}
      and the raw value (list / dict) on success.
    * load_unpaid_invoices / validate_batch_invoices / get_sepa_validation_constraints
      / get_batch_analytics / create_sepa_batch_validated are @handle_api_error wrapped.
    * get_invoice_mandate_info / validate_invoice_mandate are NOT wrapped (they
      catch internally and return plain dicts).

PRODUCT BUGS still open (xfailed below, flagged for a maintainer decision):
    * create_sepa_batch_validated can never create a batch: it sets batch_doc.description
      (no such field; reqd field is batch_description), never sets batch currency, and
      omits the reqd child-row fields member / membership. Insert always fails with
      "batch_description, membership, member". (Fixing it needs sourcing member/membership
      per invoice, so it is left flagged rather than guessed at.)
    * validate_with_schema("sepa_batch") decorator is a no-op (schema fields
      batch_name/execution_date/invoice_ids do not match the function body and never
      enforce).

Fixed during this sweep:
    * load_unpaid_invoices(limit=0) used to bypass limit validation (falsy short-circuit);
      the guard now uses `is not None`.
"""

import unittest

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.verenigingen_payments.api import sepa_batch_ui as ui


def _next_weekday(d):
    """Return the first non-weekend date on/after d."""
    d = getdate(d)
    while d.weekday() >= 5:
        d = getdate(add_days(d, 1))
    return d


class SepaBatchUITestBase(EnhancedTestCase):
    """Shared helpers to build a fully-wired member -> mandate -> invoice chain."""

    def _build_member_with_invoice(self, first_name="UiProbe", grand_total=25.0):
        f = SEPATestDataFactory(seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True)
        self.factory = f
        member = f.create_test_member(first_name=first_name)
        customer = member.customer
        if not customer:
            customer = f.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
        # Customer.member backlink is what Sales Invoice before_validate reads.
        frappe.db.set_value("Customer", customer, "member", member.name)
        mandate = f.create_test_sepa_mandate(member=member.name)
        membership = f.create_test_membership(member=member.name)
        schedule = f.create_test_membership_dues_schedule(
            member=member.name, payment_terms_template="SEPA Direct Debit"
        )
        invoice = f.create_test_sales_invoice(
            customer=customer,
            member=member.name,
            membership=membership.name,
            membership_dues_schedule_display=schedule.name,
            grand_total=grand_total,
            submit=True,
        )
        return {
            "member": member,
            "customer": customer,
            "mandate": mandate,
            "membership": membership,
            "schedule": schedule,
            "invoice": invoice,
        }

    @staticmethod
    def _is_error_result(result):
        """True if result is the OperationResult.to_dict() failure shape."""
        return isinstance(result, dict) and result.get("success") is False and "error" in result


class TestLoadUnpaidInvoices(SepaBatchUITestBase):
    def test_returns_list_for_valid_range(self):
        result = ui.load_unpaid_invoices(date_range="all", limit=10)
        self.assertIsInstance(result, list)

    def test_loaded_invoice_has_member_and_mandate_fields(self):
        data = self._build_member_with_invoice(first_name="LoadHit")
        result = ui.load_unpaid_invoices(date_range="all", limit=500)
        self.assertIsInstance(result, list)
        match = next((r for r in result if r.get("invoice") == data["invoice"].name), None)
        self.assertIsNotNone(match, "freshly created unpaid invoice should be loaded")
        # The batch optimizer enriches each row with member + mandate data.
        self.assertEqual(match["member"], data["member"].name)
        self.assertEqual(match["member_name"], data["member"].full_name)
        self.assertTrue(match["iban"])
        self.assertEqual(match["mandate_reference"], data["mandate"].mandate_id)

    def test_invalid_date_range_returns_error_result(self):
        result = ui.load_unpaid_invoices(date_range="bogus")
        self.assertTrue(self._is_error_result(result))
        self.assertEqual(result["error"]["code"], "SEPA_ERROR")
        self.assertIn("date_range", result["error"]["message"])

    def test_limit_above_max_returns_error_result(self):
        result = ui.load_unpaid_invoices(limit=ui.SEPAInputValidator.MAX_BATCH_SIZE + 1)
        self.assertTrue(self._is_error_result(result))
        self.assertEqual(result["error"]["code"], "SEPA_ERROR")
        self.assertIn("limit", result["error"]["message"].lower())

    def test_negative_limit_returns_error_result(self):
        result = ui.load_unpaid_invoices(limit=-5)
        self.assertTrue(self._is_error_result(result))

    def test_membership_type_filter_with_no_memberships_returns_empty(self):
        # A membership type with zero memberships leaves the filter unconstrained-by-membership;
        # the call must still succeed and return a list.
        result = ui.load_unpaid_invoices(date_range="all", membership_type="__nonexistent_mt__", limit=10)
        self.assertIsInstance(result, list)

    def test_due_this_week_range_succeeds(self):
        result = ui.load_unpaid_invoices(date_range="due_this_week", limit=10)
        self.assertIsInstance(result, list)

    def test_limit_zero_should_be_rejected(self):
        """limit=0 is an invalid limit and must be rejected.

        Regression: the guard was `if limit and (...)`, so a falsy limit=0
        short-circuited past validation and was silently accepted. The guard is
        now `if limit is not None and (...)`.
        """
        result = ui.load_unpaid_invoices(limit=0)
        self.assertTrue(self._is_error_result(result))


class TestGetInvoiceMandateInfo(SepaBatchUITestBase):
    def test_returns_mandate_info_for_valid_invoice(self):
        data = self._build_member_with_invoice(first_name="MandInfo")
        result = ui.get_invoice_mandate_info(data["invoice"].name)
        self.assertIsInstance(result, dict)
        self.assertTrue(result["valid"])
        self.assertEqual(result["mandate_reference"], data["mandate"].mandate_id)
        self.assertTrue(result["iban"])

    def test_returns_none_for_unknown_invoice(self):
        result = ui.get_invoice_mandate_info("SINV-NOPE-0000")
        self.assertIsNone(result)


class TestValidateInvoiceMandate(SepaBatchUITestBase):
    def test_valid_member_and_mandate(self):
        data = self._build_member_with_invoice(first_name="ValMand")
        result = ui.validate_invoice_mandate(data["invoice"].name, data["member"].name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["mandate_reference"], data["mandate"].mandate_id)

    def test_member_without_mandate(self):
        member = SEPATestDataFactory(seed=7, use_faker=True).create_test_member(first_name="NoMand")
        result = ui.validate_invoice_mandate("SINV-IRRELEVANT", member.name)
        self.assertFalse(result["valid"])
        self.assertIn("mandate", result["error"].lower())

    def test_unknown_member_returns_invalid(self):
        result = ui.validate_invoice_mandate("SINV-X", "Member-DOES-NOT-EXIST")
        self.assertFalse(result["valid"])

    def test_expired_mandate_reported(self):
        # A mandate inserted with a past expiry auto-sets status="Expired", which the
        # active-mandate SQL filters out (reporting "no active mandate"). To reach the
        # explicit expiry-date branch the mandate must stay Active, so set the past
        # expiry directly on the DB after an Active insert.
        f = SEPATestDataFactory(seed=11, use_faker=True)
        member = f.create_test_member(first_name="ExpMand")
        mandate = f.create_test_sepa_mandate(member=member.name)
        self.assertEqual(mandate.status, "Active")
        frappe.db.set_value("SEPA Mandate", mandate.name, "expiry_date", add_days(today(), -1))
        result = ui.validate_invoice_mandate("SINV-Y", member.name)
        self.assertFalse(result["valid"])
        self.assertIn("expired", result["error"].lower())


class TestGetBatchAnalytics(SepaBatchUITestBase):
    def test_analytics_for_real_batch(self):
        f = SEPATestDataFactory(seed=321, use_faker=True)
        self.factory = f
        batch = f.create_test_direct_debit_batch(invoice_count=3)
        result = ui.get_batch_analytics(batch.name)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["summary"]["total_invoices"], 3)
        self.assertEqual(result["summary"]["status"], batch.status)
        self.assertAlmostEqual(result["summary"]["total_amount"], batch.total_amount)
        # All factory rows carry an IBAN + mandate, so there should be no issues.
        self.assertEqual(result["issues"], [])
        # by_status is a list of {status, count, amount}.
        self.assertTrue(any(s["status"] == "Pending" and s["count"] == 3 for s in result["by_status"]))

    def test_missing_batch_returns_error_result(self):
        result = ui.get_batch_analytics("NO-SUCH-BATCH")
        self.assertTrue(self._is_error_result(result))
        self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")


class TestPreviewSepaXml(SepaBatchUITestBase):
    def test_preview_structure(self):
        f = SEPATestDataFactory(seed=987, use_faker=True)
        self.factory = f
        batch = f.create_test_direct_debit_batch(invoice_count=2)
        result = ui.preview_sepa_xml(batch.name)
        self.assertEqual(result["header"]["number_of_transactions"], 2)
        self.assertEqual(result["header"]["message_id"], f"BATCH-{batch.name}")
        self.assertEqual(len(result["transactions"]), 2)
        # IBAN is masked in the preview.
        masked = result["transactions"][0]["debtor_iban"]
        self.assertIn("****", masked)
        self.assertNotIn("more_transactions", result)

    def test_preview_truncates_to_five_and_reports_more(self):
        f = SEPATestDataFactory(seed=246, use_faker=True)
        self.factory = f
        batch = f.create_test_direct_debit_batch(invoice_count=7)
        result = ui.preview_sepa_xml(batch.name)
        self.assertEqual(len(result["transactions"]), 5)
        self.assertEqual(result["more_transactions"], 2)


class TestValidateBatchInvoices(SepaBatchUITestBase):
    def test_valid_invoice_list(self):
        f = SEPATestDataFactory(seed=135, use_faker=True)
        iban = f.generate_test_iban().replace(" ", "")
        invoice_list = [
            {
                "invoice": "INV-001",
                "amount": 25.0,
                "iban": iban,
                "member_name": "Jane Doe",
                "mandate_reference": "MNDT-001",
                "currency": "EUR",
            }
        ]
        result = ui.validate_batch_invoices(invoice_list)
        self.assertTrue(result["valid"], result.get("errors"))
        self.assertEqual(len(result["cleaned_invoices"]), 1)

    def test_json_string_input_accepted(self):
        import json

        f = SEPATestDataFactory(seed=975, use_faker=True)
        iban = f.generate_test_iban().replace(" ", "")
        payload = json.dumps(
            [
                {
                    "invoice": "INV-J1",
                    "amount": 10.0,
                    "iban": iban,
                    "member_name": "John Roe",
                    "mandate_reference": "MNDT-J1",
                }
            ]
        )
        result = ui.validate_batch_invoices(payload)
        self.assertTrue(result["valid"], result.get("errors"))

    def test_invalid_json_string_reports_error(self):
        result = ui.validate_batch_invoices("{not valid json")
        self.assertFalse(result["valid"])
        self.assertTrue(any("JSON" in e for e in result["errors"]))

    def test_empty_list_is_invalid(self):
        result = ui.validate_batch_invoices([])
        self.assertFalse(result["valid"])
        self.assertTrue(any("empty" in e.lower() for e in result["errors"]))

    def test_missing_required_fields_reported(self):
        result = ui.validate_batch_invoices([{"invoice": "INV-BAD"}])
        self.assertFalse(result["valid"])
        # Missing amount/iban/member_name/mandate_reference each reported.
        joined = " ".join(result["errors"])
        self.assertIn("Required field missing", joined)


class TestGetSepaValidationConstraints(SepaBatchUITestBase):
    def test_returns_constraints(self):
        result = ui.get_sepa_validation_constraints()
        self.assertIn("constraints", result)
        self.assertEqual(result["supported_currency"], "EUR")
        self.assertEqual(
            result["required_invoice_fields"],
            ["invoice", "amount", "iban", "member_name", "mandate_reference"],
        )


class TestCreateSepaBatchValidated(SepaBatchUITestBase):
    def _valid_params(self):
        data = self._build_member_with_invoice(first_name="CreateBatch")
        iban = data["mandate"].iban.replace(" ", "")
        invoice_list = [
            {
                "invoice": data["invoice"].name,
                "amount": float(data["invoice"].outstanding_amount),
                "iban": iban,
                "member_name": data["member"].full_name,
                "mandate_reference": data["mandate"].mandate_id,
                "currency": "EUR",
            }
        ]
        return {
            "batch_date": str(_next_weekday(add_days(today(), 3))),
            "batch_type": "CORE",
            "invoice_list": invoice_list,
        }, data

    def test_missing_required_params_returns_validation_failure(self):
        result = ui.create_sepa_batch_validated()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Input validation failed")
        joined = " ".join(result["errors"])
        self.assertIn("batch_date", joined)
        self.assertIn("invoice_list", joined)

    def test_invalid_batch_type_returns_validation_failure(self):
        params, _ = self._valid_params()
        params["batch_type"] = "NOTATYPE"
        result = ui.create_sepa_batch_validated(**params)
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Input validation failed")

    def test_empty_invoice_list_returns_validation_failure(self):
        result = ui.create_sepa_batch_validated(
            batch_date=str(_next_weekday(add_days(today(), 3))),
            batch_type="CORE",
            invoice_list=[],
        )
        self.assertFalse(result["success"])
        self.assertTrue(any("empty" in e.lower() for e in result["errors"]))

    def test_nonexistent_invoice_reports_business_error(self):
        f = SEPATestDataFactory(seed=159, use_faker=True)
        iban = f.generate_test_iban().replace(" ", "")
        invoice_list = [
            {
                "invoice": "SINV-NOT-REAL-0001",
                "amount": 25.0,
                "iban": iban,
                "member_name": "Ghost Member",
                "mandate_reference": "MNDT-G1",
                "currency": "EUR",
            }
        ]
        result = ui.create_sepa_batch_validated(
            batch_date=str(_next_weekday(add_days(today(), 3))),
            batch_type="CORE",
            invoice_list=invoice_list,
        )
        self.assertFalse(result["success"])
        joined = " ".join(result["errors"])
        self.assertIn("Invoice not found", joined)

    @unittest.expectedFailure
    def test_valid_params_should_create_batch(self):
        """PRODUCT BUG: create_sepa_batch_validated can never insert a Direct Debit
        Batch. It sets batch_doc.description (the reqd field is batch_description),
        never sets the reqd batch `currency`, and omits the reqd child-row fields
        `member` / `membership`. The DocType insert fails with mandatory-field error
        'batch_description, membership, member', so success is always False.
        """
        params, _ = self._valid_params()
        result = ui.create_sepa_batch_validated(**params)
        self.assertTrue(result["success"], result.get("errors"))
        self.assertTrue(result.get("batch_name"))
        self.assertTrue(frappe.db.exists("Direct Debit Batch", result["batch_name"]))
