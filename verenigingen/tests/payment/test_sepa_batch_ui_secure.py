"""
Real-integration tests for
verenigingen/verenigingen_payments/api/sepa_batch_ui_secure.py (previously 0% coverage).

The "_secure" endpoints mirror sepa_batch_ui.py but add input pre-checks, existence
checks, and audit logging (log_sepa_event). They are NOT wrapped with @handle_api_error,
so a failing pre-check raises SEPAError directly (a VerenigingenException subclass) rather
than returning an OperationResult dict.

Tests run as Administrator, satisfying the @critical_api / @high_security_api gates.
Nothing is mocked - real Member / SEPA Mandate / Sales Invoice / Direct Debit Batch
documents are built by SEPATestDataFactory. Audit events write real Mollie Audit Log rows.

PRODUCT BUGS exposed (xfailed):
    * create_sepa_batch_validated_secure shares the create_sepa_batch_validated bug:
      it sets batch_doc.description (reqd field is batch_description), never sets batch
      currency, and omits reqd child-row member/membership -> insert always fails.
"""

import unittest

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.utils.error_handling import SEPAError
from verenigingen.verenigingen_payments.api import sepa_batch_ui_secure as s


def _next_weekday(d):
    d = getdate(d)
    while d.weekday() >= 5:
        d = getdate(add_days(d, 1))
    return d


class SecureBase(EnhancedTestCase):
    def _build_member_with_invoice(self, first_name="SecProbe", grand_total=25.0):
        f = SEPATestDataFactory(seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True)
        self.factory = f
        member = f.create_test_member(first_name=first_name)
        customer = member.customer
        if not customer:
            customer = f.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
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


class TestLoadUnpaidInvoicesSecure(SecureBase):
    def test_returns_list_for_valid_range(self):
        result = s.load_unpaid_invoices_secure(date_range="all", limit=10)
        self.assertIsInstance(result, list)

    def test_loaded_invoice_enriched_with_member_and_mandate(self):
        data = self._build_member_with_invoice(first_name="SecLoadHit")
        result = s.load_unpaid_invoices_secure(date_range="all", limit=500)
        match = next((r for r in result if r.get("invoice") == data["invoice"].name), None)
        self.assertIsNotNone(match, "fresh unpaid invoice should be loaded")
        self.assertEqual(match["member"], data["member"].name)
        self.assertEqual(match["mandate_reference"], data["mandate"].mandate_id)
        self.assertTrue(match["iban"])

    def test_invalid_date_range_raises(self):
        with self.assertRaises(SEPAError):
            s.load_unpaid_invoices_secure(date_range="bogus")

    def test_limit_above_max_raises(self):
        with self.assertRaises(SEPAError):
            s.load_unpaid_invoices_secure(limit=s.SEPAInputValidator.MAX_BATCH_SIZE + 1)

    def test_unknown_membership_type_raises(self):
        # The secure variant validates that the membership type exists (unlike the
        # non-secure variant which silently ignores it).
        with self.assertRaises(SEPAError):
            s.load_unpaid_invoices_secure(membership_type="__no_such_membership_type__")

    def test_existing_membership_type_filter_succeeds(self):
        # Find any existing membership type so the existence check passes.
        mt = frappe.db.get_value("Membership Type", {}, "name")
        if not mt:
            self.skipTest("no Membership Type on site")
        result = s.load_unpaid_invoices_secure(date_range="all", membership_type=mt, limit=10)
        self.assertIsInstance(result, list)


class TestGetInvoiceMandateInfoSecure(SecureBase):
    def test_valid_invoice(self):
        data = self._build_member_with_invoice(first_name="SecMandInfo")
        result = s.get_invoice_mandate_info_secure(data["invoice"].name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["mandate_reference"], data["mandate"].mandate_id)

    def test_empty_invoice_raises(self):
        with self.assertRaises(SEPAError):
            s.get_invoice_mandate_info_secure("")

    def test_nonexistent_invoice_raises(self):
        with self.assertRaises(SEPAError):
            s.get_invoice_mandate_info_secure("SINV-NOT-HERE-0000")


