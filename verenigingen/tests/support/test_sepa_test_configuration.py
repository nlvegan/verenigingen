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

from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.support.sepa_test_configuration import (
    PAYMENTS_SETTINGS,
    SEPA_TEST_CREDITOR_ID,
    SEPA_TEST_FIELDS,
    SEPA_TEST_IBAN,
    SETTINGS,
    SEPAConfigurationNotApplied,
    _write_single,
    apply_sepa_test_configuration,
    sepa_test_field_values,
    verify_sepa_configuration,
)
from verenigingen.utils.validation.iban_validator import validate_iban

HELPER = "apply_sepa_test_configuration"

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
        self.assertFalse(frappe.db.exists("User", _GHOST_WEBHOOK_USER), "precondition: the link must dangle")
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
        enable_strict_sepa_validation). Frappe accepts every one as a no-op.

        Iterates ``sepa_test_field_values()``, not ``SEPA_TEST_FIELDS``: the
        constant holds only the fixed-value half, so iterating it left the
        ``Verenigingen Settings.company`` write -- the one whose dangling Link is
        #466's other half -- outside the check that exists to catch #466.
        """
        checked = []
        for doctype, values in sepa_test_field_values("irrelevant-for-a-meta-check").items():
            meta = frappe.get_meta(doctype)
            for fieldname in values:
                self.assertIsNotNone(meta.get_field(fieldname), f"{doctype} has no field {fieldname!r}")
                checked.append(f"{doctype}.{fieldname}")
        # Control: iterating the wrong collection is how the company write escaped,
        # so assert it is in scope rather than trusting the loop above ran over it.
        self.assertIn(f"{SETTINGS}.company", checked)

    def test_the_pinned_iban_and_creditor_id_pass_the_validation_the_helper_skips(self):
        """``set_single_value`` skips ``validate()``, which is where the mod-97
        IBAN check on ``company_iban`` lives
        (``VerenigingenPaymentsSettings._validate_sepa_configuration``). Both
        constants are valid today and nothing pinned that, so a future edit to
        either would be written silently and only surface as a SEPA XML failure.
        """
        result = validate_iban(SEPA_TEST_IBAN)
        self.assertTrue(result["valid"], f"SEPA_TEST_IBAN is not a valid IBAN: {result}")
        # The creditor id check in that validator is a soft msgprint on length
        # (8..35), so pin the window rather than a format the app does not enforce.
        self.assertTrue(8 <= len(SEPA_TEST_CREDITOR_ID) <= 35)

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
        the site does not hold what the helper intended.

        The company passed here is the REAL one, and is written first. With a
        placeholder ("some-company") the company check failed too, so the raise
        was consistent with "the blanked fields were reported" and with "only the
        company was" -- and ``assertIn("creditor_id")`` was the only thing
        distinguishing them. Now the blanked fields are the sole possible cause.
        """
        company = get_eur_test_company()
        frappe.db.set_single_value(SETTINGS, "company", company)
        self._blank_sepa_fields()

        with self.assertRaises(SEPAConfigurationNotApplied) as caught:
            verify_sepa_configuration(company)

        message = str(caught.exception)
        self.assertIn("creditor_id", message)
        # ...and the company, which DID land, must not be among the complaints.
        # Matched with the "is" suffix because company_iban / company_bic /
        # company_account_holder all contain the substring "company".
        self.assertNotIn(f"{SETTINGS}.company is", message)

    # ---- the class, not the instance ---------------------------------------

    def test_no_caller_wraps_the_shared_helper_in_a_try(self):
        """Every caller must let a setup failure fail the class.

        This is a SOURCE-SHAPE check, and it is worth being explicit about what it
        does not do: it does not prove any caller's configuration is correct, only
        that nobody has re-introduced the swallow this fix removed. It scans every
        file under verenigingen/ that mentions the helper, so a NEW caller is
        covered without being named here -- the allowlist-that-covers-nothing
        failure mode (#485) does not apply.

        The first version of this check matched only a bare ``Name`` call, which
        missed three shapes -- measured against synthetic files, it caught the
        direct call and nothing else:

        * ``import ... as _apply`` then ``try: _apply()``;
        * ``sepa_test_configuration.apply_sepa_test_configuration()``
          (an ``ast.Attribute`` call);
        * ``try: cls._setup_sepa_configuration()`` where the wrapper is what calls
          the helper -- **the shape all five real callers use**, i.e. the check
          would not have caught the very swallow it was written to prevent.

        It also flagged a handler-less ``try/finally``, which swallows nothing.
        All five shapes are covered by ``_helper_reaching_calls`` below.
        """
        offenders = []
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        for dirpath, _dirnames, filenames in os.walk(root):
            if "node_modules" in dirpath or "__pycache__" in dirpath:
                continue
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                path = os.path.join(dirpath, filename)
                # errors="replace", not strict: a single non-UTF-8 .py anywhere
                # under verenigingen/ made this check ERROR out rather than report
                # anything -- a scan that cannot read a file must not be the thing
                # that fails. A file that survives the marker test is then parsed
                # normally, so real breakage still surfaces.
                with open(path, encoding="utf-8", errors="replace") as handle:
                    source = handle.read()
                if HELPER not in source:
                    continue
                offenders.extend(
                    f"{os.path.relpath(path, root)}:{lineno}" for lineno in _swallowed_helper_calls(source)
                )
        self.assertEqual(
            offenders,
            [],
            "apply_sepa_test_configuration must not be called inside a try: a swallowed "
            "setup failure is the whole of #513 and #466",
        )

    def test_the_try_detector_sees_every_evasion_shape_and_no_clean_one(self):
        """The control for the check above: it has to fire on the direct call plus
        all four shapes that evaded the first version, and stay silent on the three
        that swallow nothing.

        Without this, "offenders == []" is equally consistent with "no caller
        swallows" and with "the detector cannot see the shape they use" -- which
        was literally true of the first version.
        """
        preamble = (
            "from verenigingen.tests.support.sepa_test_configuration import "
            "apply_sepa_test_configuration\n"
        )
        must_fire = {
            "direct call": preamble
            + "try:\n    apply_sepa_test_configuration()\nexcept Exception:\n    pass\n",
            "aliased import": (
                "from verenigingen.tests.support.sepa_test_configuration import "
                "apply_sepa_test_configuration as _apply\n"
                "try:\n    _apply()\nexcept Exception:\n    pass\n"
            ),
            "attribute call": (
                "from verenigingen.tests.support import sepa_test_configuration\n"
                "try:\n    sepa_test_configuration.apply_sepa_test_configuration()\n"
                "except Exception:\n    pass\n"
            ),
            "wrapper method -- the shape every real caller uses": (
                preamble + "class T:\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        try:\n            cls._setup()\n        except Exception:\n            pass\n"
                "    @classmethod\n"
                "    def _setup(cls):\n        apply_sepa_test_configuration()\n"
            ),
            "wrapper two levels deep": (
                preamble + "class T:\n"
                "    @classmethod\n"
                "    def setUpClass(cls):\n"
                "        try:\n            cls._outer()\n        except Exception:\n            pass\n"
                "    @classmethod\n"
                "    def _outer(cls):\n        cls._inner()\n"
                "    @classmethod\n"
                "    def _inner(cls):\n        apply_sepa_test_configuration()\n"
            ),
        }
        must_stay_silent = {
            "no try at all": preamble + "apply_sepa_test_configuration()\n",
            "try/finally with no handler swallows nothing": (
                preamble + "try:\n    apply_sepa_test_configuration()\nfinally:\n    pass\n"
            ),
            "an unrelated try in the same file": (
                preamble + "apply_sepa_test_configuration()\n"
                "try:\n    something_else()\nexcept Exception:\n    pass\n"
            ),
        }
        for label, source in must_fire.items():
            self.assertTrue(_swallowed_helper_calls(source), f"detector missed: {label}")
        for label, source in must_stay_silent.items():
            self.assertEqual(_swallowed_helper_calls(source), [], f"false positive: {label}")


