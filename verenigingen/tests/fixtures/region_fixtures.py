# -*- coding: utf-8 -*-
# Copyright (c) 2025, Your Organization and Contributors
# See license.txt

"""The single owner of the shared ``Test Region`` master (#406).

``Region.autoname`` is ``field:region_name`` (``region/region.json:6``), so every
fixture that inserts ``region_name = "Test Region"`` is writing to the SAME
docname, ``test-region``.  Sixteen files did, and they disagreed about the
``region_code`` they keyed their get-or-create on -- twelve ``TR``, two ``TST``,
two ``TSTRG``.  Some keyed on the code, others on the docname, and those two
predicates disagree whenever the row present was written by the other group: a
code-keyed lookup finds nothing, decides the region is missing, inserts, and dies
on the PRIMARY key.

Reproduced on ``test_site_5`` before this module existed, with a control::

    seed test-region with region_code="TSTRG", then run the "TR"-keyed
    get-or-create from tests/utils/setup_helpers.py
      -> DuplicateEntryError: ('Region', 'test-region',
         IntegrityError(1062, "Duplicate entry 'test-region' for key 'PRIMARY'"))

    seed test-region with region_code="TR", same get-or-create
      -> OK, resolved to 'test-region'

Which of the two runs first is decided by the shard packing, and shard bins
re-pack on measured runtime, so editing any test file moves it.

**A ``region_name``-keyed guard is not merely weaker -- it is always false.**
Frappe syncs a ``field:`` autoname back onto its field, so ``insert()`` overwrites
``region_name`` with the scrubbed docname. Measured on test_site_5::

    insert(region_name="Probe Region Name Rewrite")
      -> .name         'probe-region-name-rewrite'
      -> .region_name  'probe-region-name-rewrite'   (persisted)
      -> get_value("Region", {"region_name": "Probe Region Name Rewrite"})  ->  None

So the row on a warm site reads ``region_name = 'test-region'``, and
``get_value("Region", {"region_name": "Test Region"})`` can never find it. Two of the
sixteen were written that way.

**The guard key is the docname, and only the docname.**  The primary key is what
decides whether the insert succeeds, so it is the only predicate that cannot
disagree with reality -- ``region_code`` is UNIQUE too, but a row can satisfy the
code predicate and still collide on the name, and vice versa.  See the guard-key
rule in ``.claude/skills/verenigingen-test-harness/SKILL.md``.

``allocate_free_region_code`` (#405) allocates a code that is free; it
deliberately says nothing about the shared docname, which is what this closes.

**Import this LAZILY from the three shared harness modules** (``tests/utils/base.py``,
``factories.py``, ``setup_helpers.py``). This module needs ``shared_fixture`` and
``allocate_free_region_code`` from ``enhanced_test_factory``, whose module body runs
``import erpnext.tests.utils`` -- which calls ``BootStrapTestData()`` (Company,
Territory tree, chart of accounts, Fiscal Year, price lists) inside a bare
``except Exception: pass``. Hanging that off *importing* the harness base would fire
it for every ``--module`` run whose modules do not otherwise touch the factory,
changing WHEN those masters appear. Leaf test modules import it at module scope; they
already import the factory anyway.

``@shared_fixture`` because the row is SHARED master data built LAZILY, from
inside whichever test happens to call first.  Without it the captured-insert
drain claims it for that one test and deletes it at that test's teardown, taking
it from every later class in the shard -- #330 verbatim.  On ``test_site_5``
there are 225 Chapters linked to ``test-region``; losing it mid-shard fails their
link validation, not merely the region lookup.
``test_the_shared_region_helper_is_declared_shared`` in
``tests/test_harness_leak_attribution.py`` pins the decorator by name.
"""

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import (
    allocate_free_region_code,
    shared_fixture,
)

#: The one fixed Region name the suite shares, and the docname Frappe slugs it to.
TEST_REGION_NAME = "Test Region"
TEST_REGION_DOCNAME = "test-region"

#: Preferred code, kept because twelve of the sixteen call sites already wrote it
#: and a warm site therefore already carries it.  It is only a preference: if some
#: other Region holds "TR", the Region controller rejects the duplicate with a
#: ValidationError, so fall back to an allocated one rather than fail.
_PREFERRED_REGION_CODE = "TR"


@shared_fixture
def ensure_test_region() -> str:
    """Get-or-create the shared ``Test Region``; return its docname.

    Deliberately does NOT set ``postal_code_patterns``.  One of the sixteen call
    sites (``tests/utils/setup_helpers.py``) used to seed ``"1000-9999"`` on it,
    which makes ``find_region_by_postal_code`` return this region for essentially
    every Dutch postal code -- but only when that one file happened to create the
    row first.  Chapter matching reads ``Chapter.postal_codes``, not the region's
    patterns (``ChapterMatchingService.get_chapters_by_postal_code``), and no test
    reads this region's patterns, so the narrower behaviour is the one to make
    deterministic.  Measured on ``test_site_5``: 0 of 466 Regions carry patterns.
    """
    if frappe.db.exists("Region", TEST_REGION_DOCNAME):
        return TEST_REGION_DOCNAME

    code = _PREFERRED_REGION_CODE
    if frappe.db.exists("Region", {"region_code": code}):
        code = allocate_free_region_code()

    region = frappe.get_doc(
        {
            "doctype": "Region",
            "region_name": TEST_REGION_NAME,
            "region_code": code,
            "country": "Netherlands",
            "is_active": 1,
        }
    )
    # Check-then-insert with no retry, for the reason `allocate_free_region_code`
    # gives: each CI shard runs against its own site, so there is no second writer.
    region.insert(ignore_permissions=True)
    return region.name
