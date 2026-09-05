# -*- coding: utf-8 -*-
# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt
"""Regression for #263: shared membership-type fixture names must not freeze
their amount at whichever caller creates them first.

``ensure_membership_type_exists()`` (test_data_factory.py) and
``EnhancedTestDataFactory.ensure_membership_type()`` (enhanced_test_factory.py)
are get-or-create helpers keyed on a stable, human-meaningful name (e.g.
"Standard Member", "Monthly Membership") that dozens of test files deliberately
share, because the production code under test looks the type up by that
literal name -- the name itself cannot be made unique per caller the way
``create_test_membership_type()``'s synthetic names are.

Before the fix, once ANY caller created the row, every later caller silently
received that FIRST caller's amount untouched, no matter what it asked for.
This is exactly what #248 hit in production CI: PAYMENT_TEST_DAILY_TYPE's €2
type could come back at €100 depending on run order. #248 was patched by
giving that one type a private name nothing else references; this fix instead
corrects the shared get-or-create itself -- but ONLY when a caller passes an
EXPLICIT amount. A caller with no opinion (no `amount` argument, or an
`attributes` dict with no "amount"/"minimum_amount" key) leaves an existing row
untouched, exactly as before: realigning unconditionally was tried first and
broke real tests (test_dues_schedule_health_manager.py's
test_custom_rate_preservation and 4 siblings) whose setUp deliberately sets a
non-default amount, then have it silently reset back to the default by an
unrelated "just ensure it exists" call elsewhere in the same test.

``TestCrossCallerAmountSync`` reproduces the defect directly: two calls to the
same helper for the same name, different EXPLICIT amounts, in one test method.
``TestNoAmountCallLeavesExistingRowAlone`` pins the other half of the design --
that a caller who does NOT pass an amount can never clobber one a DIFFERENT,
opinionated caller set.

``TestConsumerModuleAlpha`` / ``TestConsumerModuleBeta`` stand in for two
separate consuming test files sharing one already-existing Membership Type
name, to check the same invariant across a test-class boundary rather than
within one method. ``setUpModule()`` creates that shared row ONCE, under
``suspend_insert_capture()`` + an explicit commit, so it survives the two
erasure mechanisms that would otherwise remove it before either class runs:
EnhancedTestCase's per-test transaction rollback, and this app's own
captured-insert drain (see ``_create_shared_type_surviving_into_next_test``'s
docstring). Creating it in ``setUpModule()`` rather than inside one of the two
consumer classes means neither class's own assertions gate whether cleanup
happens, and it means the two classes' RELATIVE execution order does not
matter for correctness -- each just needs to observe the row already existing
(a non-vacuous guard checks this) and get back the amount IT asked for,
regardless of what the other class most recently set it to. ``tearDownModule()``
removes the row unconditionally once, however the individual tests fared.
"""

import time
import unittest

import frappe
from frappe.utils import flt

from verenigingen.tests.fixtures.enhanced_test_factory import (
    EnhancedTestCase,
    suspend_insert_capture,
)
from verenigingen.tests.fixtures.test_data_factory import ensure_membership_type_exists


