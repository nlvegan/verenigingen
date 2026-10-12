"""Shipped DocType permission rows (#1589, #1588).

Frappe refuses a DocType whose ``permissions`` carry two rows with the same
(role, permlevel, if_owner) (``validate_permissions.check_double``), and ORs
every applicable row per permission type, so a narrower twin of a broader row
grants nothing. Three DocTypes shipped such a twin for ``Verenigingen Staff``,
which made any ``DocType.save()`` of them throw. The walk below is over the
shipped JSON, so it does not depend on what a given site's DB happens to hold.

The second class pins the Chapter Board Member rows that
``setup_chapter_board_permissions`` used to (re)create at runtime: that service
was deleted (#1588), so the JSON is now the only thing that guarantees them.
"""

import json
import unittest
from collections import defaultdict
from pathlib import Path

import frappe

APP_ROOT = Path(__file__).resolve().parents[1]
CBM_ROLE = "Verenigingen Chapter Board Member"
DOCTYPES_WITH_DUPLICATE = ("Membership", "Membership Type", "Contribution Amendment Request")


def _own_doctype_jsons():
    """Yield (path, parsed) for every DocType JSON this app ships."""
    for path in sorted(APP_ROOT.rglob("doctype/*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("doctype") == "DocType":
            yield path, data


def _shipped_doctype_json(doctype_name):
    for path, data in _own_doctype_jsons():
        if data.get("name") == doctype_name:
            return data
    raise AssertionError(f"{doctype_name} JSON not found under {APP_ROOT}")


def _duplicate_rule_sets(data):
    seen = defaultdict(int)
    for row in data.get("permissions") or []:
        seen[(row.get("role"), row.get("permlevel") or 0, row.get("if_owner") or 0)] += 1
    return {key: n for key, n in seen.items() if n > 1}


class TestNoDuplicatePermissionRows(unittest.TestCase):
    def test_no_own_doctype_ships_a_duplicate_role_permlevel_if_owner_rule(self):
        walked = 0
        offenders = []
        for path, data in _own_doctype_jsons():
            walked += 1
            for key in _duplicate_rule_sets(data):
                offenders.append(f"{data.get('name')} {key} ({path.relative_to(APP_ROOT)})")
        # Control: a walk that found no DocTypes would pass vacuously.
        self.assertGreater(walked, 50, f"walk found only {walked} DocType JSONs")
        self.assertEqual(offenders, [], "duplicate (role, permlevel, if_owner) rows ship in JSON")

    def test_the_detector_sees_a_duplicate(self):
        """Control: the helper must flag the exact shape that used to ship."""
        data = {"permissions": [{"role": "R", "read": 1, "write": 1}, {"role": "R", "read": 1}]}
        self.assertEqual(_duplicate_rule_sets(data), {("R", 0, 0): 2})
        data["permissions"][1]["if_owner"] = 1
        self.assertEqual(_duplicate_rule_sets(data), {})

    def test_frappe_accepts_the_permissions_of_the_formerly_duplicated_doctypes(self):
        """Behavioural: Frappe's own rule check (the one DocType.save() runs)."""
        from frappe.core.doctype.doctype.doctype import validate_permissions

        for name in DOCTYPES_WITH_DUPLICATE:
            with self.subTest(doctype=name):
                doc = frappe.get_doc(_shipped_doctype_json(name))  # in memory only: no insert, no JSON write-back
                validate_permissions(doc)

    def test_the_surviving_staff_row_is_the_broad_one(self):
        """Control against the wrong fix: deleting the BROAD twin would silently
        strip Staff of write/create (and Membership's submit/cancel/amend)."""
        expected = {
            "Membership": ("read", "write", "create", "submit", "cancel", "amend"),
            "Membership Type": ("read", "write", "create"),
            "Contribution Amendment Request": ("read", "write", "create"),
        }
        for name, ptypes in expected.items():
            with self.subTest(doctype=name):
                rows = [r for r in _shipped_doctype_json(name)["permissions"] if r["role"] == "Verenigingen Staff"]
                self.assertEqual(len(rows), 1)
                for ptype in ptypes:
                    self.assertEqual(rows[0].get(ptype), 1, ptype)


class TestChapterBoardMemberRowsShipInJson(unittest.TestCase):
    """The JSON, not a runtime service, guarantees board access (#1588)."""

    def _cbm_rows(self, doctype_name):
        return [r for r in _shipped_doctype_json(doctype_name)["permissions"] if r.get("role") == CBM_ROLE]

    def test_membership_row_grants_read_write_create_submit_and_no_admin_rights(self):
        # submit stays: Membership is submittable and approval inserts+submits it
        # as the session user (membership_creation_service), and a Chapter Board
        # Member must be able to approve applications for their chapter.
        self.assertTrue(_shipped_doctype_json("Membership").get("is_submittable"))
        rows = self._cbm_rows("Membership")
        self.assertEqual(len(rows), 1)
        for ptype in ("read", "write", "create", "submit"):
            self.assertEqual(rows[0].get(ptype), 1, ptype)
        for ptype in ("delete", "cancel", "amend"):
            self.assertFalse(rows[0].get(ptype), ptype)

    def test_termination_request_row_grants_read_write_and_no_admin_rights(self):
        rows = self._cbm_rows("Membership Termination Request")
        self.assertEqual(len(rows), 1)
        for ptype in ("read", "write"):
            self.assertEqual(rows[0].get(ptype), 1, ptype)
        for ptype in ("delete", "cancel", "amend"):
            self.assertFalse(rows[0].get(ptype), ptype)


if __name__ == "__main__":
    unittest.main()