class TestValidateInvoiceMandateSecure(SecureBase):
    def test_valid(self):
        data = self._build_member_with_invoice(first_name="SecValMand")
        result = s.validate_invoice_mandate_secure(data["invoice"].name, data["member"].name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["mandate_reference"], data["mandate"].mandate_id)

    def test_missing_invoice_param_raises(self):
        with self.assertRaises(SEPAError):
            s.validate_invoice_mandate_secure("", "whatever")

    def test_missing_member_param_raises(self):
        data = self._build_member_with_invoice(first_name="SecMemReq")
        with self.assertRaises(SEPAError):
            s.validate_invoice_mandate_secure(data["invoice"].name, "")

    def test_nonexistent_invoice_raises(self):
        data = self._build_member_with_invoice(first_name="SecInvReq")
        with self.assertRaises(SEPAError):
            s.validate_invoice_mandate_secure("SINV-GONE-0000", data["member"].name)

    def test_nonexistent_member_raises(self):
        data = self._build_member_with_invoice(first_name="SecMemNo")
        with self.assertRaises(SEPAError):
            s.validate_invoice_mandate_secure(data["invoice"].name, "Member-NOPE")

    def test_member_without_active_mandate(self):
        # Build a valid invoice (for the existence check) but validate a *different*
        # member that has no mandate.
        data = self._build_member_with_invoice(first_name="SecHasMand")
        bare_member = self.factory.create_test_member(first_name="SecNoMand")
        result = s.validate_invoice_mandate_secure(data["invoice"].name, bare_member.name)
        self.assertFalse(result["valid"])
        self.assertIn("mandate", result["error"].lower())


class TestGetBatchAnalyticsSecure(SecureBase):
    def test_valid_batch(self):
        f = SEPATestDataFactory(seed=820, use_faker=True)
        self.factory = f
        batch = f.create_test_direct_debit_batch(invoice_count=2)
        result = s.get_batch_analytics_secure(batch.name)
        self.assertEqual(result["summary"]["total_invoices"], 2)
        self.assertEqual(result["summary"]["status"], batch.status)

    def test_empty_batch_name_raises(self):
        with self.assertRaises(SEPAError):
            s.get_batch_analytics_secure("")

    def test_nonexistent_batch_raises(self):
        with self.assertRaises(SEPAError):
            s.get_batch_analytics_secure("DDB-NOPE-0000")


class TestPreviewSepaXmlSecure(SecureBase):
    def test_preview_structure(self):
        f = SEPATestDataFactory(seed=930, use_faker=True)
        self.factory = f
        batch = f.create_test_direct_debit_batch(invoice_count=2)
        result = s.preview_sepa_xml_secure(batch.name)
        self.assertEqual(result["header"]["number_of_transactions"], 2)
        self.assertEqual(len(result["transactions"]), 2)
        self.assertIn("****", result["transactions"][0]["debtor_iban"])

    def test_more_than_five_truncated(self):
        f = SEPATestDataFactory(seed=931, use_faker=True)
        self.factory = f
        batch = f.create_test_direct_debit_batch(invoice_count=6)
        result = s.preview_sepa_xml_secure(batch.name)
        self.assertEqual(len(result["transactions"]), 5)
        self.assertEqual(result["more_transactions"], 1)

    def test_empty_batch_name_raises(self):
        with self.assertRaises(SEPAError):
            s.preview_sepa_xml_secure("")

    def test_nonexistent_batch_raises(self):
        with self.assertRaises(SEPAError):
            s.preview_sepa_xml_secure("DDB-MISSING-0000")


class TestValidateBatchInvoicesSecure(SecureBase):
    def test_valid_list(self):
        f = SEPATestDataFactory(seed=741, use_faker=True)
        iban = f.generate_test_iban().replace(" ", "")
        result = s.validate_batch_invoices_secure(
            [
                {
                    "invoice": "INV-S1",
                    "amount": 30.0,
                    "iban": iban,
                    "member_name": "Secure Member",
                    "mandate_reference": "MNDT-S1",
                }
            ]
        )
        self.assertTrue(result["valid"], result.get("errors"))

    def test_json_string_input(self):
        import json

        f = SEPATestDataFactory(seed=742, use_faker=True)
        iban = f.generate_test_iban().replace(" ", "")
        payload = json.dumps(
            [
                {
                    "invoice": "INV-S2",
                    "amount": 12.0,
                    "iban": iban,
                    "member_name": "Secure Json",
                    "mandate_reference": "MNDT-S2",
                }
            ]
        )
        result = s.validate_batch_invoices_secure(payload)
        self.assertTrue(result["valid"], result.get("errors"))

    def test_invalid_json_reports_error(self):
        result = s.validate_batch_invoices_secure("{broken json")
        self.assertFalse(result["valid"])
        self.assertTrue(any("JSON" in e for e in result["errors"]))

    def test_empty_list_invalid(self):
        result = s.validate_batch_invoices_secure([])
        self.assertFalse(result["valid"])


class TestGetSepaValidationConstraintsSecure(SecureBase):
    def test_returns_rules(self):
        result = s.get_sepa_validation_constraints_secure()
        self.assertEqual(result["supported_currency"], "EUR")
        self.assertIn("constraints", result)


class TestSepaSecurityHealthCheck(SecureBase):
    def test_health_check_shape(self):
        result = s.sepa_security_health_check()
        self.assertTrue(result["success"])
        self.assertIn(result["overall_health"], ("healthy", "degraded"))
        for component in ("csrf_protection", "rate_limiting", "authorization", "audit_logging"):
            self.assertIn(component, result["components"])
            self.assertIn(result["components"][component]["status"], ("healthy", "error", "unknown"))


