"""`EnhancedTestCase.setUp` must not undo a `Verenigingen Settings.company` a CLASS chose (#528).

`_ensure_verenigingen_settings()` used to re-point the Single at the harness test company
on EVERY test method, so a `setUpClass` that configured it was already undone by the
first test body. Measured on test_site_4 with `test_sepa_xml_compliance`: the value was
`TEST-Payment-Integration-Company` at the end of `setUpClass` and `_Test Company` (whose
leading underscore is outside the SEPA charset) by the first body.

The contract pinned here:

* a company the class itself wrote in `setUpClass` (an existing Company that differs from
  what the Single held when the class began) survives into every test body, together with
  a `dues_income_account` that belongs to it;
* a class that wrote nothing still gets the harness default -- including when the site's
  ambient value is a real, different company (the control that stops "always keep what is
  there" passing), a company that does not exist, or a value a previous TEST left behind.

Each scenario drives a real `EnhancedTestCase` through `unittest`, because the defect is
in how `setUp` treats the Single, not in the helper in isolation.
"""

import unittest

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.support.verenigingen_settings import _write, _write_setting

GHOST_COMPANY_528 = "No Such Company 528"


def _read_settings_pair_528():
    return (
        frappe.db.get_value("Verenigingen Settings", None, "company"),
        frappe.db.get_value("Verenigingen Payments Settings", None, "dues_income_account"),
    )


def _run_case_528(case_class):
    result = unittest.TestResult()
    unittest.TestLoader().loadTestsFromTestCase(case_class).run(result)
    return result


class TestSettingsCompanyChosenByTheClassSurvives(unittest.TestCase):
    def setUp(self):
        self.original = _read_settings_pair_528()
        self.addCleanup(_write, *self.original)
        self.class_company = get_eur_test_company()

    def _observing_case(self, class_setup=None, body_a=None):
        """A real EnhancedTestCase with two bodies that record what they see.

        `class_setup` runs in setUpClass; `body_a` runs inside the first body, before
        it records, to model a test that changes the company mid-test.
        """
        seen = []

        class _Case(EnhancedTestCase):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                if class_setup:
                    class_setup()

            def test_a_first(inner):
                if body_a:
                    body_a()
                    return
                seen.append(_read_settings_pair_528())

            def test_b_second(inner):
                seen.append(_read_settings_pair_528())

        return _Case, seen

    def _harness_default(self):
        """What a class that configures nothing sees -- measured, not assumed."""
        _write_setting("company", GHOST_COMPANY_528)
        case, seen = self._observing_case()
        result = _run_case_528(case)
        self.assertEqual((result.errors, result.failures), ([], []))
        default = seen[0][0]
        self.assertTrue(default and frappe.db.exists("Company", default))
        return default

    def test_a_company_written_in_setUpClass_is_seen_by_every_body(self):
        default = self._harness_default()
        self.assertNotEqual(
            self.class_company,
            default,
            "precondition: the class company must differ from the harness default, or "
            "this test cannot tell a kept value from an overwritten one",
        )
        case, seen = self._observing_case(class_setup=lambda: _write_setting("company", self.class_company))
        result = _run_case_528(case)
        self.assertEqual((result.errors, result.failures), ([], []))
        self.assertEqual([company for company, _ in seen], [self.class_company] * 2)

    def test_the_dues_income_account_follows_the_kept_company(self):
        case, seen = self._observing_case(class_setup=lambda: _write_setting("company", self.class_company))
        _run_case_528(case)
        accounts = [account for _, account in seen]
        self.assertEqual(len(accounts), 2)
        for account in accounts:
            self.assertEqual(frappe.db.get_value("Account", account, "company"), self.class_company)

    def test_a_class_that_writes_nothing_still_gets_the_default_over_a_real_ambient_company(self):
        """The control: the ambient value is a REAL company that differs from the default.

        An "always keep what is there" fix would keep it and fail here.
        """
        default = self._harness_default()
        _write_setting("company", self.class_company)
        case, seen = self._observing_case()
        result = _run_case_528(case)
        self.assertEqual((result.errors, result.failures), ([], []))
        self.assertEqual([company for company, _ in seen], [default] * 2)

    def test_a_class_company_that_does_not_exist_does_not_stick(self):
        default = self._harness_default()
        case, seen = self._observing_case(class_setup=lambda: _write_setting("company", GHOST_COMPANY_528))
        _run_case_528(case)
        self.assertEqual([company for company, _ in seen], [default] * 2)

    def test_a_company_a_test_changed_mid_test_does_not_carry_into_the_next_test(self):
        default = self._harness_default()
        case, seen = self._observing_case(body_a=lambda: _write_setting("company", self.class_company))
        result = _run_case_528(case)
        self.assertEqual((result.errors, result.failures), ([], []))
        self.assertEqual([company for company, _ in seen], [default])
