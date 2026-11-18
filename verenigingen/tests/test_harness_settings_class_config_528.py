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
  there" passing) or a company that does not exist;
* that holds IN SEQUENCE: `setUpClass` pins a common baseline and restores the site's value
  in a class cleanup, so a class that chose a company and never restored it cannot make a
  LATER class choosing the same company look ambient and get reverted (the first design
  compared with whatever the Single held, and reverted T2 in "T1 chooses X, T2 chooses X").

Each scenario drives a real `EnhancedTestCase` through `unittest`, because the defect is
in how `setUp` treats the Single, not in the helper in isolation.
"""

import unittest
from unittest.mock import patch

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.support.mollie_settings import (
    _restore_mollie_clearing_account,
    own_mollie_clearing_account,
)
from verenigingen.tests.support.sepa_test_company import get_eur_test_company
from verenigingen.tests.support.verenigingen_settings import _write, _write_setting

GHOST_COMPANY_528 = "No Such Company 528"


def _read_settings_pair_528():
    return (
        frappe.db.get_value("Verenigingen Settings", None, "company"),
        frappe.db.get_value("Verenigingen Payments Settings", None, "dues_income_account"),
    )


class TestSettingsCompanyChosenByTheClassSurvives(unittest.TestCase):
    def setUp(self):
        self.original = _read_settings_pair_528()
        self.addCleanup(_write, *self.original)
        self.class_company = get_eur_test_company()
        self.default = self._harness_default_528()
        # Pin the preconditions instead of inheriting them from the site: the class company
        # must differ from the default, and the ambient value is a THIRD company, so no
        # outcome below can come from ambient state.
        self.assertNotEqual(self.class_company, self.default)
        others = frappe.get_all(
            "Company",
            filters={"name": ["not in", [self.class_company, self.default]]},
            pluck="name",
            order_by="name asc",
        )
        if not others:
            self.skipTest("needs a third company to act as the ambient value")
        self.third = others[0]
        self._set_ambient_528(self.third)

    def _set_ambient_528(self, company):
        _write(company, _read_settings_pair_528()[1])
        self.assertEqual(_read_settings_pair_528()[0], company)

    def _observing_case_528(self, name, class_setup=None, body_a=None):
        """A real EnhancedTestCase with two bodies that record what they see."""
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

        _Case.__name__ = name
        return _Case, seen

    def _class_chooses_528(self, company=None):
        return lambda: _write_setting("company", company or self.class_company)

    def _run_cases_528(self, *cases):
        suite = unittest.TestSuite(unittest.TestLoader().loadTestsFromTestCase(c) for c in cases)
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual((result.errors, result.failures), ([], []))

    def _harness_default_528(self):
        """What a class that configures nothing sees -- measured, not assumed."""
        case, seen = self._observing_case_528("Probe528")
        self._run_cases_528(case)
        company = seen[0][0]
        self.assertTrue(company and frappe.db.exists("Company", company))
        return company

    def test_a_company_written_in_setUpClass_is_seen_by_every_body(self):
        case, seen = self._observing_case_528("T528", self._class_chooses_528())
        self._run_cases_528(case)
        self.assertEqual([company for company, _ in seen], [self.class_company] * 2)

    def test_the_dues_income_account_follows_the_kept_company(self):
        case, seen = self._observing_case_528("Inc528", self._class_chooses_528())
        self._run_cases_528(case)
        accounts = [account for _, account in seen]
        self.assertEqual(len(accounts), 2)
        for account in accounts:
            self.assertEqual(frappe.db.get_value("Account", account, "company"), self.class_company)

    def test_a_class_that_writes_nothing_still_gets_the_default_over_a_real_ambient_company(self):
        """The control: a REAL ambient company (a third one) is in place when the class starts.

        The class sees the default, not the ambient company: setUpClass pins the baseline over
        it, and a class that wrote nothing has nothing to keep. This does NOT discriminate
        "keep whatever the Single holds in setUp" (that value is the pinned default by then);
        `test_a_class_that_writes_nothing_gets_the_default_when_it_is_not_the_pinned_baseline`
        and the no-baseline case below do.
        """
        case, seen = self._observing_case_528("Ctl528")
        self._run_cases_528(case)
        self.assertEqual([company for company, _ in seen], [self.default] * 2)

    def test_a_class_that_writes_nothing_gets_the_default_when_it_is_not_the_pinned_baseline(self):
        """Pinned baseline (`_harness_company`) and default (`_get_test_company`) are different
        companies here. A class that wrote nothing has the Single at the pinned baseline, which
        must NOT count as chosen: ignoring the `current != pinned` comparison keeps the baseline
        and the bodies would see it instead of the default."""
        frappe.local.test_company_name = self.class_company
        self.addCleanup(delattr, frappe.local, "test_company_name")
        case, seen = self._observing_case_528("NotPinned528")
        self._run_cases_528(case)
        self.assertNotEqual(self.class_company, self.default)
        self.assertEqual([company for company, _ in seen], [self.class_company] * 2)

    def test_without_a_pinned_baseline_a_real_ambient_company_is_not_taken_as_chosen(self):
        """`own_settings_company` returns None when no harness company exists. A real ambient
        company then differs from "nothing", and must not be kept as the class's choice."""
        with patch("verenigingen.tests.support.verenigingen_settings._harness_company", return_value=None):
            case, seen = self._observing_case_528("NoBase528")
            self._run_cases_528(case)
        self.assertEqual([company for company, _ in seen], [self.default] * 2)

    def test_a_class_company_that_does_not_exist_does_not_stick(self):
        case, seen = self._observing_case_528("Ghost528", self._class_chooses_528(GHOST_COMPANY_528))
        self._run_cases_528(case)
        self.assertEqual([company for company, _ in seen], [self.default] * 2)

    def test_a_company_a_test_changed_mid_test_does_not_carry_into_the_next_test(self):
        case, seen = self._observing_case_528("Mid528", body_a=lambda: _write_setting("company", self.class_company))
        self._run_cases_528(case)
        self.assertEqual([company for company, _ in seen], [self.default])

    def test_classes_in_sequence_each_see_what_they_chose(self):
        """Shard composition: T1 chooses X, T2 chooses X, T3 nothing, T4 chooses X, then
        a class that chose X and never restored it, then one that chooses nothing.

        None of them restores anything itself. Under the first design T2 and T4 were
        reverted because X had leaked into their class-start value.
        """
        t1, s1 = self._observing_case_528("Seq1_528", self._class_chooses_528())
        t2, s2 = self._observing_case_528("Seq2_528", self._class_chooses_528())
        t3, s3 = self._observing_case_528("Seq3_528")
        t4, s4 = self._observing_case_528("Seq4_528", self._class_chooses_528())
        leak, sl = self._observing_case_528("SeqLeak_528", self._class_chooses_528())
        after, sa = self._observing_case_528("SeqAfter_528")
        self._run_cases_528(t1, t2, t3, t4, leak, after)
        chose = [self.class_company] * 2
        self.assertEqual(
            [[c for c, _ in s] for s in (s1, s2, s3, s4, sl, sa)],
            [chose, chose, [self.default] * 2, chose, chose, [self.default] * 2],
        )

    def test_the_sites_value_is_back_after_the_classes_have_run(self):
        case, _ = self._observing_case_528("Back528", self._class_chooses_528())
        self._run_cases_528(case)
        self.assertEqual(_read_settings_pair_528()[0], self.third)

    def test_a_class_choosing_the_company_the_site_already_holds_keeps_it(self):
        """Ambient == the class's choice (the DuesProcessorTestBase shape on a site that
        an earlier module left on EUR)."""
        self._set_ambient_528(self.class_company)
        case, seen = self._observing_case_528("Same528", self._class_chooses_528())
        self._run_cases_528(case)
        self.assertEqual([company for company, _ in seen], [self.class_company] * 2)

    def test_a_class_scoped_mollie_clearing_pin_is_seen_by_the_bodies_and_restored_after(self):
        """A class that points Mollie Settings at its own clearing account must hand the site's
        value back: left behind, it reconfigured every later class's Mollie lookups (#528)."""
        field = "mollie_clearing_account"
        original = frappe.db.get_single_value("Mollie Settings", field)
        self.addCleanup(_restore_mollie_clearing_account, original)
        _restore_mollie_clearing_account("528 ambient clearing")  # set + commit the ambient value
        seen = []

        class _MollieCase(EnhancedTestCase):
            @classmethod
            def setUpClass(cls):
                super().setUpClass()
                own_mollie_clearing_account(cls, "528 class clearing")

            def test_sees_the_pin(inner):
                seen.append(frappe.db.get_single_value("Mollie Settings", field))

        self._run_cases_528(_MollieCase)
        self.assertEqual(seen, ["528 class clearing"])
        self.assertEqual(frappe.db.get_single_value("Mollie Settings", field), "528 ambient clearing")
