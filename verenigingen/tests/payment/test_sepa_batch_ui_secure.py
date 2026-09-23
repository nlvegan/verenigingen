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

import inspect
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.fixtures.sepa_test_factory import SEPATestDataFactory
from verenigingen.tests.payment.sepa_batch_loader_test_helpers import (
    customer_only_invoice,
    put_invoice_in_batch,
)
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

    @staticmethod
    def _dues_schedule_membership_type(chain):
        """The (unique-per-chain) membership type, to isolate a test from unpaid
        invoices left behind by other tests on a shared site."""
        return frappe.db.get_value("Membership Dues Schedule", chain["schedule"].name, "membership_type")


class TestLoadUnpaidInvoicesSecure(SecureBase):
    def test_returns_list_for_valid_range(self):
        result = s.load_unpaid_invoices_secure(date_range="all", limit=10)
        self.assertIsInstance(result, list)

    def test_loaded_invoice_enriched_with_member_and_mandate(self):
        # Scoped to this chain's own membership type (#1223). An unscoped call caps
        # at `limit` and orders by due_date, so on any site already holding more than
        # `limit` unpaid invoices the fixture falls off the page and this fails
        # whether or not the code is correct. Measured on test_site_3, 2026-09-22:
        # 584 unpaid invoices vs limit=500, and this test failed there on untouched
        # develop for exactly that reason. Its non-secure counterpart
        # (`test_loaded_invoice_has_member_and_mandate_fields`) was already scoped;
        # this file was the sibling #1223 names as never having had the treatment.
        data = self._build_member_with_invoice(first_name="SecLoadHit")
        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(data), limit=500
        )
        match = next((r for r in result if r.get("invoice") == data["invoice"].name), None)
        self.assertIsNotNone(match, "fresh unpaid invoice should be loaded")
        self.assertEqual(match["member"], data["member"].name)
        self.assertEqual(match["mandate_reference"], data["mandate"].mandate_id)
        self.assertTrue(match["iban"])

    def test_loaded_invoice_row_has_nonblank_membership_key(self):
        """#1227: this endpoint's rows must carry the same keys as its non-secure
        twin's. `direct_debit_batch.js:505-538` feeds the TWIN's rows straight into
        `frm.add_child('invoices', inv)` with no re-derivation, against the
        required Link `Direct Debit Batch Invoice.membership`. The twin
        (`sepa_batch_ui.py`) selects the aliased column; this endpoint selected the
        unaliased one, so its rows had no `membership` key at all.

        The dialog does NOT call this endpoint -- no .js file in the app references
        `load_unpaid_invoices_secure`, and the button's visibility gate checks the
        non-secure function. This is reachable only by direct RPC from an
        authorized role, so what is guarded here is twin parity, not a live UI
        path. Stated explicitly because an earlier version of this docstring
        claimed the dialog consumed these rows.

        This asserts the row actually clears Frappe's own mandatory-field check
        (`_get_missing_mandatory_fields`), not merely that a dict key exists --
        i.e. that the row is usable by its real consumer. It does NOT assert the
        *value* resolves to an existing Membership record: both this endpoint and
        its non-secure twin put a Membership Dues Schedule name there, which is a
        separate, wider defect (LinkValidationError on save) tracked in #1239,
        not fixed here.
        """
        data = self._build_member_with_invoice(first_name="SecMandField")
        # Scoped to this chain's own (unique) membership type -- like the
        # exclusion tests above -- so the match is not lost among unpaid
        # invoices already on a shared test site (see #1223, a pre-existing
        # flake from `limit=500` alone on a busy site).
        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(data), limit=500
        )
        match = next((r for r in result if r.get("invoice") == data["invoice"].name), None)
        self.assertIsNotNone(match, "fresh unpaid invoice should be loaded")

        batch = frappe.new_doc("Direct Debit Batch")
        batch.append("invoices", dict(match))
        child = batch.invoices[0]
        missing_fields = [fieldname for fieldname, _msg in child._get_missing_mandatory_fields()]
        self.assertNotIn(
            "membership",
            missing_fields,
            f"membership key missing or blank, breaking parity with the non-secure twin: {match}",
        )

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


