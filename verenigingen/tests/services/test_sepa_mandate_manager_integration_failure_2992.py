"""#2992: create_mandate must not report a clean success when the member-integration step failed.

``SEPA Mandate.after_insert`` / ``on_update`` run the lifecycle service, whose member integration
step contains an ordinary (non-lock) error and returns ``success: False``; the hooks only
``msgprint`` it, so ``create_mandate`` returned "created successfully" with no trace of the
failure. The mandate row and its ``Member SEPA Mandate Link`` row DO persist in that case
(measured in the issue; asserted below), so the right outcome is to keep ``valid=True`` and
surface the failure as ``data["warnings"]`` plus a message that no longer says "successfully".
The fault is injected at the DB driver on ``UPDATE tabMember`` (the issue's own measurement).
"""

from unittest.mock import patch

import frappe

from verenigingen.services.payment.sepa_mandate_manager import get_sepa_mandate_manager
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.utils.validation.iban_validator import generate_test_iban


class TestCreateMandateIntegrationFailure2992(EnhancedTestCase):
    def setUp(self):
        super().setUp()
        self.manager = get_sepa_mandate_manager()
        self.member = self.create_test_member(
            first_name="Integ",
            last_name="Fail",
            birth_date="1990-01-01",
            email=f"integ.fail.{frappe.generate_hash(length=8)}@example.com",
        )
        self.iban = generate_test_iban("RABO", "0123456789")

    def _create(self):
        return self.manager.create_mandate(
            member=self.member.name,
            iban=self.iban,
            account_holder_name="Integ Fail",
            mandate_id=f"M-2992-{frappe.generate_hash(length=8)}",
        )

    def _fail_member_update(self):
        cursor_cls = frappe.db._cursor.__class__
        real_execute = cursor_cls.execute

        def execute(cursor, query, *args, **kwargs):
            if isinstance(query, str) and query.lstrip().upper().startswith("UPDATE") and "`tabMember`" in query:
                raise frappe.db.OperationalError(1064, "injected at the driver")
            return real_execute(cursor, query, *args, **kwargs)

        # Mock justified: fault injection at the driver; calls through for every other statement
        return patch.object(cursor_cls, "execute", execute)

    def _link_rows(self, mandate_name):
        return frappe.get_all(
            "Member SEPA Mandate Link",
            filters={"parent": self.member.name, "sepa_mandate": mandate_name},
            pluck="name",
        )

    def test_integration_failure_is_surfaced_to_the_caller(self):
        self.expectErrorLog("SEPA Mandate Member Integration Error")
        with self._fail_member_update():
            result = self._create()
        # The mandate and its link persisted, so this stays a (qualified) success...
        self.assertTrue(result.valid, result.message)
        self.assertTrue(frappe.db.exists("SEPA Mandate", result.data["mandate_name"]))
        self.assertEqual(len(self._link_rows(result.data["mandate_name"])), 1)
        # ...but the caller is told, and the message does not claim a clean success.
        self.assertTrue(result.data.get("warnings"), "integration failure was swallowed")
        self.assertTrue(any("injected at the driver" in w for w in result.data["warnings"]))
        self.assertNotIn("created successfully", result.message)

    def test_clean_creation_has_no_warnings_and_keeps_the_success_message(self):
        """Control: no fault, so no warnings key content and the original message."""
        result = self._create()
        self.assertTrue(result.valid, result.message)
        self.assertFalse(result.data.get("warnings"))
        self.assertIn("created successfully", result.message)
        self.assertEqual(len(self._link_rows(result.data["mandate_name"])), 1)
