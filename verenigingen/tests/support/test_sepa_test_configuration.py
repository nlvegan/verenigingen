"""Pins for the shared SEPA test-configuration helper (#513, #466).

Both issues are the same defect: a ``setUpClass`` that configures a Single inside
a ``try/except``, where the configuration had never once succeeded and the
``except`` made it invisible. Two properties have to hold for that to be fixed,
and each of these tests damages the site first so it cannot pass on state a
previous run left behind:

1. the configuration lands even when the Single holds a dangling ``webhook_user``
   Link -- #513's proximate cause, and the reason all 12 setup attempts in a
   14-test run failed;
2. a fieldname that does not exist is *reported*, not silently written -- #466's
   cause, where four fields were assigned on the wrong doctype and Frappe
   accepted every one of them as a no-op.

Damage-first matters here more than usual. On any warm test site the SEPA fields
are already set to exactly the values the helper writes, so an assertion that
merely reads them back is green against the broken code and proves nothing.

Base class note: plain ``FrappeTestCase``, matching
``tests/support/test_sepa_test_company``. ``EnhancedTestCase.setUp`` runs the
once-per-session seeding block, which mutates the very Singles these tests are
reasoning about. The test-quality enforcer warns about this; the warning is
expected.

Usage::

    bench --site test_site_4 run-tests --app verenigingen \
        --module verenigingen.tests.support.test_sepa_test_configuration
"""

import ast
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.tests.support.sepa_test_configuration import (
    PAYMENTS_SETTINGS,
    SEPA_TEST_FIELDS,
    SETTINGS,
    SEPAConfigurationNotApplied,
    _write_single,
    apply_sepa_test_configuration,
    verify_sepa_configuration,
)

# A User that cannot exist, planted in Verenigingen Payments Settings.webhook_user
# to reproduce #513's precondition.
_GHOST_WEBHOOK_USER = "webhook-user-513-pin@example.invalid"


