"""#2904: a test cleanup must delete what the test created, not what a pattern matches.

A site-wide `DELETE ... LIKE 'Test%'` (or a table-wide DELETE) removes rows another test, a
co-tenant in the same CI shard, or -- on a dev site -- real data owns, and `_` is a single-char
wildcard in LIKE (#2120). It turns an order-dependent flake into "passes alone, fails in shard".

This is a SOURCE scan, because a behavioural test cannot see a site that has not gone wrong yet.
It looks at three shapes in every module under `verenigingen/tests`:

  * raw SQL `DELETE FROM ... LIKE '<literal>'`
  * raw SQL `DELETE FROM `tabX`` with no WHERE, and `frappe.db.delete("X")` with no filter
  * `frappe.db.delete(...)` whose filter is `["like", "<literal with no interpolation>"]`

A pattern that interpolates a per-run token (`f"%{req.name}%"`) is not flagged: it can only match
rows carrying a value the test generated. What the scan does NOT see: `get_all(..., like)` feeding
`delete_doc`, and deletes spread over several lines with the pattern in a variable.

`KNOWN_REMAINING` is the audited list of sites that still match this scan and are tracked in #2904;
it may only shrink.
"""

import os
import re
import unittest

APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS_ROOT = os.path.join(APP_ROOT, "tests")

# raw SQL DELETE with a literal LIKE (an f-string `{...}` before the LIKE value is a per-run token)
_SQL_LIKE = re.compile(r"""DELETE\s+FROM\s+`tab[^`]+`[^"']*?\bLIKE\s+'[^'{]*'""", re.I | re.S)
# raw SQL DELETE FROM `tabX` closing the string straight away: no WHERE at all
_SQL_ALL = re.compile(r"""DELETE\s+FROM\s+`tab[^`]+`\s*[\"')]""", re.I)
# frappe.db.delete("X", {... ["like", "<literal>"] ...}) on one logical call
_DB_DELETE_ALL = re.compile(r"""frappe\.db\.delete\(\s*["'][^"']+["']\s*\)""")
_DB_DELETE_LIKE = re.compile(r"""frappe\.db\.delete\([^\n]*?\[\s*["']like["']\s*,\s*["'][^"'{]*["']""")


def scan_source(source):
    """Return the (lineno, text) of every dangerous cleanup in `source`."""
    hits = []
    for pattern in (_SQL_LIKE, _SQL_ALL):
        for match in pattern.finditer(source):
            lineno = source.count("\n", 0, match.start()) + 1
            hits.append((lineno, " ".join(match.group(0).split())))
    for lineno, line in enumerate(source.splitlines(), 1):
        if _DB_DELETE_LIKE.search(line) or _DB_DELETE_ALL.search(line):
            hits.append((lineno, line.strip()))
    return hits


def scan_tree(root):
    found = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(dirpath, name)
            if os.path.abspath(path) == os.path.abspath(__file__):
                continue  # this file quotes the shapes it scans for
            with open(path, encoding="utf-8") as handle:
                source = handle.read()
            rel = os.path.relpath(path, root)
            for _lineno, text in scan_source(source):
                found.add((rel, text))
    return found


#: Audited 2026-11-24 (#2904). Each still deletes by a pattern; none is fixed here, because each
#: either matches a unique-ish file-specific token or needs its own red/green. Remove an entry when
#: its site is fixed; adding one needs a reviewer to say why the pattern cannot reach foreign rows.
KNOWN_REMAINING = {
    # Error Log / Notification Log rows with a FIXED title, site-wide: removes another test's or a
    # concurrent process's identical rows.
    ("test_staff_alert_event_1979.py", 'frappe.db.delete("Error Log", {"method": ["like", "Staff Alert Event could not be recorded%"]})'),
    ("services/event_application/test_failed_chapter_move_alert_2199.py", 'frappe.db.delete("Notification Log", {"subject": ["like", "MijnRood chapter move failed for %"]})'),
    # table-wide deletes (a whole table, not this test's rows)
    ("payment/test_mollie_reconciliation_engine.py", 'frappe.db.delete("Mollie Reconciliation Log")'),
    ("chapter/test_chapter_board_lifecycle_notifications.py", 'frappe.db.delete("Email Queue")'),
    ("utils/test_config.py", 'frappe.db.delete("Email Queue")'),
    # raw SQL on a file-specific prefix ("Chapter Member Test Chapter%", "ChapterTest%")
    ("chapter/test_chapter_members_enhanced.py", "DELETE FROM `tabChapter Board Member` WHERE parent LIKE 'Chapter Member Test Chapter%'"),
    ("chapter/test_chapter_members_enhanced.py", "DELETE FROM `tabChapter Member` WHERE parent LIKE 'Chapter Member Test Chapter%'"),
    ("chapter/test_chapter_members_enhanced.py", "DELETE FROM `tabChapter` WHERE name LIKE 'Chapter Member Test Chapter%'"),
    ("chapter/test_chapter_members_enhanced.py", "DELETE FROM `tabMember` WHERE first_name LIKE 'ChapterTest%'"),
    ("chapter/test_chapter_members_enhanced.py", "DELETE FROM `tabVolunteer` WHERE volunteer_name LIKE 'ChapterTest%'"),
}


def _unexpected(found):
    """Drop the audited sites, matched by exact (file, text): a new hit in the same file is reported."""
    return sorted(hit for hit in found if hit not in KNOWN_REMAINING)


class TestCleanupsDeleteOnlyWhatTheyCreated(unittest.TestCase):
    def test_no_new_site_wide_cleanup_delete(self):
        unexpected = _unexpected(scan_tree(TESTS_ROOT))
        self.assertEqual(
            unexpected,
            [],
            "a test cleanup deletes by a site-wide pattern or without a WHERE (#2904). Delete the "
            "rows the test inserted (the EnhancedTestCase drain, track_doc, or the created names), "
            "not whatever a pattern matches.",
        )

    def test_scan_sees_the_dangerous_shapes_and_passes_the_scoped_ones(self):
        """Control: the scan fires on each shape and stays quiet on a per-run token."""
        dangerous = [
            'frappe.db.sql("DELETE FROM `tabMember` WHERE first_name LIKE \'Test%\'")',
            'frappe.db.sql("DELETE FROM `tabMember` WHERE email LIKE \'TEST\\\\_%@test.invalid\'")',
            'frappe.db.sql("DELETE FROM `tabMembership Goal`")',
            'frappe.db.delete("Mollie Audit Log", {"description": ["like", "%test%"]})',
        ]
        for snippet in dangerous:
            self.assertTrue(scan_source(snippet), f"the scan missed: {snippet}")

        scoped = [
            'frappe.db.delete("Mollie Audit Log", {"description": ["like", f"{marker}%"]})',
            'frappe.db.sql("DELETE FROM `tabMember` WHERE name IN %(names)s", {"names": names})',
            'frappe.db.sql("DELETE FROM `tabChapter Member` WHERE parent = %s", name)',
            'frappe.db.delete("Error Log", {"error": ["like", f"%{req.name}%"]})',
        ]
        for snippet in scoped:
            self.assertEqual(scan_source(snippet), [], f"the scan flagged a scoped delete: {snippet}")

    def test_known_remaining_sites_still_exist(self):
        """An entry whose site was fixed must be removed, so the list only shrinks."""
        found = scan_tree(TESTS_ROOT)
        stale = sorted(hit for hit in KNOWN_REMAINING if hit not in found)
        self.assertEqual(stale, [], "KNOWN_REMAINING lists a site the scan no longer finds; delete the entry")
