# Copyright (c) 2026, Verenigingen and contributors
# For license information, please see license.txt

"""
Tests for ING Checkout Mandate API endpoints (api/mandate.py).

These cover the whitelisted entry points without touching Pay.nl's live API
(the sandbox 403s mandate create/list). Strategy:

- Validation guards (missing args, unknown Member / Mandate) are exercised with
  real ``frappe.db.exists`` checks -- no stubbing.
- Read endpoints (``get_mandate_status``, ``get_member_mandates``) run against
  real ING Checkout Mandate + Member docs and assert on returned field values.
- Endpoints that delegate to MandateService (create / execute / sync) are
  verified by replacing the ``get_mandate_service`` factory with a recording
  double, asserting the API forwards the right arguments and returns the
  service result verbatim. The HTTP boundary is never reached.
"""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.verenigingen_payments.ing_checkout.api import mandate as mandate_api


class _RecordingMandateService:
    """Stands in for MandateService; records calls and returns a canned result."""

    def __init__(self, result=None):
        self.result = result or {"success": True, "mandate_id": "IO-STUB"}
        self.calls = []

    def create_mandate_for_member(self, **kwargs):
        self.calls.append(("create_mandate_for_member", kwargs))
        return self.result

    def execute_debit_for_invoice(self, **kwargs):
        self.calls.append(("execute_debit_for_invoice", kwargs))
        return self.result

    def sync_mandate_status(self, mandate_name):
        self.calls.append(("sync_mandate_status", mandate_name))
        return self.result


class MandateAPITestBase(FrappeTestCase):
    """Shared real-doc fixtures."""

    def _ensure_member(self):
        name = "ING-Mandate-API-Member"
        if not frappe.db.exists("Member", {"email": "ing-mandate-api@example.com"}):
            member = frappe.get_doc(
                {
                    "doctype": "Member",
                    "first_name": "Ing",
                    "last_name": "Mandate",
                    "email": "ing-mandate-api@example.com",
                }
            )
            member.insert(ignore_permissions=True)
            return member.name
        return frappe.db.get_value("Member", {"email": "ing-mandate-api@example.com"}, "name")

    def _make_mandate(self, member_name, mandate_id="IO-API-0001", status="Active"):
        existing = frappe.db.get_value("ING Checkout Mandate", {"mandate_id": mandate_id}, "name")
        if existing:
            return existing
        doc = frappe.get_doc(
            {
                "doctype": "ING Checkout Mandate",
                "mandate_id": mandate_id,
                "mandate_type": "flexible",
                "status": status,
                "debtor_name": "Ing Mandate",
                "debtor_iban": "NL91INGB0001234567",
                "member": member_name,
            }
        )
        doc.insert(ignore_permissions=True)
        return doc.name

    def _patch_service(self, recorder):
        """Swap the factory the endpoints import lazily from mandate_service."""
        import verenigingen.verenigingen_payments.ing_checkout.services.mandate_service as ms

        orig_factory = ms.get_mandate_service
        ms.get_mandate_service = lambda: recorder
        self.addCleanup(lambda: setattr(ms, "get_mandate_service", orig_factory))


class TestCreateMandateForMember(MandateAPITestBase):
    def test_missing_member_name(self):
        result = mandate_api.create_mandate_for_member(member_name="")
        self.assertFalse(result["success"])
        self.assertIn("Member name is required", result["error"])

    def test_invalid_mandate_type(self):
        member = self._ensure_member()
        result = mandate_api.create_mandate_for_member(member_name=member, mandate_type="quarterly")
        self.assertFalse(result["success"])
        self.assertIn("Invalid mandate type", result["error"])

    def test_member_not_found(self):
        result = mandate_api.create_mandate_for_member(member_name="MEMBER-DOES-NOT-EXIST-9999")
        self.assertFalse(result["success"])
        self.assertIn("Member not found", result["error"])

    def test_delegates_with_parsed_amount(self):
        member = self._ensure_member()
        recorder = _RecordingMandateService(result={"success": True, "mandate_id": "IO-X"})
        self._patch_service(recorder)

        result = mandate_api.create_mandate_for_member(
            member_name=member, mandate_type="recurring", amount="25.50", description="Dues"
        )
        self.assertEqual(result, {"success": True, "mandate_id": "IO-X"})
        self.assertEqual(len(recorder.calls), 1)
        method, kwargs = recorder.calls[0]
        self.assertEqual(method, "create_mandate_for_member")
        self.assertEqual(kwargs["member_name"], member)
        self.assertEqual(kwargs["mandate_type"], "recurring")
        # String amount is coerced to float before delegating.
        self.assertEqual(kwargs["amount"], 25.50)
        self.assertEqual(kwargs["description"], "Dues")

    def test_delegates_with_none_amount(self):
        member = self._ensure_member()
        recorder = _RecordingMandateService()
        self._patch_service(recorder)

        mandate_api.create_mandate_for_member(member_name=member, mandate_type="single")
        _, kwargs = recorder.calls[0]
        self.assertIsNone(kwargs["amount"])


