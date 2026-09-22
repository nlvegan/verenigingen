"""Regression test for #1208.

Chapter's "View Board History" button (chapter.js, `show_board_history()`) used to
dispatch via `frappe.call({method: 'get_board_members', doc: frm.doc, ...})`. That
is a `run_doc_method` doc-bound dispatch, and `Chapter.get_board_members` has never
carried `@frappe.whitelist()` -- so every click refused with a PermissionError
before any board-history logic ran (surfaced to the user via the button's own
`error()` handler). Filed as part of the UI/route/template/client census, #1210.

The fix repoints the button at the already-existing, already-permission-checked
module-level twin `get_chapter_board_history(chapter_name)`
(`chapter.py`), which:
  - IS whitelisted (`@frappe.whitelist()` outermost, per this app's decorator rule)
  - gates on `ChapterPermissionService.can_user_view_chapter_board_history()`
    (admin, or an active board member of THAT chapter) rather than plain doc read
    permission -- which matters, because ordinary doc `read` permission on Chapter
    is granted to every "Verenigingen Member" for published chapters
    (`has_chapter_permission`), which would have been a much wider gate than the
    board-history feature intends.
  - returns the exact same shape the button already expects: `chapter.get_board_
    members(include_inactive=True)`, a plain list of dicts.

Two things are tested:
  1. A wiring ratchet: the `show_board_history()` call target in chapter.js must
     resolve to something in `frappe.whitelisted` -- so this test is RED against
     the pre-fix JS (doc-bound `get_board_members`, unwhitelisted) and GREEN
     against the fixed JS (dotted `get_chapter_board_history`, whitelisted).
  2. The real dispatch path, end to end: a board member of the chapter gets real
     board data back; a "Verenigingen Member" user who is not on this chapter's
     board is refused with a PermissionError (empirically, via the
     @high_security_api tier gate rather than the chapter-scoped check --
     see the docstring on test_non_board_member_does_not_see_board_history).
"""

import re
from pathlib import Path

import frappe

from verenigingen.tests.fixtures.enhanced_test_factory import EnhancedTestCase
from verenigingen.verenigingen.doctype.chapter.chapter import Chapter

CHAPTER_JS = Path(__file__).resolve().parents[2] / "verenigingen" / "doctype" / "chapter" / "chapter.js"


def _show_board_history_call_block():
    """Extract the `frappe.call({...})` object literal inside chapter.js's
    `show_board_history` function -- NOT the whole function body, so that an
    explanatory comment mentioning `doc: frm.doc` in prose doesn't get parsed
    as if it were a real dispatch argument."""
    text = CHAPTER_JS.read_text(encoding="utf-8")
    func_match = re.search(r"function show_board_history\(frm\)\s*\{(.*?)\n\}\n", text, re.DOTALL)
    assert func_match, "show_board_history() not found in chapter.js -- has it been renamed/removed?"
    call_match = re.search(r"frappe\.call\(\{(.*?)\n\t\}\);", func_match.group(1), re.DOTALL)
    assert call_match, f"no frappe.call({{...}}) found in show_board_history():\n{func_match.group(1)}"
    return call_match.group(1)


def _resolve_show_board_history_target():
    """Return the whitelist-checkable callable the button's frappe.call() targets.

    Handles both dispatch shapes seen in this app's doctype JS:
      - doc-bound: `method: '<name>', doc: frm.doc` -> Chapter.<name> (unbound)
      - dotted:    `method: 'a.b.c.<name>'` with no `doc:` key -> frappe.get_attr(...)
    """
    block = _show_board_history_call_block()
    method_match = re.search(r"""method:\s*['"]([\w.]+)['"]""", block)
    assert method_match, f"no method: found in show_board_history() body:\n{block}"
    method = method_match.group(1)

    if "." in method:
        # Dotted module-level path -- must not also be doc-bound.
        assert "doc: frm.doc" not in block and "doc:frm.doc" not in block, (
            f"method {method!r} looks like a dotted path but the call also passes "
            "doc: frm.doc -- that combination is not a real dispatch shape, fix the test"
        )
        return frappe.get_attr(method)

    assert "doc: frm.doc" in block or "doc:frm.doc" in block, (
        f"method {method!r} has no dots (looks doc-bound) but no doc: frm.doc was found "
        f"in the call block:\n{block}"
    )
    return getattr(Chapter, method)


class TestChapterBoardHistoryButtonWhitelist(EnhancedTestCase):
    def test_show_board_history_targets_a_whitelisted_endpoint(self):
        """RED pre-fix (doc-bound get_board_members, never whitelisted),
        GREEN post-fix (dotted get_chapter_board_history, whitelisted)."""
        target = _resolve_show_board_history_target()
        self.assertIn(
            target,
            frappe.whitelisted,
            "chapter.js's 'View Board History' button targets a method that is not "
            "whitelisted, so every click will refuse with a PermissionError (#1208)",
        )

    def test_the_control_would_have_caught_the_pre_fix_target(self):
        """Control for the test above: prove the resolver can still recognize the
        OLD, broken doc-bound target as unwhitelisted, so a resolver that always
        returns something in frappe.whitelisted (e.g. a bug that resolves the
        wrong symbol) would not silently pass."""
        self.assertNotIn(Chapter.get_board_members, frappe.whitelisted)

    def test_board_member_sees_real_board_history_through_the_real_dispatch_path(self):
        """A board member of the chapter, calling the exact whitelisted function
        the fixed button targets, gets real board data back."""
        chapter = self.create_chapter()
        seat = self.create_test_board_member(chapter.name, permissions_level="Admin")

        target = _resolve_show_board_history_target()
        self.assertIn(target, frappe.whitelisted)

        with self.as_user(seat.user):
            result = target(chapter_name=chapter.name)

        self.assertTrue(
            any(row.get("volunteer") == seat.volunteer for row in result),
            f"expected the seated board member's volunteer {seat.volunteer!r} in the "
            f"returned board history, got: {result}",
        )

    def test_non_board_member_does_not_see_board_history(self):
        """A 'Verenigingen Member' who is not on this chapter's board is refused.

        Measured empirically: the refusal happens at the @high_security_api
        decorator's own tier gate (verenigingen.utils.security.api_security_
        framework), which denies HIGH-tier access before get_chapter_board_
        history()'s own body -- and its can_user_view_chapter_board_history()
        check -- ever runs. A bare 'Verenigingen Member' role carries no role
        profile mapped to HIGH/MEDIUM/LOW (authorization_policy.py), so
        validate_authentication() raises first. The seated board member in the
        positive test above clears this same gate only because create_test_
        board_member() also assigns the 'Verenigingen Chapter Board Member'
        role PROFILE, not just the role. Assert the exception actually raised
        (a PermissionError subclass), not one inferred from reading the source.
        """
        chapter = self.create_chapter()
        # Seed a real board member so the chapter has non-empty history to withhold.
        self.create_test_board_member(chapter.name, permissions_level="Admin")

        outsider = self.create_test_user(
            email=f"outsider-{frappe.generate_hash(length=8)}@example.com",
            roles=["Verenigingen Member"],
        )

        target = _resolve_show_board_history_target()

        with self.as_user(outsider.name):
            with self.assertRaises(frappe.PermissionError):
                target(chapter_name=chapter.name)