def _names_bound_to_helper(tree):
    """Local names that resolve to the helper, including ``import ... as`` aliases."""
    names = {HELPER}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == HELPER and alias.asname:
                    names.add(alias.asname)
    return names


def _is_helper_call(call, names):
    """A call that lands on the helper, however it was imported.

    ``ast.Attribute`` is matched on the attribute name alone -- ``mod.HELPER()``,
    ``pkg.mod.HELPER()`` -- rather than by resolving the module alias: the name is
    distinctive enough that a false positive would itself be worth looking at.
    """
    if isinstance(call.func, ast.Name):
        return call.func.id in names
    return isinstance(call.func, ast.Attribute) and call.func.attr == HELPER


def _functions_reaching_helper(tree, names):
    """Names of functions/methods in this module whose body reaches the helper.

    Iterated to a fixed point, so a wrapper that calls a wrapper is covered: the
    swallow this ratchet exists to block is one level of indirection, and one
    more level must not be a way out of it.
    """
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    reaching = set()
    while True:
        grown = False
        for fn in functions:
            if fn.name in reaching:
                continue
            if any(_call_reaches_helper(c, names, reaching) for c in _calls_in(fn)):
                reaching.add(fn.name)
                grown = True
        if not grown:
            return reaching


def _calls_in(node):
    return [c for c in ast.walk(node) if isinstance(c, ast.Call)]


def _call_reaches_helper(call, names, reaching):
    if _is_helper_call(call, names):
        return True
    # cls._setup(), self._setup(), type(self)._setup(), bare _setup()
    called = call.func.id if isinstance(call.func, ast.Name) else getattr(call.func, "attr", None)
    return called in reaching


def _swallowed_helper_calls(source):
    """Line numbers of ``try`` blocks that swallow a call reaching the helper.

    A ``try`` with no ``except`` (``try/finally``) is skipped: it swallows nothing,
    and flagging it was a false positive in the first version of this check.
    """
    tree = ast.parse(source)
    names = _names_bound_to_helper(tree)
    reaching = _functions_reaching_helper(tree, names)
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try) or not node.handlers:
            continue
        for call in _calls_in(node):
            if _call_reaches_helper(call, names, reaching):
                lines.append(call.lineno)
    return lines