class TestLoadUnpaidInvoicesSecureEligibilityGuards(SecureBase):
    """#1218: `load_unpaid_invoices_secure` shares the non-secure loader's query
    shape and the same omission -- no membership-link guard, no currency guard.
    Same fix, same twin-parity requirement (#1244 tracks the OTHER divergence,
    security levels, which is NOT fixed here). See
    TestLoadUnpaidInvoicesEligibilityGuards (test_sepa_batch_ui.py) for the
    measured veg11 counts this guard is based on.
    """

    def test_invoice_with_no_member_and_no_dues_schedule_link_is_excluded(self):
        invoice = customer_only_invoice(self, "SecNoLinkNoMember")

        result = s.load_unpaid_invoices_secure(date_range="all", limit=500)
        names = {r.get("invoice") for r in result}
        self.assertNotIn(
            invoice.name,
            names,
            "an invoice with no member and no dues-schedule link must not be offered as a SEPA candidate",
        )

    def test_invoice_with_member_but_no_dues_schedule_link_is_still_included(self):
        f = SEPATestDataFactory(seed=frappe.generate_hash(length=4).__hash__() & 0xFFFF, use_faker=True)
        self.factory = f
        member = f.create_test_member(first_name="SecMemberNoSchedule")
        customer = member.customer
        if not customer:
            customer = f.create_test_customer(customer_name=f"Cust {member.full_name}").name
            member.db_set("customer", customer)
        frappe.db.set_value("Customer", customer, "member", member.name)
        invoice = f.create_test_sales_invoice(
            customer=customer,
            member=member.name,
            grand_total=15.0,
            submit=True,
        )

        result = s.load_unpaid_invoices_secure(date_range="all", limit=500)
        names = {r.get("invoice") for r in result}
        self.assertIn(
            invoice.name,
            names,
            "a real member's invoice missing only its dues-schedule link must stay visible",
        )
        match = next(r for r in result if r.get("invoice") == invoice.name)
        self.assertEqual(match["membership"], "")
        self.assertIn("no membership dues schedule", match["unbatchable_reason"].lower())

    def test_non_eur_invoice_is_excluded_from_the_picker(self):
        data = self._build_member_with_invoice(first_name="SecNonEurPicker")
        frappe.db.set_value(
            "Sales Invoice", data["invoice"].name, "currency", "USD", update_modified=False
        )

        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(data), limit=500
        )
        names = {r.get("invoice") for r in result}
        self.assertNotIn(
            data["invoice"].name, names, "a non-EUR invoice must not be offered as a SEPA candidate"
        )

    def test_a_real_dues_invoice_is_still_offered(self):
        data = self._build_member_with_invoice(first_name="SecEligibilityControl")
        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(data), limit=500
        )
        names = {r.get("invoice") for r in result}
        self.assertIn(data["invoice"].name, names)


class TestLoadUnpaidInvoicesSecureTotalEligibleCount(SecureBase):
    """#1219: same truncation-visibility fix as the non-secure twin; see
    TestLoadUnpaidInvoicesTotalEligibleCount (test_sepa_batch_ui.py)."""

    def test_total_eligible_equals_page_length_when_not_truncated(self):
        data = self._build_member_with_invoice(first_name="SecTotalNoTrunc")
        frappe.local.response.pop("total_eligible", None)

        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(data), limit=500
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(frappe.local.response.get("total_eligible"), 1)

    def test_total_eligible_reports_truncation_when_limit_caps_the_page(self):
        data = self._build_member_with_invoice(first_name="SecTotalTrunc")
        f = self.factory
        f.create_test_sales_invoice(
            customer=data["customer"],
            member=data["member"].name,
            membership=data["membership"].name,
            membership_dues_schedule_display=data["schedule"].name,
            due_date=add_days(today(), 20),
            grand_total=25.0,
            submit=True,
        )
        f.create_test_sales_invoice(
            customer=data["customer"],
            member=data["member"].name,
            membership=data["membership"].name,
            membership_dues_schedule_display=data["schedule"].name,
            due_date=add_days(today(), 21),
            grand_total=25.0,
            submit=True,
        )
        membership_type = self._dues_schedule_membership_type(data)
        frappe.local.response.pop("total_eligible", None)

        result = s.load_unpaid_invoices_secure(date_range="all", membership_type=membership_type, limit=2)
        self.assertEqual(len(result), 2, "page must be capped at the limit")
        self.assertEqual(
            frappe.local.response.get("total_eligible"),
            3,
            "must report the true eligible count, not the truncated page size",
        )

    def test_total_eligible_is_zero_when_membership_type_matches_no_schedules(self):
        # The secure endpoint pre-checks `frappe.db.exists("Membership Type", ...)`
        # (unlike the non-secure twin), so an arbitrary nonexistent name would
        # raise SEPAError instead of exercising the "zero schedules" branch. Use
        # a real, freshly created Membership Type that no schedule references.
        from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists

        mt_name = ensure_membership_type_exists(f"SecZeroEligible-{frappe.generate_hash(length=6)}")
        frappe.local.response.pop("total_eligible", None)

        result = s.load_unpaid_invoices_secure(date_range="all", membership_type=mt_name, limit=500)
        self.assertEqual(result, [])
        self.assertEqual(frappe.local.response.get("total_eligible"), 0)


