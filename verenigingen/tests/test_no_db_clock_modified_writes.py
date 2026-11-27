"""No production SQL in this app may hand-write ``modified`` from the DB clock.

The bug class (#453)
--------------------
Frappe writes ``modified`` from ``frappe.utils.now()`` -- the **site** clock, with
microseconds -- into ``datetime(6)`` columns. A raw ``UPDATE ... SET modified = NOW()``
gets neither property:

* ``NOW()`` is the **database server's** wall clock. Measured on ``test_site_4``
  2026-08-31: ``SELECT NOW()`` -> ``00:03:08``, ``frappe.utils.now()`` -> ``03:33:08``.
  3h30m apart, because the site's ``time_zone`` is ``Asia/Kolkata`` and the server's is
  not. The *size* of that gap is environment-specific and can be zero; that a caller
  cannot rely on it being zero is not.
* ``NOW()`` is **second** precision (``NOW(6)`` is the microsecond form), so the stored
  stamp is up to a second earlier than the write that produced it -- and, because
  ``Document.check_if_latest`` compares ``modified`` as a **string**, two writes inside
  one second collapse to the same stamp and the optimistic lock stops firing. Measured on
  ``test_site_4``: two raw ``NOW()`` writes then a stale ``save()`` -> **no exception**;
  the same pair with ``NOW(6)`` and with ``frappe.db.set_value`` -> both raised
  ``TimestampMismatchError``.

``frappe.db.set_value`` maintains ``modified``/``modified_by`` correctly, clears the
document cache, and -- like raw SQL -- does not run controller hooks, so it is a drop-in
for the "bypass validation" reason these sites were written for in the first place.

What this does NOT enforce
--------------------------
* It sees only the **assignment** form (``modified = NOW()`` / ``= CURRENT_TIMESTAMP``).
  The INSERT column-list form -- ``(... creation, modified ...) VALUES (..., NOW(), NOW(),
  ...)`` -- is the same defect and is **not** matched here: recognising it needs the
  column list paired with the value list, which a regex over a SQL literal cannot do
  reliably. Two such sites were fixed in the same change as this guard
  (``sepa_mandate_member_integration_service``'s link INSERT and
  ``chapter/managers/member_manager``'s Chapter Member INSERT); a third would slip past.
* It says nothing about ``modified = %s`` sites that pass a Python-side ``now()``. Those
  are correct on both counts and are the shape this guard is pushing people towards.
* It says nothing about whether bumping ``modified`` at all was the right call. A write
  that legitimately changes a row *should* move ``modified`` and *should* invalidate a
  stale in-memory copy; #453 is about the stamp being wrong, not about it moving.

Only string literals are inspected, via the AST -- never the raw source. Several of the
fixes in this change quote the defective SQL verbatim in a comment to say what was wrong,
and a text search would flag that prose and push the next author into deleting the
explanation to appease the guard.
"""

import ast
import os
import unittest

import verenigingen
from scripts.validation.db_clock_modified_write_validator import (
    ALLOWED,
    _db_clock_writes,
    scan_db_clock_modified_writes,
    walk_production_modules,
)


class TestNoDbClockModifiedWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The REPO root, not the package root. `scripts/` (74 files using frappe.db.sql)
        # and `admin_tools/` sit beside the package, and one of the sites this guard was
        # written alongside -- scripts/workspace_reorganization.py:131 -- lives there.
        cls.root = os.path.dirname(os.path.dirname(os.path.abspath(verenigingen.__file__)))

    def _walk_production_modules(self):
        return walk_production_modules(self.root)

    def test_no_module_writes_modified_from_the_database_clock(self):
        offenders = scan_db_clock_modified_writes(root=self.root)

        self.assertEqual(
            offenders,
            [],
            msg=(
                "these sites hand-write `modified` from the database server's clock at "
                "second precision; use frappe.db.set_value (or pass a Python-side "
                "frappe.utils.now()) instead -- see #453:\n  " + "\n  ".join(offenders)
            ),
        )

    def test_the_guard_can_actually_see_the_shape_it_is_looking_for(self):
        """Control. Without this, a regex that matches nothing reads as a clean app."""
        tree = ast.parse(
            'frappe.db.sql("UPDATE `tabMember` SET modified = NOW() WHERE name = %s", (n,))'
        )
        self.assertEqual(list(_db_clock_writes(tree)), [1])

        for spelling in ("modified=NOW()", "MODIFIED = current_timestamp()", "modified =  SYSDATE()"):
            with self.subTest(spelling=spelling):
                self.assertEqual(list(_db_clock_writes(ast.parse(f'q = "SET {spelling}"'))), [1])

        # ... and does not flag the shapes that are fine.
        for benign in (
            "WHERE modified >= DATE_SUB(NOW(), INTERVAL 7 DAY)",
            "SET modified = %s",
            "SET last_modified = NOW()",
        ):
            with self.subTest(benign=benign):
                self.assertEqual(list(_db_clock_writes(ast.parse(f'q = "{benign}"'))), [])

    def test_the_walk_reaches_the_directories_beside_the_package(self):
        """Control for the walk root, not just the regex.

        The first version of this guard rooted the walk at the `verenigingen` PACKAGE, so
        `scripts/workspace_reorganization.py` -- one of the six sites the change that
        introduced this guard fixed -- was silently unprotected.
        """
        scanned = {relative for relative, _ in self._walk_production_modules()}
        self.assertIn(os.path.join("verenigingen", "api", "schedule_maintenance.py"), scanned)
        self.assertIn(os.path.join("scripts", "workspace_reorganization.py"), scanned)
        self.assertIn(os.path.join("admin_tools", "fix_chapter_member_status.py"), scanned)

        # ... and does not scan test code, by directory OR by filename.
        self.assertNotIn(os.path.join("verenigingen", "tests", "test_harness.py"), scanned)
        self.assertFalse(
            [p for p in scanned if os.path.basename(p).startswith("test_")],
            msg="test modules must be excluded by filename too, not only by directory",
        )

    def test_docstrings_are_not_scanned(self):
        """The explanation must be allowed to quote the defect it explains."""
        tree = ast.parse('"""Do not write modified = NOW() -- see #453."""\nx = 1\n')
        self.assertEqual(list(_db_clock_writes(tree)), [])
