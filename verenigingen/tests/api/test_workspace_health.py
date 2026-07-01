"""
Real integration tests for verenigingen/api/workspace_health.py

Exercises the unified workspace diagnostic/repair tool against real Workspace
DocTypes in the test database. No mocking of business logic — every test builds
a real Workspace fixture, runs the real whitelisted endpoint, and asserts on the
security-decorator-wrapped nested dict response.

Return shape note:
    The whitelisted functions are wrapped by @high_security_api, which converts
    the returned OperationResult into its nested dict via to_dict(scrub_sensitive=True):

        success -> {"success": True,  "timestamp": ..., "data": {...}, "meta": {...}}
        failure -> {"success": False, "timestamp": ..., "error": {"message": ...}}

    On success, "data" holds the WorkspaceHealthManager response dict, which itself
    has its own "success"/"status"/"issues"/"fixes" keys.
"""

import json

import frappe

from verenigingen.api.workspace_health import diagnose_and_fix, health_check, quick_fix
from verenigingen.tests.utils.base import VereningingenTestCase


class TestWorkspaceHealth(VereningingenTestCase):
    """Integration tests for the workspace health API."""

    # ------------------------------------------------------------------ helpers

    def _make_workspace(self, suffix, links, content="[]"):
        """Create and track a real Workspace fixture.

        custom=1 prevents developer-mode export of the workspace to disk, so no
        stray JSON files are written into the app during tests.
        """
        name = f"ZZ WSHealth {suffix} {frappe.generate_hash(length=6)}"
        ws = frappe.get_doc(
            {
                "doctype": "Workspace",
                "name": name,
                "label": name,
                "title": name,
                "type": "Workspace",
                "public": 1,
                "custom": 1,
                "content": content,
                "links": links,
            }
        )
        ws.insert(ignore_permissions=True)
        self.track_doc("Workspace", ws.name)
        return ws

    @staticmethod
    def _synced_content(card_labels):
        """Build a content JSON that matches the given Card Break labels."""
        return json.dumps(
            [
                {"id": f"card_{i}", "type": "card", "data": {"card_name": label, "col": 6}}
                for i, label in enumerate(card_labels)
            ]
        )

    # ---------------------------------------------------------------- not found

    def test_health_check_nonexistent_workspace(self):
        """health_check on a missing workspace returns a failure envelope."""
        self.expectErrorLog("Workspace Health Check Failed")
        result = health_check("ZZ Does Not Exist " + frappe.generate_hash(length=6))

        self.assertFalse(result["success"])
        self.assertIn("error", result)
        self.assertIn("not found", result["error"]["message"].lower())

    def test_quick_fix_nonexistent_workspace(self):
        """quick_fix on a missing workspace fails with a 'does not exist' message."""
        self.expectErrorLog("Workspace Quick Fix Failed")
        result = quick_fix("ZZ Does Not Exist " + frappe.generate_hash(length=6))

        self.assertFalse(result["success"])
        self.assertIn("does not exist", result["error"]["message"].lower())

    # ------------------------------------------------------------- healthy path

    def test_health_check_healthy_workspace(self):
        """A workspace whose content matches its single Card Break is healthy."""
        card = "Section Main"
        ws = self._make_workspace(
            "healthy",
            links=[
                {"type": "Card Break", "label": card},
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member"},
            ],
            content=self._synced_content([card]),
        )

        result = health_check(ws.name)

        self.assertTrue(result["success"])
        data = result["data"]
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["issues_found"], 0)
        self.assertEqual(data["fixes_applied"], 0)

    def test_health_check_does_not_mutate(self):
        """health_check must run diagnostics only (no fix, no backup)."""
        card = "Reports"
        ws = self._make_workspace(
            "readonly",
            links=[{"type": "Card Break", "label": card}],
            content="[]",  # deliberately out of sync
        )
        original_content = frappe.db.get_value("Workspace", ws.name, "content")

        result = health_check(ws.name)

        self.assertTrue(result["success"])
        # Issues were found but nothing applied and no backup file created.
        self.assertGreaterEqual(result["data"]["issues_found"], 1)
        self.assertEqual(result["data"]["fixes_applied"], 0)
        self.assertFalse(result["data"]["backup_created"])
        # Content on disk is untouched.
        self.assertEqual(frappe.db.get_value("Workspace", ws.name, "content"), original_content)

    # -------------------------------------------------------- content sync flag

    def test_health_check_detects_content_sync_issue(self):
        """Empty content but a Card Break present -> content_sync issue reported."""
        card = "Volunteers"
        ws = self._make_workspace(
            "contentsync",
            links=[{"type": "Card Break", "label": card}],
            content="[]",
        )

        result = health_check(ws.name)

        issue_types = [i["type"] for i in result["data"]["issues"]]
        self.assertIn("content_sync", issue_types)
        sync_issue = next(i for i in result["data"]["issues"] if i["type"] == "content_sync")
        self.assertIn(card, sync_issue["details"]["missing_cards"])

    def test_health_check_detects_invalid_json_content(self):
        """Corrupt content JSON is reported as a critical content_syntax issue.

        The Workspace controller rejects non-list content on save, so this branch
        only fires on pre-existing DB corruption. Simulate that by writing invalid
        JSON straight to the column (bypassing validation), which is exactly the
        drift this tool exists to detect and repair.
        """
        ws = self._make_workspace(
            "badjson",
            links=[{"type": "Card Break", "label": "Broken"}],
            content="[]",
        )
        frappe.db.set_value(
            "Workspace", ws.name, "content", "{not valid json", update_modified=False
        )
        frappe.db.commit()
        frappe.clear_document_cache("Workspace", ws.name)

        result = health_check(ws.name)

        issue_types = [i["type"] for i in result["data"]["issues"]]
        self.assertIn("content_syntax", issue_types)
        syntax_issue = next(i for i in result["data"]["issues"] if i["type"] == "content_syntax")
        self.assertEqual(syntax_issue["severity"], "critical")

    # -------------------------------------------------------- broken link flag

    def test_broken_link_detection_is_currently_dead_code(self):
        """CHARACTERIZATION / KNOWN BUG: broken-link detection never fires.

        _check_link_validity compares ``link.type`` against "DocType"/"Report"/
        "Dashboard", but the Workspace Link ``type`` field only takes the values
        "Link" and "Card Break" -- the target kind lives in ``link_type``
        (DocType/Page/Report). So the DocType/Report/Dashboard branches are
        unreachable and broken links are never reported.

        This test pins that (buggy) behaviour: a genuinely broken DocType-kind
        link is NOT flagged. If someone fixes the bug (comparing ``link_type``
        instead of ``type``), this test will fail and must be updated to assert
        detection -- serving as an intentional tripwire on the dead code.
        """
        bogus = "ZZ No Such Doctype " + frappe.generate_hash(length=6)
        # Insert with a valid target (the controller rejects broken links on save),
        # then corrupt the child row's link_to directly to simulate a DocType that
        # was deleted after the workspace link was created.
        ws = self._make_workspace(
            "brokenlink",
            links=[
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Bogus"},
            ],
        )
        frappe.db.set_value("Workspace Link", ws.links[0].name, "link_to", bogus, update_modified=False)
        frappe.db.commit()
        frappe.clear_document_cache("Workspace", ws.name)

        result = health_check(ws.name)

        issue_types = [i["type"] for i in result["data"]["issues"]]
        self.assertNotIn("broken_links", issue_types)

    # ------------------------------------------------------- duplicate detection

    def test_distinct_card_breaks_not_flagged_as_duplicates(self):
        """Regression: two distinct Card Breaks must NOT be flagged as duplicates.

        Card Breaks carry no link_to, so a naive '<type>:<link_to>' signature makes
        every Card Break collide on 'Card Break:None'. _check_structure must skip
        link-less structural rows, otherwise auto_fix would destroy real sections.
        """
        cards = ["Section A", "Section B"]
        ws = self._make_workspace(
            "distinctcards",
            links=[
                {"type": "Card Break", "label": cards[0]},
                {"type": "Card Break", "label": cards[1]},
            ],
            content=self._synced_content(cards),
        )

        result = health_check(ws.name)

        issue_types = [i["type"] for i in result["data"]["issues"]]
        self.assertNotIn(
            "duplicate_links",
            issue_types,
            "Distinct Card Breaks were falsely reported as duplicate links",
        )

    def test_genuine_duplicate_links_still_flagged(self):
        """Two identical DocType links (real targets) are still flagged as duplicates."""
        cards = ["S"]
        ws = self._make_workspace(
            "realdupe",
            links=[
                {"type": "Card Break", "label": cards[0]},
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member One"},
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member Two"},
            ],
            content=self._synced_content(cards),
        )

        result = health_check(ws.name)

        issue_types = [i["type"] for i in result["data"]["issues"]]
        self.assertIn("duplicate_links", issue_types)
        dup = next(i for i in result["data"]["issues"] if i["type"] == "duplicate_links")
        self.assertGreaterEqual(len(dup["details"]["duplicates"]), 1)

    # ------------------------------------------------------------ auto-fix path

    def test_autofix_of_genuine_duplicate_preserves_card_breaks(self):
        """auto_fix removing a genuine duplicate DocType link must NOT also destroy
        Card Break sections.

        This is the real destructive scenario: a workspace with >=2 Card Breaks AND
        a genuine duplicate link. The detector flags the duplicate, so _apply_fixes
        calls _fix_duplicate_links -- which must skip link-less Card Breaks or it
        would collide them all on "Card Break:None" and remove every one but the
        first. Without the guard in _fix_duplicate_links this test fails (both Card
        Breaks would not survive).
        """
        cards = ["Alpha", "Beta"]
        ws = self._make_workspace(
            "autofixdupe",
            links=[
                {"type": "Card Break", "label": cards[0]},
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member One"},
                {"type": "Card Break", "label": cards[1]},
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member Two"},
            ],
            content=self._synced_content(cards),
        )

        result = diagnose_and_fix(ws.name, auto_fix=True, create_backup=False)
        self.assertTrue(result["success"])

        # Both Card Breaks must still exist after the fix; the genuine duplicate
        # Member link should be the only thing that could be removed.
        ws.reload()
        surviving_card_labels = [link.label for link in ws.links if not link.link_to]
        self.assertIn(cards[0], surviving_card_labels)
        self.assertIn(cards[1], surviving_card_labels)
        self.assertEqual(
            len([link for link in ws.links if link.type == "Card Break"]),
            2,
            "Card Break sections were destroyed by the duplicate-link fixer",
        )

    def test_diagnose_and_fix_repairs_content_sync(self):
        """diagnose_and_fix rebuilds the content field from Card Breaks."""
        card = "Administration"
        ws = self._make_workspace(
            "autofix",
            links=[{"type": "Card Break", "label": card}],
            content="[]",
        )

        result = diagnose_and_fix(ws.name, auto_fix=True, create_backup=False)

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["data"]["fixes_applied"], 1)
        fix_types = [f["type"] for f in result["data"]["fixes"]]
        self.assertIn("content_sync", fix_types)

        # The persisted content now references the Card Break as a card.
        new_content = json.loads(frappe.db.get_value("Workspace", ws.name, "content"))
        card_names = [
            item["data"]["card_name"] for item in new_content if item.get("type") == "card"
        ]
        self.assertIn(card, card_names)

    def test_diagnose_and_fix_without_autofix_leaves_content(self):
        """auto_fix=False reports issues but applies no fixes and leaves content."""
        card = "Finance"
        ws = self._make_workspace(
            "noautofix",
            links=[{"type": "Card Break", "label": card}],
            content="[]",
        )

        result = diagnose_and_fix(ws.name, auto_fix=False, create_backup=False)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["fixes_applied"], 0)
        self.assertGreaterEqual(result["data"]["issues_found"], 1)
        self.assertEqual(frappe.db.get_value("Workspace", ws.name, "content"), "[]")

    # ------------------------------------------------------------- quick_fix path

    def test_quick_fix_syncs_card_breaks(self):
        """quick_fix writes a content structure covering all Card Breaks."""
        cards = ["Alpha", "Beta", "Gamma"]
        ws = self._make_workspace(
            "quickfix",
            links=[{"type": "Card Break", "label": c} for c in cards],
            content="[]",
        )

        result = quick_fix(ws.name)

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["cards_count"], len(cards))
        self.assertEqual(sorted(result["data"]["cards_synced"]), sorted(cards))

        new_content = json.loads(frappe.db.get_value("Workspace", ws.name, "content"))
        card_names = [item["data"]["card_name"] for item in new_content if item.get("type") == "card"]
        self.assertEqual(sorted(card_names), sorted(cards))

    def test_quick_fix_no_card_breaks_fails(self):
        """quick_fix on a workspace with no Card Breaks returns a failure."""
        ws = self._make_workspace(
            "nocards",
            links=[
                {"type": "Link", "link_type": "DocType", "link_to": "Member", "label": "Member"},
            ],
        )

        self.expectErrorLog("Workspace Quick Fix Failed")
        result = quick_fix(ws.name)

        self.assertFalse(result["success"])
        self.assertIn("no card breaks", result["error"]["message"].lower())