class TestLoadUnpaidInvoicesSecureExcludesAlreadyBatched(SecureBase):
    """#1217: `load_unpaid_invoices_secure` shares the non-secure loader's query
    shape and the same omission (confirmed in the issue, not independently
    re-measured there) -- same rule, same fix, own tests.

    Unlike the non-secure loader, this endpoint is NOT `@handle_api_error`-wrapped,
    so an unexpected exception here propagates directly to the caller rather than
    becoming an OperationResult dict.
    """

    def test_invoice_in_submitted_batch_is_excluded(self):
        chain = self._build_member_with_invoice(first_name="SecSubExcl")
        put_invoice_in_batch(self, chain, status="Submitted", force_docstatus=1)

        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(chain), limit=500
        )
        names = {r.get("invoice") for r in result}
        self.assertNotIn(
            chain["invoice"].name,
            names,
            "invoice already in a submitted, open batch must not be offered again",
        )

    def test_invoice_in_cancelled_batch_is_available_again(self):
        chain = self._build_member_with_invoice(first_name="SecCancelAvail")
        put_invoice_in_batch(self, chain, status="Cancelled", force_docstatus=2)

        result = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(chain), limit=500
        )
        names = {r.get("invoice") for r in result}
        self.assertIn(
            chain["invoice"].name, names, "a cancelled batch must not permanently block re-collection"
        )

    def test_exclusion_lookup_failure_fails_closed(self):
        """Not `@handle_api_error`-wrapped: an unexpected exception must propagate
        (never be swallowed into an unfiltered invoice list)."""
        chain = self._build_member_with_invoice(first_name="SecFailClosed")
        put_invoice_in_batch(self, chain, status="Submitted", force_docstatus=1)

        with patch.object(
            s, "get_open_batch_invoice_names", side_effect=RuntimeError("simulated lookup failure")
        ):
            with self.assertRaises(RuntimeError):
                s.load_unpaid_invoices_secure(
                    date_range="all", membership_type=self._dues_schedule_membership_type(chain), limit=500
                )


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

    def test_sql_does_not_alias_dues_schedule_display_as_membership(self):
        """#1252: mirrors the same rename in the non-secure twin
        (test_sepa_batch_ui.py::TestGetInvoiceMandateInfo). The old alias never
        leaked to any caller, so this is a naming/structural check, not a
        behavioural one -- see the control test below."""
        source = inspect.getsource(s.get_invoice_mandate_info_secure)
        self.assertNotIn("as membership", source)
        self.assertIn("as dues_schedule", source)

    def test_still_resolves_mandate_after_rename(self):
        """Control for the rename above: it must not change behaviour for a real,
        valid chain (same assertions as test_valid_invoice)."""
        data = self._build_member_with_invoice(first_name="SecMandInfoRenameControl")
        result = s.get_invoice_mandate_info_secure(data["invoice"].name)
        self.assertTrue(result["valid"])
        self.assertEqual(result["mandate_reference"], data["mandate"].mandate_id)


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


class TestLoadUnpaidInvoicesSecureResolvesRealMembership(SecureBase):
    """#1239, twin half: the `_secure` loader must emit a Membership, not a schedule.

    #1227 gave this endpoint the non-secure twin's `membership` alias to restore
    parity. #1239 then established the alias was wrong in BOTH: it put a Membership
    Dues Schedule name into a key that `Direct Debit Batch Invoice.membership`
    (Link -> Membership, reqd) consumes. Fixing only the non-secure twin would have
    left these two divergent for the third time (#1227, #1244), so both resolve the
    real Membership from `Membership Dues Schedule.membership` -- the link
    `create_sepa_batch_validated` documents as AUTHORITATIVE.
    """

    def test_loaded_row_carries_the_membership_not_the_dues_schedule(self):
        data = self._build_member_with_invoice(first_name="SecRealMembership")
        expected = frappe.db.get_value("Membership Dues Schedule", data["schedule"].name, "membership")
        self.assertTrue(expected, "fixture precondition: the schedule must name a Membership")
        self.assertNotEqual(
            expected,
            data["schedule"].name,
            "fixture precondition: the names must differ, or the alias bug is invisible",
        )

        rows = s.load_unpaid_invoices_secure(
            date_range="all", membership_type=self._dues_schedule_membership_type(data), limit=500
        )
        match = next((r for r in rows if r.get("invoice") == data["invoice"].name), None)
        self.assertIsNotNone(match, "freshly created unpaid invoice should be loaded")
        self.assertEqual(match["membership"], expected)
        self.assertNotEqual(match["membership"], match["dues_schedule"])

    def test_the_two_twins_return_the_same_membership_for_the_same_invoice(self):
        """Parity is the property that keeps regressing, so assert it directly."""
        from verenigingen.verenigingen_payments.api import sepa_batch_ui as nonsec

        data = self._build_member_with_invoice(first_name="SecTwinParity")
        mtype = self._dues_schedule_membership_type(data)

        secure_rows = s.load_unpaid_invoices_secure(date_range="all", membership_type=mtype, limit=500)
        plain_rows = nonsec.load_unpaid_invoices(date_range="all", membership_type=mtype, limit=500)

        def pick(rows):
            return next((r for r in rows if r.get("invoice") == data["invoice"].name), None)

        a, b = pick(secure_rows), pick(plain_rows)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a["membership"], b["membership"])
        self.assertEqual(a["dues_schedule"], b["dues_schedule"])
        self.assertEqual(a["unbatchable_reason"], b["unbatchable_reason"])
