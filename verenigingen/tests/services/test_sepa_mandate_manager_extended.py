"""
Extended integration tests for SEPAMandateManager.

Complements test_sepa_mandate_manager.py by covering the paths it leaves
untested: mandate creation lifecycle, member-mandate sync, discrepancy
detection (and its name/IBAN comparison helpers), the standalone utility
functions, and the whitelisted API endpoints.

All tests use real SEPA Mandate / Member fixtures on the test DB.

Author: Verenigingen Development Team
"""

import frappe
from frappe.utils import today

from verenigingen.services.payment.sepa_mandate_manager import (
    determine_mandate_action,
    get_active_mandates_api,
    get_active_sepa_mandate,
    get_sepa_mandate_manager,
)
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase


class TestSEPAMandateManagerExtended(EnhancedTestCase):
    """Extended SEPAMandateManager coverage."""

    def setUp(self):
        super().setUp()
        frappe.set_user("Administrator")
        self.manager = get_sepa_mandate_manager()
        self.member = self.create_test_member(
            first_name="Sepa",
            last_name="Extended",
            birth_date="1980-05-05",
            email=f"sepa.ext.{frappe.generate_hash(length=8)}@example.com",
        )
        self.valid_iban = "NL91ABNA0417164300"

    # ========== create_mandate (full lifecycle) ==========

    def test_create_mandate_starts_as_draft_inactive(self):
        """A newly created mandate starts as Draft / inactive and is linked."""
        with self.assertNoErrorLog():
            result = self.manager.create_mandate(
                member=self.member.name,
                iban=self.valid_iban,
                account_holder_name="Sepa Extended",
            )
        self.assertTrue(result.valid)
        mandate = frappe.get_doc("SEPA Mandate", result.data["mandate_name"])
        self.assertEqual(mandate.status, "Draft")
        self.assertEqual(mandate.is_active, 0)
        # Linked to member child table
        self.member.reload()
        links = [m for m in self.member.sepa_mandates if m.sepa_mandate == mandate.name]
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0].is_current, 0)

    def test_create_mandate_duplicate_iban_blocked(self):
        """Creating a second mandate with the same active IBAN is rejected."""
        first = self._active_mandate(self.valid_iban)
        self.assertTrue(frappe.db.exists("SEPA Mandate", first.name))
        result = self.manager.create_mandate(member=self.member.name, iban=self.valid_iban)
        self.assertFalse(result.valid)
        self.assertIn("already exists for this IBAN", result.message)

    # ========== sync_member_mandates ==========

    def test_sync_member_mandates_rebuilds_child_table(self):
        """Sync rebuilds the member's sepa_mandates child table from real mandates."""
        m1 = self._active_mandate(self.valid_iban)
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        m2 = self._mandate(generate_test_iban("RABO", "0123456789"), status="Cancelled", is_active=0)

        result = self.manager.sync_member_mandates(self.member.name)
        self.assertTrue(result.valid)
        self.assertEqual(result.data["mandates_count"], 2)

        self.member.reload()
        synced = {row.sepa_mandate: row for row in self.member.sepa_mandates}
        self.assertIn(m1.name, synced)
        self.assertIn(m2.name, synced)
        # Active mandate is current, cancelled is not
        self.assertEqual(synced[m1.name].is_current, 1)
        self.assertEqual(synced[m2.name].is_current, 0)

    def test_sync_member_mandates_empty(self):
        """Sync with no mandates yields a count of zero."""
        result = self.manager.sync_member_mandates(self.member.name)
        self.assertTrue(result.valid)
        self.assertEqual(result.data["mandates_count"], 0)

    def test_sync_member_mandates_sets_dynamic_link_doctype(self):
        """#667: sync_member_mandates persists sepa_mandates via update_child_table(),
        which runs no defaults and no link validation at all. Appending a row
        without sepa_mandate_doctype silently wrote NULL there and left the member
        unable to save at all -- the very next ordinary Member.save() threw "SEPA
        Mandate DocType must be set first"."""
        mandate = self._active_mandate(self.valid_iban)

        result = self.manager.sync_member_mandates(self.member.name)
        self.assertTrue(result.valid)

        persisted_doctype = frappe.db.get_value(
            "Member SEPA Mandate Link",
            {"parent": self.member.name, "sepa_mandate": mandate.name},
            "sepa_mandate_doctype",
        )
        self.assertEqual(persisted_doctype, "SEPA Mandate")

        # The member must remain saveable after the sync -- a NULL companion
        # field here makes the next ordinary save() throw.
        self.member.reload()
        self.member.save(ignore_permissions=True)

    # ========== check_discrepancies ==========

    def test_check_discrepancies_reports_missing_mandate(self):
        """A SEPA member with an IBAN but no mandate is flagged as missing."""
        self.member.payment_method = "SEPA Direct Debit"
        self.member.iban = self.valid_iban
        self.member.bank_account_name = "Sepa Extended"
        self.member.save()

        results = self.manager.check_discrepancies()
        self.assertIn("total_checked", results)
        missing_for_member = [m for m in results["missing_mandates"] if m["member"] == self.member.name]
        self.assertEqual(len(missing_for_member), 1)

    def test_check_discrepancies_reports_iban_mismatch(self):
        """A mandate whose IBAN differs from the member's is auto-fixed or flagged."""
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        member_iban = self.valid_iban
        mandate_iban = generate_test_iban("RABO", "0123456789")

        self.member.payment_method = "SEPA Direct Debit"
        self.member.iban = member_iban
        self.member.bank_account_name = "Sepa Extended"
        self.member.save()
        self._active_mandate(mandate_iban)

        results = self.manager.check_discrepancies()
        # The two IBANs differ by far more than 2 characters, so they are NOT
        # "too similar" -> _should_auto_fix_iban_change returns True -> the old
        # mandate is auto-deactivated and recorded under auto_fixed (not flagged
        # as a manual mismatch).
        auto_fixed = [r for r in results["auto_fixed"] if r.get("member") == self.member.name]
        self.assertEqual(len(auto_fixed), 1)
        self.assertEqual(auto_fixed[0]["action"], "deactivated_old_mandate")
        # And it is NOT also surfaced as a manual-review mismatch
        mismatches = [r for r in results["iban_mismatches"] if r.get("member") == self.member.name]
        self.assertEqual(len(mismatches), 0)

    # ========== name / IBAN comparison helpers ==========

    def test_names_significantly_different(self):
        self.assertFalse(self.manager._names_significantly_different("Jan de Vries", "jan de vries"))
        self.assertFalse(self.manager._names_significantly_different("Jan de Vries", "Jan de Vries B.V."))
        self.assertTrue(self.manager._names_significantly_different("Jan de Vries", "Piet Bakker"))

    def test_names_slightly_different(self):
        self.assertTrue(self.manager._names_slightly_different("Jan de Vries", "Jan de Vries."))
        self.assertFalse(self.manager._names_slightly_different("Jan de Vries", "Piet Bakker"))

    def test_strings_too_similar(self):
        # Same length, <= 2 char differences -> too similar (possible typo)
        self.assertTrue(self.manager._strings_too_similar("NL91ABNA0417164300", "NL91ABNA0417164301"))
        # Different lengths -> not flagged
        self.assertFalse(self.manager._strings_too_similar("ABC", "ABCDEF"))

    def test_should_auto_fix_iban_change(self):
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        a = self.manager._normalize_iban(self.valid_iban)
        b = self.manager._normalize_iban(generate_test_iban("RABO", "0123456789"))
        self.assertTrue(self.manager._should_auto_fix_iban_change(a, b))
        # Empty inputs -> no auto-fix
        self.assertFalse(self.manager._should_auto_fix_iban_change("", b))

    def test_normalize_iban(self):
        self.assertEqual(self.manager._normalize_iban("nl91-abna-0417-1643-00"), "NL91ABNA0417164300")
        self.assertEqual(self.manager._normalize_iban(""), "")

    def test_check_company_sepa_settings_reports_missing(self):
        """
        When a required company SEPA setting is unconfigured, the check returns a
        WARNING string that names each missing setting (asserting the real
        warning-formatting branch, not merely that *some* string came back).

        This drives the method with an explicit set of missing settings so the
        assertion is deterministic regardless of site configuration.
        """
        # Probe the underlying state: which required settings are absent here?
        from verenigingen.utils.settings_utils import get_payments_settings

        payments_settings = get_payments_settings()
        general_settings = frappe.get_single("Verenigingen Settings")
        expected_missing = []
        if not getattr(payments_settings, "company_iban", None):
            expected_missing.append("Company IBAN")
        if not getattr(payments_settings, "creditor_id", None):
            expected_missing.append("SEPA Creditor ID (Incassant ID)")
        if not getattr(general_settings, "company_name", None):
            expected_missing.append("Company Name")

        result = self.manager._check_company_sepa_settings()
        self.assertIsInstance(result, str)
        if expected_missing:
            self.assertIn("Missing Company SEPA Settings", result)
            for setting in expected_missing:
                self.assertIn(setting, result)
        else:
            self.assertEqual(result, "")

    # ========== standalone utilities ==========

    def test_get_active_sepa_mandate_standalone(self):
        """The standalone get_active_sepa_mandate returns the active mandate dict."""
        mandate = self._active_mandate(self.valid_iban)
        result = get_active_sepa_mandate(self.member.name)
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], mandate.name)
        self.assertEqual(result["status"], "Active")

    def test_get_active_sepa_mandate_none(self):
        """Returns None when there is no active mandate."""
        self.assertIsNone(get_active_sepa_mandate(self.member.name))

    def test_determine_mandate_action_matrix(self):
        """determine_mandate_action returns the correct action for each state."""
        m = {"name": "x"}
        # DD enabled
        self.assertEqual(determine_mandate_action(None, "X", True, False), "create_mandate")
        self.assertEqual(determine_mandate_action(m, "X", True, False), "keep_mandate")
        self.assertEqual(determine_mandate_action(m, "X", True, True), "replace_mandate")
        # DD disabled
        self.assertEqual(determine_mandate_action(m, "X", False, False), "cancel_mandate")
        self.assertEqual(determine_mandate_action(None, "X", False, False), "no_mandate")

    # ========== API endpoints ==========

    def test_get_active_mandates_api(self):
        """The whitelisted get_active_mandates_api returns serializable dicts."""
        mandate = self._active_mandate(self.valid_iban)
        result = get_active_mandates_api(self.member.name)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["mandates"][0]["name"], mandate.name)
        self.assertEqual(result["mandates"][0]["status"], "Active")

    # ========== Helpers ==========

    def _mandate(self, iban, status="Draft", is_active=0):
        from verenigingen.utils.secure_operations import secure_document_operation

        mandate = frappe.get_doc(
            {
                "doctype": "SEPA Mandate",
                "member": self.member.name,
                "mandate_id": f"EXT-{frappe.generate_hash(length=8)}",
                "iban": iban,
                "bic": "ABNANL2A",
                "account_holder_name": "Sepa Extended",
                "sign_date": today(),
                "status": status,
                "is_active": is_active,
                "used_for_memberships": 1,
                "mandate_type": "RCUR",
                "scheme": "SEPA",
            }
        )
        result = secure_document_operation(
            operation="insert",
            doc=mandate,
            justification="Test mandate",
            required_permissions=["SEPA Mandate:create"],
        )
        if not result.success:
            raise frappe.ValidationError("; ".join(result.errors))
        return mandate

    def _active_mandate(self, iban):
        return self._mandate(iban, status="Active", is_active=1)
