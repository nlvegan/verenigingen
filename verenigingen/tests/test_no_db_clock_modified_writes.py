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
import re
import unittest

import verenigingen

# Paths are relative to the REPO root. Each entry needs a reason, and the reason has to
# say why a DB-clock stamp is right there -- or, for a test fixture, why it has to be
# written that way rather than with a Python-side now().
ALLOWED: dict[str, str] = {}

# Test code is excluded: hand-rolled fixture SQL is deliberate there, and no sensible
# ALLOWED reason exists for it. Excluded BOTH ways, because this app splits the
# difference: most tests live under `verenigingen/tests/`, but Frappe's own convention
# puts them next to the code (`verenigingen/verenigingen/doctype/volunteer/
# test_volunteer.py`, `verenigingen/services/billing/test_sales_invoice_hooks.py` --
# both real, both currently using the INSERT form this guard does not match anyway).
# A directory-only exclusion would redden on the first doctype-local fixture that uses
# the assignment form, with no honest ALLOWED entry available.
_EXCLUDED_DIRS = frozenset({"tests", "node_modules", "__pycache__", "env", "sites", "logs"})


def _is_test_file(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py")

_DB_CLOCK = re.compile(
    r"\bmodified\s*=\s*(?:NOW|CURRENT_TIMESTAMP|LOCALTIME|LOCALTIMESTAMP|SYSDATE|UTC_TIMESTAMP)\s*\(",
    re.IGNORECASE,
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Ids of the string Constants that are docstrings, so prose is not scanned."""
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _db_clock_writes(tree: ast.AST):
    """Yield line numbers of string literals assigning `modified` from the DB clock."""
    skip = _docstring_nodes(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        if _DB_CLOCK.search(node.value):
            yield node.lineno


class TestNoDbClockModifiedWrites(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # The REPO root, not the package root. `scripts/` (74 files using frappe.db.sql)
        # and `admin_tools/` sit beside the package, and one of the sites this guard was
        # written alongside -- scripts/workspace_reorganization.py:131 -- lives there.
        cls.root = os.path.dirname(os.path.dirname(os.path.abspath(verenigingen.__file__)))

    def _walk_production_modules(self):
        for dirpath, dirnames, filenames in os.walk(self.root):
            # Skip dot-directories outright: .git, and .claude/worktrees, which holds
            # whole copies of this repo that would otherwise be scanned as if they were
            # the app.
            dirnames[:] = [
                d for d in dirnames if not d.startswith(".") and d not in _EXCLUDED_DIRS
            ]
            for filename in filenames:
                if not filename.endswith(".py") or _is_test_file(filename):
                    continue
                path = os.path.join(dirpath, filename)
                yield os.path.relpath(path, self.root), path

    def test_no_module_writes_modified_from_the_database_clock(self):
        offenders = []
        for relative, path in self._walk_production_modules():
            if relative in ALLOWED:
                continue
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError:  # pragma: no cover - a broken file is another test's problem
                continue
            offenders.extend(f"{relative}:{line}" for line in _db_clock_writes(tree))

        self.assertEqual(
            sorted(offenders),  # os.walk order is not stable across machines
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