class TestSEPATestConfiguration(FrappeTestCase):
    """The helper five test classes now share, pinned at both failure modes."""

    def setUp(self):
        super().setUp()
        self._original = {
            (PAYMENTS_SETTINGS, "webhook_user"): frappe.db.get_single_value(
                PAYMENTS_SETTINGS, "webhook_user"
            ),
            (SETTINGS, "company"): frappe.db.get_single_value(SETTINGS, "company"),
        }
        for fieldname in SEPA_TEST_FIELDS[PAYMENTS_SETTINGS]:
            self._original[(PAYMENTS_SETTINGS, fieldname)] = frappe.db.get_single_value(
                PAYMENTS_SETTINGS, fieldname
            )
        self.addCleanup(self._restore)

    def _restore(self):
        for (doctype, fieldname), value in self._original.items():
            frappe.db.set_single_value(doctype, fieldname, value)
        # Committed: these writes have to outlive the class-level rollback, or the
        # damage this module plants is what the next module in the shard inherits.
        frappe.db.commit()
        frappe.clear_document_cache(SETTINGS, SETTINGS)
        frappe.clear_document_cache(PAYMENTS_SETTINGS, PAYMENTS_SETTINGS)

    @staticmethod
    def _blank_sepa_fields():
        """Clear the values the helper is supposed to write.

        Without this the assertions below are satisfied by whatever an earlier run
        left on the site -- which is exactly how the broken helpers stayed green.
        """
        for fieldname in SEPA_TEST_FIELDS[PAYMENTS_SETTINGS]:
            frappe.db.set_single_value(PAYMENTS_SETTINGS, fieldname, None)
        frappe.db.commit()

    # ---- #513: a dangling Link in a field this configuration does not own ----

    def test_configuration_lands_despite_a_dangling_webhook_user(self):
        """#513: the Single's webhook_user pointed at a deleted User, so save()
        failed link validation before reaching any SEPA field -- 12 times in a
        14-test run, silently."""
        self._blank_sepa_fields()
        frappe.db.set_single_value(PAYMENTS_SETTINGS, "webhook_user", _GHOST_WEBHOOK_USER)
        frappe.db.commit()
        # Preconditions: the damage is real, or this test proves nothing.
        self.assertFalse(
            frappe.db.exists("User", _GHOST_WEBHOOK_USER), "precondition: the link must dangle"
        )
        self.assertFalse(frappe.db.get_single_value(PAYMENTS_SETTINGS, "creditor_id"))

        company = apply_sepa_test_configuration()

        for fieldname, value in SEPA_TEST_FIELDS[PAYMENTS_SETTINGS].items():
            self.assertEqual(frappe.db.get_single_value(PAYMENTS_SETTINGS, fieldname), value)
        self.assertEqual(frappe.db.get_single_value(SETTINGS, "company"), company)

    def test_configuration_lands_from_a_blanked_single(self):
        """The baseline the test above needs: with no damage other than blank
        fields, the helper writes all of them and reports the company."""
        self._blank_sepa_fields()
        company = apply_sepa_test_configuration()
        self.assertTrue(frappe.db.exists("Company", company))
        # Must not raise: this is the same check the helper runs on itself.
        verify_sepa_configuration(company)

    # ---- #466: a field that does not exist ---------------------------------

    def test_every_field_the_helper_writes_exists_on_its_doctype(self):
        """#466: four fields were assigned on Verenigingen Settings that do not
        exist there (sepa_creditor_id, company_iban, company_bic,
        enable_strict_sepa_validation). Frappe accepts every one as a no-op."""
        for doctype, values in SEPA_TEST_FIELDS.items():
            meta = frappe.get_meta(doctype)
            for fieldname in values:
                self.assertIsNotNone(
                    meta.get_field(fieldname), f"{doctype} has no field {fieldname!r}"
                )

    def test_a_field_that_does_not_exist_is_raised_not_written(self):
        """The guard that makes #466 impossible to repeat.

        Pinned through the real write path. Measured on test_site_4, the three
        write paths disagree about a nonexistent field: ``doc.attr = value`` is a
        silent no-op (#466's actual path), ``frappe.db.set_single_value`` writes
        the row with no error at all, and only ``get_single_value`` raises. So
        neither of the write paths reports it, and the meta check is what has to.
        """
        with self.assertRaises(SEPAConfigurationNotApplied) as caught:
            _write_single(SETTINGS, {"sepa_creditor_id": "NL12ZZZ123456789"})
        self.assertIn("sepa_creditor_id", str(caught.exception))
        # And no tabSingles row was written for it. Asserted with raw SQL because
        # get_single_value on a nonexistent field raises rather than returning
        # None, which would mask the difference between "not written" and "wrote
        # junk".
        rows = frappe.db.sql(
            "select count(*) from tabSingles where doctype = %s and field = %s",
            (SETTINGS, "sepa_creditor_id"),
        )[0][0]
        self.assertEqual(rows, 0)

    def test_a_link_that_points_nowhere_is_raised_not_written(self):
        """#466's other half: company = "Test Vereniging", a Company that does
        not exist. That was the one assignment which was NOT a no-op, and the
        LinkValidationError it raised is what took the whole helper down."""
        self.assertFalse(
            frappe.db.exists("Company", "Test Vereniging"),
            "precondition: #466's hardcoded company must still not exist",
        )
        with self.assertRaises(SEPAConfigurationNotApplied) as caught:
            _write_single(SETTINGS, {"company": "Test Vereniging"})
        self.assertIn("Test Vereniging", str(caught.exception))

    def test_a_value_that_did_not_land_is_reported(self):
        """The read-back guard: verify_sepa_configuration must fail loudly when
        the site does not hold what the helper intended."""
        self._blank_sepa_fields()
        with self.assertRaises(SEPAConfigurationNotApplied) as caught:
            verify_sepa_configuration("some-company")
        self.assertIn("creditor_id", str(caught.exception))

    # ---- the class, not the instance ---------------------------------------

    def test_no_caller_wraps_the_shared_helper_in_a_try(self):
        """Every caller must let a setup failure fail the class.

        This is a SOURCE-SHAPE check, and it is worth being explicit about what it
        does not do: it does not prove any caller's configuration is correct, only
        that nobody has re-introduced the swallow this fix removed. It scans every
        file under verenigingen/ that mentions the helper, so a NEW caller is
        covered without being named here -- the allowlist-that-covers-nothing
        failure mode (#485) does not apply.
        """
        offenders = []
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for dirpath, dirnames, filenames in os.walk(root):
            if "node_modules" in dirpath or "__pycache__" in dirpath:
                continue
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                with open(path, encoding="utf-8") as handle:
                    source = handle.read()
                if "apply_sepa_test_configuration" not in source:
                    continue
                for node in ast.walk(ast.parse(source)):
                    if not isinstance(node, ast.Try):
                        continue
                    for child in ast.walk(node):
                        if (
                            isinstance(child, ast.Call)
                            and isinstance(child.func, ast.Name)
                            and child.func.id == "apply_sepa_test_configuration"
                        ):
                            offenders.append(f"{os.path.relpath(path, root)}:{child.lineno}")
        self.assertEqual(
            offenders,
            [],
            "apply_sepa_test_configuration must not be called inside a try: a swallowed "
            "setup failure is the whole of #513 and #466",
        )
