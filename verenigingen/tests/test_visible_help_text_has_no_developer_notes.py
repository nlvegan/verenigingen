"""Help text an admin can see carries no developer notes (#1648, follow-up to #1605).

Field descriptions on DocType forms and the ``description`` of shipped Critical
Operation Rule rows are shown to association admins. Issue numbers and source
file names mean nothing to them. SCOPE: the guard catches issue refs (#NN) and
``.py`` file names ONLY. It does NOT catch snake_case or function names (a
description saying ``pause_until`` stays green); a generic snake_case regex would
flag legitimate examples such as ``chapter_assignment``. Hidden fields are never shown, so developer
notes on them are left alone. The walk is over the shipped JSON, not a site's DB.
"""

import json
import re
import unittest
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
DEVELOPER_NOTE = re.compile(r"#\d{2,5}\b|\b\w+\.py\b")
COR_FIXTURES = sorted((APP_ROOT / "fixtures").glob("critical_operation_rule*.json"))
DONATION_JSON = APP_ROOT / "verenigingen" / "doctype" / "donation" / "donation.json"


def _developer_notes_in_visible_fields(fields):
    """Return (fieldname, description) for every non-hidden field with a developer note."""
    return [
        (f.get("fieldname"), f["description"])
        for f in fields
        if not f.get("hidden") and DEVELOPER_NOTE.search(f.get("description") or "")
    ]


class TestVisibleHelpTextHasNoDeveloperNotes(unittest.TestCase):
    def test_visible_doctype_field_descriptions_have_no_issue_refs_or_py_paths(self):
        offenders = []
        for path in sorted(APP_ROOT.rglob("doctype/*/*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if not isinstance(data, dict) or data.get("doctype") != "DocType":
                continue
            for fieldname, text in _developer_notes_in_visible_fields(data.get("fields") or []):
                offenders.append(f"{data['name']}.{fieldname}: {text[:90]}")
        self.assertEqual(offenders, [])

    def test_critical_operation_rule_fixture_descriptions_have_no_issue_refs(self):
        self.assertGreaterEqual(len(COR_FIXTURES), 4, "fixture glob found too few files")
        rows = [r for p in COR_FIXTURES for r in json.loads(p.read_text(encoding="utf-8"))]
        self.assertGreater(len(rows), 100, "fixtures unexpectedly small; scan would prove nothing")
        offenders = [
            f"{r.get('name')}: {r['description']}"
            for r in rows
            if DEVELOPER_NOTE.search(r.get("description") or "")
        ]
        self.assertEqual(offenders, [])

    def test_the_scan_can_fail(self):
        """Control: a visible note is flagged, the same note on a hidden field is not."""
        fields = [
            {"fieldname": "shown", "description": "Retry endpoint (#969)"},
            {"fieldname": "path", "description": "See services/account_creation_manager.py"},
            {"fieldname": "hidden_one", "description": "Retry endpoint (#969)", "hidden": 1},
            {"fieldname": "clean", "description": "Retry endpoint"},
        ]
        self.assertEqual([n for n, _ in _developer_notes_in_visible_fields(fields)], ["shown", "path"])

    def test_recurring_cancelled_date_help_says_mollie_subscriptions_are_different(self):
        """get_recurring_donation_state() ignores the date when a Mollie subscription is set."""
        data = json.loads(DONATION_JSON.read_text(encoding="utf-8"))
        field = next(f for f in data["fields"] if f["fieldname"] == "recurring_cancelled_date")
        self.assertIn("Mollie subscription", field["description"])