class TestCrossCallerAmountSync(EnhancedTestCase):
    """Two direct calls to the same helper, same name, different EXPLICIT amounts."""

    def test_ensure_membership_type_exists_realigns_on_every_call(self):
        name = f"Shared Amount Sync {self.uid[:8]}"

        ensure_membership_type_exists(name, amount=100.0)
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", name, "minimum_amount"), 2),
            100.0,
            "first caller's amount was not applied",
        )

        # A second caller asking for a DIFFERENT amount must get ITS amount,
        # not the first caller's frozen-in value.
        ensure_membership_type_exists(name, amount=250.0)
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", name, "minimum_amount"), 2),
            250.0,
            "second caller silently received the first caller's amount (#263)",
        )

        # The linked dues-schedule template must move with it, or a schedule
        # built from it fails validation for an unrelated reason.
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": name},
            ["dues_rate", "suggested_amount"],
            as_dict=True,
        )
        self.assertIsNotNone(template)
        self.assertEqual(flt(template.dues_rate, 2), 250.0)
        self.assertEqual(flt(template.suggested_amount, 2), 250.0)

    def test_enhanced_factory_ensure_membership_type_realigns_on_every_call(self):
        type_name = f"Shared Amount Sync ETDF {self.uid[:8]}"

        self.factory.ensure_membership_type(type_name, {"amount": 50.0})
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", type_name, "minimum_amount"), 2),
            50.0,
        )

        self.factory.ensure_membership_type(type_name, {"amount": 175.0})
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", type_name, "minimum_amount"), 2),
            175.0,
            "second caller silently received the first caller's amount (#263)",
        )
        # The linked dues-schedule template must move with it too -- this half
        # of the postcondition was previously unasserted, so deleting the
        # template-alignment code in _align_membership_type_amount would still
        # have left this test green.
        template = frappe.db.get_value(
            "Membership Dues Schedule",
            {"is_template": 1, "membership_type": type_name},
            ["dues_rate", "suggested_amount"],
            as_dict=True,
        )
        self.assertIsNotNone(template)
        self.assertEqual(flt(template.dues_rate, 2), 175.0)
        self.assertEqual(flt(template.suggested_amount, 2), 175.0)

    def test_enhanced_factory_accepts_minimum_amount_as_a_synonym_for_amount(self):
        """10 real call sites pass attributes={"minimum_amount": ...} rather
        than {"amount": ...} (e.g. test_member_lifecycle_workflows.py's tiered
        Regular/Student/Senior/Family/Corporate types). Those calls must count
        as "explicit" too, or they are silently ignored by the realign check
        and every one of those callers gets whatever amount an unrelated
        caller created the shared name at first -- the same #263 defect, just
        reachable through the OTHER key name.
        """
        type_name = f"Shared Amount Sync MinAmt {self.uid[:8]}"

        self.factory.ensure_membership_type(type_name, {"minimum_amount": 30.0})
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", type_name, "minimum_amount"), 2),
            30.0,
        )

        self.factory.ensure_membership_type(type_name, {"minimum_amount": 80.0})
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", type_name, "minimum_amount"), 2),
            80.0,
            "a caller using the minimum_amount key was silently ignored (#263)",
        )


class TestNoAmountCallLeavesExistingRowAlone(EnhancedTestCase):
    """The other half of the design: a caller with no opinion on amount must
    never clobber a value some OTHER, opinionated caller is relying on.

    An earlier version of this fix realigned on EVERY call, including calls
    that passed no amount at all -- which broke real production tests, because
    create_test_membership() internally calls ensure_membership_type_exists()
    with no amount purely to guarantee existence. This pins the corrected
    behaviour so it can't regress back to "realign unconditionally" silently.
    """

    def test_ensure_membership_type_exists_no_amount_leaves_existing_amount_alone(self):
        name = f"No Amount Sync {self.uid[:8]}"

        ensure_membership_type_exists(name, amount=5.0)
        # A later caller with NO opinion on amount -- just wants it to exist.
        ensure_membership_type_exists(name)

        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", name, "minimum_amount"), 2),
            5.0,
            "a no-amount call clobbered a value an earlier, opinionated caller set",
        )

    def test_ensure_membership_type_exists_explicit_none_behaves_like_no_amount(self):
        name = f"No Amount Sync None {self.uid[:8]}"

        ensure_membership_type_exists(name, amount=5.0)
        # amount=None is "no opinion", not "set it to null" -- the DocType has
        # no such concept, and this call site pattern is a foreseeable typo/
        # forwarding bug (e.g. `ensure_membership_type_exists(name, amount=kwargs.get("amount"))`).
        ensure_membership_type_exists(name, amount=None)

        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", name, "minimum_amount"), 2),
            5.0,
            "amount=None was treated as an explicit request and clobbered the existing amount",
        )

    def test_enhanced_factory_no_amount_leaves_existing_amount_alone(self):
        type_name = f"No Amount Sync ETDF {self.uid[:8]}"

        self.factory.ensure_membership_type(type_name, {"amount": 5.0})
        # A later caller that passes attributes with no "amount"/"minimum_amount".
        self.factory.ensure_membership_type(type_name, {"billing_period": "Monthly"})

        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", type_name, "minimum_amount"), 2),
            5.0,
            "a no-amount call clobbered a value an earlier, opinionated caller set",
        )


def _create_shared_type_surviving_into_next_test(name, amount):
    """Create Membership Type `name` so it survives past THIS test's teardown
    into a LATER test class -- simulating a row a real shared fixture
    (PAYMENT_TEST_DAILY_TYPE via setUpClass) leaves behind for other tests.

    Two commit-related mechanisms would otherwise erase it before the next
    test class runs: FrappeTestCase wraps each test method in its own
    transaction and rolls back at teardown (measured: without this commit,
    the row is gone by the next test class), and this app's OWN
    captured-insert drain independently claims and deletes any row inserted
    inside an unmarked test (see suspend_insert_capture()'s docstring). Both
    have to be defeated for the cross-class scenario below to be real rather
    than vacuous.
    """
    with suspend_insert_capture():
        ensure_membership_type_exists(name, amount=amount)
        frappe.db.commit()


