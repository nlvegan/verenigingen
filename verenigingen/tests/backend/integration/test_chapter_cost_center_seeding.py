# Copyright (c) 2026, Verenigingen and Contributors
# See license.txt

"""Regression test for the chapter cost-center company seeding.

Background
----------
``ChapterFinanceService.get_validated_company`` resolves the company to create a
chapter cost center under. It prefers ``Verenigingen Settings.company``, then
``Global Defaults.default_company``, and only falls back to "use the single
company" when exactly one company exists. ERPNext's v16 test bootstrap
(``BootStrapTestData``) creates **20** test companies and never sets a default
company, so in tests the single-company shortcut never fires and the resolver
returns ``None`` -- silently leaving chapters without a cost center -- unless the
test seeding has populated ``Verenigingen Settings.company`` with a real company.

This pins the behaviour of ``_seed_verenigingen_test_system_user`` (run by both
``before_tests`` and ``ensure_member_test_masters``): it must self-heal a STALE
``Verenigingen Settings.company`` (one pointing at a company a co-located test
deleted), not only an empty one. Before the fix the seeder only re-seeded an
empty value, so a stale value survived and the resolver returned ``None``.

The reproduction requires the real multi-company test state, so this is an
integration test rather than a mocked unit test (the mocked branch logic already
lives in ``tests/unit/services/test_chapter_finance_service.py``).
"""

from types import SimpleNamespace

import frappe

from verenigingen.services.chapter.chapter_finance_service import get_chapter_finance_service
from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.tests.setup import (
    _seed_verenigingen_test_system_user,
    ensure_member_test_masters,
)

_GHOST_COMPANY = "Nonexistent Ghost Co - regression"


class TestChapterCostCenterSeeding(EnhancedTestCase):
    """The test seeding must always leave the cost-center resolver a real company."""

    def setUp(self):
        super().setUp()
        # Seed ERPNext + Verenigingen base masters (Company tree, Verenigingen
        # Settings.company). Idempotent.
        ensure_member_test_masters()
        # _seed_verenigingen_test_system_user commits, so its writes survive the
        # per-test rollback -- capture the good post-seed value and restore it in
        # tearDown so we don't bleed our deliberate corruption into later tests.
        self._orig_ver_company = frappe.db.get_single_value("Verenigingen Settings", "company")
        self.svc = get_chapter_finance_service()
        self.chapter = SimpleNamespace(name="CC-Seeding-Regression-Chapter")

    def tearDown(self):
        frappe.db.set_single_value("Verenigingen Settings", "company", self._orig_ver_company or "")
        frappe.db.commit()
        super().tearDown()

    def test_precondition_many_companies_present(self):
        """The reproduction only means something with multiple companies present."""
        self.assertGreater(
            frappe.db.count("Company"),
            1,
            "Expected ERPNext's multi-company test state; the single-company "
            "resolver shortcut would mask the bug otherwise.",
        )

    def test_seeder_self_heals_stale_settings_company(self):
        """A stale Verenigingen Settings.company (deleted company) must be re-seeded."""
        self.assertFalse(
            frappe.db.exists("Company", _GHOST_COMPANY),
            "ghost company must not actually exist for this test",
        )
        # Corrupt: point at a non-existent company.
        frappe.db.set_single_value("Verenigingen Settings", "company", _GHOST_COMPANY)
        frappe.db.commit()

        # Sanity: the corrupted state reproduces the break (the resolver's
        # Global Defaults fallback is empty in tests, and with many companies the
        # single-company shortcut never fires).
        self.assertIsNone(
            self.svc.get_validated_company(self.chapter),
            "expected the resolver to fail with a stale company + many companies",
        )

        _seed_verenigingen_test_system_user()

        healed = frappe.db.get_single_value("Verenigingen Settings", "company")
        self.assertNotEqual(healed, _GHOST_COMPANY, "seeder must replace the stale value")
        self.assertTrue(frappe.db.exists("Company", healed), "healed company must exist")
        self.assertEqual(
            self.svc.get_validated_company(self.chapter),
            healed,
            "resolver must now return the healed company",
        )