class TestCreateSepaBatchValidatedSecure(SecureBase):
    def _valid_params(self):
        data = self._build_member_with_invoice(first_name="SecCreateBatch")
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
        }

    def test_missing_params_validation_failure(self):
        result = s.create_sepa_batch_validated_secure()
        self.assertFalse(result["success"])
        self.assertEqual(result["message"], "Input validation failed")

    def test_empty_invoice_list_validation_failure(self):
        result = s.create_sepa_batch_validated_secure(
            batch_date=str(_next_weekday(add_days(today(), 3))),
            batch_type="CORE",
            invoice_list=[],
        )
        self.assertFalse(result["success"])

    def test_nonexistent_invoice_business_error(self):
        f = SEPATestDataFactory(seed=753, use_faker=True)
        iban = f.generate_test_iban().replace(" ", "")
        result = s.create_sepa_batch_validated_secure(
            batch_date=str(_next_weekday(add_days(today(), 3))),
            batch_type="CORE",
            invoice_list=[
                {
                    "invoice": "SINV-GHOST-001",
                    "amount": 25.0,
                    "iban": iban,
                    "member_name": "Ghost",
                    "mandate_reference": "MNDT-GH",
                    "currency": "EUR",
                }
            ],
        )
        self.assertFalse(result["success"])
        self.assertTrue(any("Invoice not found" in e for e in result["errors"]))

    def test_valid_params_should_create_batch(self):
        """Regression (FIXED): the Direct Debit Batch insert now populates
        batch_description / currency / child member+membership reqd fields."""
        result = s.create_sepa_batch_validated_secure(**self._valid_params())
        self.assertTrue(result["success"], result.get("errors"))
        self.assertTrue(frappe.db.exists("Direct Debit Batch", result["batch_name"]))

    def test_batch_row_uses_membership_from_invoice_dues_schedule(self):
        """F4: with multiple submitted memberships, the secure path must also resolve
        the batch row's membership from the invoice's dues schedule, not an arbitrary
        member lookup."""
        data = self._build_member_with_invoice(first_name="SecTwoMemberships")
        member = data["member"]

        # Cancel the auto-created active membership and create a fresh active one so
        # there are two submitted memberships; point the dues schedule at the fresh one.
        old_membership = data["membership"]
        frappe.db.set_value("Membership", old_membership.name, "status", "Cancelled", update_modified=False)
        frappe.db.set_value("Membership", old_membership.name, "docstatus", 2, update_modified=False)

        f = self.factory
        new_active = f.create_test_membership(member=member.name)
        frappe.db.set_value(
            "Membership Dues Schedule",
            data["schedule"].name,
            "membership",
            new_active.name,
            update_modified=False,
        )

        iban = data["mandate"].iban.replace(" ", "")
        result = s.create_sepa_batch_validated_secure(
            batch_date=str(_next_weekday(add_days(today(), 3))),
            batch_type="CORE",
            invoice_list=[
                {
                    "invoice": data["invoice"].name,
                    "amount": float(data["invoice"].outstanding_amount),
                    "iban": iban,
                    "member_name": member.full_name,
                    "mandate_reference": data["mandate"].mandate_id,
                    "currency": "EUR",
                }
            ],
        )
        self.assertTrue(result["success"], result.get("errors"))
        batch = frappe.get_doc("Direct Debit Batch", result["batch_name"])
        self.assertEqual(len(batch.invoices), 1)
        self.assertEqual(batch.invoices[0].membership, new_active.name)
        self.assertNotEqual(batch.invoices[0].membership, old_membership.name)

    def test_non_eur_invoice_is_rejected(self):
        """F5: the secure path must also reject non-EUR invoices (SEPA DD is EUR-only).
        Keep the payload currency 'EUR' (passes input validation) but flip the stored
        Sales Invoice currency to USD to exercise the per-invoice EUR guard."""
        data = self._build_member_with_invoice(first_name="SecNonEur")
        frappe.db.set_value(
            "Sales Invoice", data["invoice"].name, "currency", "USD", update_modified=False
        )
        iban = data["mandate"].iban.replace(" ", "")
        result = s.create_sepa_batch_validated_secure(
            batch_date=str(_next_weekday(add_days(today(), 3))),
            batch_type="CORE",
            invoice_list=[
                {
                    "invoice": data["invoice"].name,
                    "amount": float(data["invoice"].outstanding_amount),
                    "iban": iban,
                    "member_name": data["member"].full_name,
                    "mandate_reference": data["mandate"].mandate_id,
                    "currency": "EUR",
                }
            ],
        )
        self.assertFalse(result["success"])
        self.assertIn("not in EUR", " ".join(result.get("errors", [])))