def _cleanup_membership_type_and_its_templates(name):
    """Delete a Membership Type and every dues-schedule template linked to
    it, then commit.

    A Membership Type and its dues_schedule_template link to each other (see
    test_data_factory.py's ensure_payment_test_daily_type AssertionError
    message, which documents the same recipe for a human to run by hand):
    force-deleting only the type leaves the template behind as an orphan with
    a dangling `membership_type` reference. Measured: a naive
    `frappe.delete_doc("Membership Type", name, force=True)` with no template
    cleanup leaked 6 such orphaned "... Template" rows across earlier runs of
    this module. Unlink first so neither delete trips the other doctype's
    link-validation.
    """
    frappe.db.set_value("Membership Type", name, "dues_schedule_template", None)
    for schedule in frappe.get_all(
        "Membership Dues Schedule", filters={"membership_type": name}, pluck="name"
    ):
        frappe.delete_doc("Membership Dues Schedule", schedule, force=True)
    frappe.delete_doc("Membership Type", name, force=True)
    # Backstop: one run of this module's development (see #263 PR) left a single
    # such row behind despite the loop above, for a reason that did not
    # reproduce across four follow-up runs. A direct DELETE closes the gap
    # regardless of cause, rather than trusting frappe.get_all()'s read to have
    # seen every row frappe.delete_doc() needs to remove.
    frappe.db.sql("DELETE FROM `tabMembership Dues Schedule` WHERE membership_type=%s", (name,))
    frappe.db.commit()


# Module-level state for the two "consuming module" classes below. Populated
# by setUpModule() before either class's tests run, and torn down
# unconditionally by tearDownModule() -- NOT by either class's own test
# bodies, so a failing assertion in either one can never skip cleanup (a
# try/finally scoped to one test's body was tried first and does not cover
# this: it only protects against that ONE test's own assertions failing, not
# against the run being interrupted, filtered to skip the other class, or
# failing before reaching the finally).
_shared_consumer_type_name = None


def setUpModule():
    global _shared_consumer_type_name
    name = f"Cross Module Shared Type {int(time.time() * 1000000) % 1000000}"
    _create_shared_type_surviving_into_next_test(name, amount=250.0)
    _shared_consumer_type_name = name


def tearDownModule():
    if _shared_consumer_type_name:
        _cleanup_membership_type_and_its_templates(_shared_consumer_type_name)


class TestConsumerModuleAlpha(EnhancedTestCase):
    def test_gets_its_own_amount_not_a_sibling_modules(self):
        name = _shared_consumer_type_name
        # Non-vacuous guard: without setUpModule()'s row already existing,
        # this call would just create it fresh and the assertion below would
        # pass trivially without ever exercising the get-or-create-EXISTING
        # branch this test targets.
        self.assertTrue(
            name and frappe.db.exists("Membership Type", name),
            "setUpModule()'s shared row is missing -- this test would be vacuous",
        )

        ensure_membership_type_exists(name, amount=150.0)
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", name, "minimum_amount"), 2),
            150.0,
            "did not get its own amount -- contaminated by whatever the row held before (#263)",
        )


class TestConsumerModuleBeta(EnhancedTestCase):
    def test_gets_its_own_amount_not_a_sibling_modules(self):
        name = _shared_consumer_type_name
        # Same non-vacuous guard as TestConsumerModuleAlpha. Whichever of the
        # two classes unittest runs first will have already changed the row's
        # amount to ITS OWN value -- this test must still get back what IT
        # asks for, not what the other class most recently set, so the
        # assertion below is meaningful regardless of execution order.
        self.assertTrue(
            name and frappe.db.exists("Membership Type", name),
            "setUpModule()'s shared row is missing -- this test would be vacuous",
        )

        ensure_membership_type_exists(name, amount=99.0)
        self.assertEqual(
            flt(frappe.db.get_value("Membership Type", name, "minimum_amount"), 2),
            99.0,
            "did not get its own amount -- contaminated by whatever the row held before (#263)",
        )


if __name__ == "__main__":
    unittest.main()
