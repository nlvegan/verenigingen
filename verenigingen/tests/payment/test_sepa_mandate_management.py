"""
Real-integration tests for SEPA mandate management endpoints.

Covers verenigingen/verenigingen_payments/api/sepa_mandate_management.py
(previously 0% coverage):

    - create_missing_sepa_mandates (dry-run + real create)
    - fix_specific_member_sepa_mandate (validation + happy path + already-active)
    - periodic_sepa_mandate_child_table_sync (real diagnostics, no auto-fix)
    - detect_sepa_mandate_inconsistencies (real SQL inconsistency scan)

Everything runs against REAL Member / SEPA Mandate / Member SEPA Mandate Link
documents built by the test factory. Nothing is mocked - these endpoints have no
external boundary (no email/HTTP), so a true integration test is appropriate.

The endpoints are decorated @critical_api / @high_security_api / @standard_api and
some perform internal frappe.has_permission checks; the tests run as the default
Administrator user, which satisfies those gates.

Run:
    bench --site test_site_2 run-tests --app verenigingen \
        --module verenigingen.tests.payment.test_sepa_mandate_management
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen_payments.api import sepa_mandate_management as mgmt


class _SepaMemberMixin:
    """Helper to build a member that QUALIFIES for auto-mandate creation:
    SEPA Direct Debit payment method + IBAN + no active mandate."""

    def _make_sepa_member(self, **overrides):
        # Build a checksum-valid Dutch IBAN with a UNIQUE 10-digit account number
        # (the generator's default account number is fixed and would collide).
        from verenigingen.utils.validation.iban_validator import generate_test_iban

        acct = str(abs(hash(frappe.generate_hash(length=12))))[:10].zfill(10)
        unique_iban = generate_test_iban(bank_code="RABO", account_number=acct)
        kwargs = {
            "first_name": "SepaCand",
            "payment_method": "SEPA Direct Debit",
            "iban": unique_iban,
            "bank_account_name": "Test Holder",
        }
        kwargs.update(overrides)
        return self.create_test_member(**kwargs)


class TestCreateMissingSepaMandatesDryRun(_SepaMemberMixin, EnhancedTestCase):
    def test_dry_run_finds_member_without_creating(self):
        member = self._make_sepa_member()
        result = mgmt.create_missing_sepa_mandates(dry_run=True)

        self.assertTrue(result["success"])
        self.assertIn("DRY RUN", result["message"])
        results = result["results"]
        # Our candidate member should appear in the "would create" list.
        member_names = {m["member"] for m in results["mandates"]}
        self.assertIn(member.name, member_names)
        # Dry run creates nothing.
        self.assertEqual(results["created"], 0)
        self.assertFalse(
            frappe.db.exists("SEPA Mandate", {"member": member.name, "status": "Active", "is_active": 1})
        )
        # The "would create" entry uses the dry-run action text.
        entry = next(m for m in results["mandates"] if m["member"] == member.name)
        self.assertEqual(entry["action"], "Would create mandate")

    def test_member_with_active_mandate_excluded(self):
        member = self._make_sepa_member()
        # Give them an active mandate -> they must NOT be picked up.
        self.create_test_sepa_mandate(member=member.name, iban=member.iban)
        result = mgmt.create_missing_sepa_mandates(dry_run=True)
        member_names = {m["member"] for m in result["results"]["mandates"]}
        self.assertNotIn(member.name, member_names)


class TestCreateMissingSepaMandatesRealCreate(_SepaMemberMixin, EnhancedTestCase):
    def test_real_create_makes_active_submitted_mandate(self):
        """The real-create path links a newly-created mandate to the member.

        Regression: the child-link append omitted ``sepa_mandate_doctype`` for the
        Dynamic Link field, so linking failed ("SEPA Mandate DocType must be set
        first") and the member landed in ``results['errors']`` instead of
        ``results['created']``. The append now sets ``sepa_mandate_doctype``.
        """
        member = self._make_sepa_member()
        result = mgmt.create_missing_sepa_mandates(dry_run=False)
        self.assertTrue(result["success"])

        # Correct behaviour: the member's mandate creation succeeds (no error).
        errors_for_member = [e for e in result["results"]["errors"] if e["member"] == member.name]
        self.assertEqual(
            errors_for_member,
            [],
            msg=f"PRODUCT BUG: mandate creation errored: {errors_for_member}",
        )

        # A real, active, submitted mandate now exists for the member.
        mandate_name = frappe.db.get_value(
            "SEPA Mandate", {"member": member.name, "status": "Active", "is_active": 1}, "name"
        )
        self.assertIsNotNone(mandate_name, "expected an active mandate to be created")
        mandate = frappe.get_doc("SEPA Mandate", mandate_name)
        self.assertEqual(mandate.docstatus, 1)  # submitted
        self.assertEqual(mandate.mandate_type, "RCUR")
        self.assertEqual(mandate.iban, member.iban)


class TestFixSpecificMemberSepaMandate(_SepaMemberMixin, EnhancedTestCase):
    def test_empty_member_name_raises(self):
        with self.assertRaises(frappe.ValidationError):
            mgmt.fix_specific_member_sepa_mandate(member_name="")

    def test_nonexistent_member_raises(self):
        with self.assertRaises(frappe.ValidationError):
            mgmt.fix_specific_member_sepa_mandate(member_name="Assoc-Member-NONEXISTENT-9999")

    def test_member_without_iban_raises(self):
        # Create a normal member first (the Member DocType refuses to save a SEPA
        # Direct Debit member without an IBAN), then strip the IBAN and flip the
        # payment method directly at the DB level to reach the endpoint's own
        # "Member does not have an IBAN" guard.
        member = self.create_test_member(first_name="NoIban")
        frappe.db.set_value(
            "Member", member.name, {"payment_method": "SEPA Direct Debit", "iban": ""}
        )
        with self.assertRaises(frappe.ValidationError):
            mgmt.fix_specific_member_sepa_mandate(member_name=member.name)

    def test_member_wrong_payment_method_raises(self):
        member = self._make_sepa_member(payment_method="Bank Transfer")
        with self.assertRaises(frappe.ValidationError):
            mgmt.fix_specific_member_sepa_mandate(member_name=member.name)

    def test_already_active_mandate_returns_failure_message(self):
        member = self._make_sepa_member()
        self.create_test_sepa_mandate(member=member.name, iban=member.iban)
        result = mgmt.fix_specific_member_sepa_mandate(member_name=member.name)
        self.assertFalse(result["success"])
        self.assertIn("already has an active", result["message"].lower())

    def test_happy_path_creates_mandate(self):
        """fix_specific_member_sepa_mandate (delegates to create_missing_sepa_mandates)
        creates and links a mandate for an eligible member.

        Regression: the appended child row omitted the Dynamic Link's
        ``sepa_mandate_doctype``, so the link failed and the endpoint returned
        success=False. Now fixed.
        """
        member = self._make_sepa_member()
        result = mgmt.fix_specific_member_sepa_mandate(member_name=member.name)
        self.assertTrue(result["success"], msg=result.get("message"))
        self.assertIn("mandate_id", result)
        # A real active mandate now exists.
        self.assertTrue(
            frappe.db.exists("SEPA Mandate", {"member": member.name, "status": "Active", "is_active": 1})
        )


class TestPeriodicSepaMandateSync(EnhancedTestCase):
    """periodic_sepa_mandate_child_table_sync delegates to the real diagnostics
    page and reports (does NOT auto-fix)."""

    def test_returns_structured_summary(self):
        result = mgmt.periodic_sepa_mandate_child_table_sync()
        self.assertTrue(result["success"], msg=result.get("error"))
        results = result["results"]
        # Structural keys present.
        for key in ("total_issues", "unique_members", "high_severity_issues", "issue_breakdown", "message"):
            self.assertIn(key, results)
        self.assertIsInstance(results["issue_breakdown"], dict)
        # alert_sent reflects whether high-severity issues were found.
        self.assertIn("alert_sent", results)
        if results["high_severity_issues"] > 0:
            self.assertTrue(results["alert_sent"])
        else:
            self.assertFalse(results["alert_sent"])

    def test_detects_missing_child_table_entry_as_high_severity(self):
        # Create a member with a mandate, then delete the auto-created child-table
        # link so the member has a mandate but no link -> the
        # "missing_child_table_entries" (high severity) diagnostic should fire.
        member = self.create_test_member(first_name="OrphanLink")
        self.create_test_sepa_mandate(member=member.name)
        # SEPA Mandate.after_insert auto-creates the child link; remove it at the
        # DB level to construct the "missing link" condition the diagnostic scans.
        frappe.db.delete("Member SEPA Mandate Link", {"parent": member.name})
        frappe.db.commit()

        result = mgmt.periodic_sepa_mandate_child_table_sync()
        self.assertTrue(result["success"])
        breakdown = result["results"]["issue_breakdown"]
        self.assertIn("missing_child_table_entries", breakdown)
        # missing_child_table_entries is classified high severity.
        self.assertEqual(breakdown["missing_child_table_entries"]["severity"], "high")
        # At least our member contributes to the count.
        self.assertGreaterEqual(breakdown["missing_child_table_entries"]["count"], 1)


class TestDetectSepaMandateInconsistencies(EnhancedTestCase):
    def test_returns_all_issue_categories(self):
        result = mgmt.detect_sepa_mandate_inconsistencies()
        self.assertTrue(result["success"], msg=result.get("error"))
        issues = result["issues"]
        for key in (
            "missing_child_table_entries",
            "orphaned_child_table_entries",
            "outdated_child_table_data",
            "multiple_current_mandates",
            "active_mandates_not_current",
        ):
            self.assertIn(key, issues)
            self.assertIsInstance(issues[key], list)
        # total_issues equals the sum of category lengths.
        self.assertEqual(
            result["total_issues"], sum(len(v) for v in issues.values())
        )

    def test_detects_missing_child_table_entry(self):
        member = self.create_test_member(first_name="DetectMissing")
        self.create_test_sepa_mandate(member=member.name)
        # SEPA Mandate.after_insert auto-creates a child link; delete it so the
        # member has a mandate but no link -> missing_child_table_entries.
        frappe.db.delete("Member SEPA Mandate Link", {"parent": member.name})
        frappe.db.commit()

        result = mgmt.detect_sepa_mandate_inconsistencies()
        missing = result["issues"]["missing_child_table_entries"]
        member_names = {row["name"] for row in missing}
        self.assertIn(member.name, member_names)

    def test_detects_multiple_current_mandates(self):
        member = self.create_test_member(first_name="MultiCurrent")
        # Two Active mandates on one member is still legitimate since #584 -- for
        # DIFFERENT purposes. That is the state this diagnostic is about: both child
        # links flagged is_current, which nothing in the app can then tell apart.
        m1 = self.create_test_sepa_mandate(member=member.name)
        m2 = self.create_test_sepa_mandate(
            member=member.name, used_for_memberships=0, used_for_donations=1
        )
        # Add two child links both flagged current -> multiple_current_mandates.
        # The Dynamic Link requires sepa_mandate_doctype to be set explicitly.
        member.reload()
        for mref in (m1, m2):
            member.append(
                "sepa_mandates",
                {
                    "sepa_mandate": mref.name,
                    "sepa_mandate_doctype": "SEPA Mandate",
                    "mandate_reference": mref.mandate_id,
                    "is_current": 1,
                    "status": "Active",
                    "valid_from": frappe.utils.today(),
                },
            )
        member.save()

        result = mgmt.detect_sepa_mandate_inconsistencies()
        multi = result["issues"]["multiple_current_mandates"]
        member_names = {row["member"] for row in multi}
        self.assertIn(member.name, member_names)