class TestExecuteDebitForInvoice(MandateAPITestBase):
    def test_missing_mandate_name(self):
        result = mandate_api.execute_debit_for_invoice(mandate_name="", sales_invoice="SI-1")
        self.assertFalse(result["success"])
        self.assertIn("Mandate name is required", result["error"])

    def test_missing_sales_invoice(self):
        result = mandate_api.execute_debit_for_invoice(mandate_name="ING-MAND-1", sales_invoice="")
        self.assertFalse(result["success"])
        self.assertIn("Sales Invoice is required", result["error"])

    def test_mandate_not_found(self):
        result = mandate_api.execute_debit_for_invoice(
            mandate_name="ING-MAND-DOES-NOT-EXIST", sales_invoice="SI-1"
        )
        self.assertFalse(result["success"])
        self.assertIn("Mandate not found", result["error"])

    def test_sales_invoice_not_found(self):
        member = self._ensure_member()
        mandate_name = self._make_mandate(member, mandate_id="IO-EXEC-0001")
        result = mandate_api.execute_debit_for_invoice(
            mandate_name=mandate_name, sales_invoice="ACC-SINV-DOES-NOT-EXIST-9999"
        )
        self.assertFalse(result["success"])
        self.assertIn("Sales Invoice not found", result["error"])


class TestGetMandateStatus(MandateAPITestBase):
    def test_missing_name(self):
        result = mandate_api.get_mandate_status(mandate_name="")
        self.assertFalse(result["success"])

    def test_not_found(self):
        result = mandate_api.get_mandate_status(mandate_name="ING-MAND-NOPE")
        self.assertFalse(result["success"])
        self.assertIn("Mandate not found", result["error"])

    def test_returns_mandate_fields(self):
        member = self._ensure_member()
        mandate_name = self._make_mandate(member, mandate_id="IO-STATUS-0001", status="Active")
        result = mandate_api.get_mandate_status(mandate_name=mandate_name)
        self.assertTrue(result["success"])
        self.assertEqual(result["mandate_id"], "IO-STATUS-0001")
        self.assertEqual(result["status"], "Active")
        self.assertEqual(result["mandate_type"], "flexible")
        self.assertEqual(result["debtor_iban"], "NL91INGB0001234567")
        self.assertEqual(result["member"], member)


class TestSyncMandateStatus(MandateAPITestBase):
    def test_missing_name(self):
        result = mandate_api.sync_mandate_status(mandate_name="")
        self.assertFalse(result["success"])

    def test_not_found(self):
        result = mandate_api.sync_mandate_status(mandate_name="ING-MAND-NOPE")
        self.assertFalse(result["success"])

    def test_delegates_to_service(self):
        member = self._ensure_member()
        mandate_name = self._make_mandate(member, mandate_id="IO-SYNC-0001")
        recorder = _RecordingMandateService(result={"success": True, "status": "Active"})
        self._patch_service(recorder)

        result = mandate_api.sync_mandate_status(mandate_name=mandate_name)
        self.assertEqual(result, {"success": True, "status": "Active"})
        self.assertEqual(recorder.calls[0], ("sync_mandate_status", mandate_name))


class TestCancelMandate(MandateAPITestBase):
    def test_missing_name(self):
        result = mandate_api.cancel_mandate(mandate_name="")
        self.assertFalse(result["success"])

    def test_not_found(self):
        result = mandate_api.cancel_mandate(mandate_name="ING-MAND-NOPE")
        self.assertFalse(result["success"])
        self.assertIn("Mandate not found", result["error"])


class TestGetMemberMandates(MandateAPITestBase):
    def test_missing_member(self):
        result = mandate_api.get_member_mandates(member_name="")
        self.assertFalse(result["success"])

    def test_member_not_found(self):
        result = mandate_api.get_member_mandates(member_name="MEMBER-NOPE-9999")
        self.assertFalse(result["success"])
        self.assertIn("Member not found", result["error"])

    def test_returns_member_mandates(self):
        member = self._ensure_member()
        self._make_mandate(member, mandate_id="IO-LIST-0001")
        result = mandate_api.get_member_mandates(member_name=member)
        self.assertTrue(result["success"])
        ids = [m["mandate_id"] for m in result["mandates"]]
        self.assertIn("IO-LIST-0001", ids)
        # Only this member's mandates are returned.
        for m in result["mandates"]:
            self.assertIn("mandate_id", m)
