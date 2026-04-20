# Chapter Board Member-Lifecycle Notifications — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify chapter boards when members are assigned to, transferred between, or removed from their chapter.

**Architecture:** Centralize notifications in the existing `ChapterMember.after_insert` / `on_trash` hooks, so every code path (approval, admin edit, transfer helper, direct service call) triggers them automatically. A request-scoped `frappe.flags.chapter_transfer` flag set by `transfer_member_between_chapters()` tells the hooks whether to emit "transferred in/out" vs. plain "joined/left" templates. Suppression via existing `is_bulk_import` / `suppress_chapter_notifications` flags and the `send_chapter_assignment_notifications` setting (default flipped 0 → 1). Email delivery uses `EmailService.send_templated_email()` (the non-deprecated API).

**Tech Stack:** Frappe Framework (Python), ERPNext patterns, Email Template DocType fixtures, existing `EmailService` + notification registry.

**Design reference:** `docs/plans/2026-04-20-chapter-board-lifecycle-notifications-design.md`

---

## File Structure

**Create:**
- `verenigingen/patches/v2_1/enable_chapter_notifications_default_for_new_installs.py` — NULL-only migration
- `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py` — integration tests

**Modify:**
- `verenigingen/notification_registry.py` — add 2 transfer keys
- `verenigingen/fixtures/email_template.json` — add 4 templates
- `verenigingen/services/chapter/chapter_membership_manager.py` — transfer flag plumbing
- `verenigingen/verenigingen/doctype/chapter_member/chapter_member.py` — new board helpers + hook calls
- `verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json` — default 0 → 1
- `verenigingen/patches.txt` — register new patch

---

## Task 1: Register transfer notification keys

Add two entries to the notification registry. `chapter_member_joined` and `chapter_member_left` already exist.

**Files:**
- Modify: `verenigingen/notification_registry.py`

- [ ] **Step 1: Add registry entries**

In `verenigingen/notification_registry.py`, find the "CHAPTER NOTIFICATIONS" section (around line 173-238, after `chapter_join_request_rejected`) and add:

```python
    "chapter_member_transferred_in": {
        "label": "Chapter Member Transferred In",
        "category": CATEGORY_CHAPTER,
        "description": "Sent to board when a member transfers into the chapter from another chapter.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
    "chapter_member_transferred_out": {
        "label": "Chapter Member Transferred Out",
        "category": CATEGORY_CHAPTER,
        "description": "Sent to board when a member transfers out of the chapter to another chapter.",
        "priority": PRIORITY_LOW,
        "recipient_policy": POLICY_ROLE_BASED,
    },
```

- [ ] **Step 2: Verify registry validates**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute verenigingen.notification_registry.validate_notification_key --kwargs "{'notification_key': 'chapter_member_transferred_in'}"
```
Expected output: `True`

Same for `chapter_member_transferred_out` — expected `True`.

- [ ] **Step 3: Commit**

```bash
git add verenigingen/notification_registry.py
git commit -m "feat(notifications): register chapter transfer lifecycle keys"
```

---

## Task 2: Add four Email Template fixtures

Templates stored in the existing `fixtures/email_template.json` file (a JSON array). Each new template follows the structure already used by `chapter_membership_approved`.

**Files:**
- Modify: `verenigingen/fixtures/email_template.json`

- [ ] **Step 1: Append four new Email Template entries to the JSON array**

Open `verenigingen/fixtures/email_template.json`. The file is a JSON array of Email Template objects. Append the following four objects (mind the preceding comma on the previous closing `}`):

```json
  {
    "docstatus": 0,
    "doctype": "Email Template",
    "enabled": 1,
    "modified": "2026-04-20 12:00:00",
    "name": "chapter_board_member_joined",
    "reference_doctype": null,
    "response": null,
    "response_html": "<div class=\"email-container\">\n    <div class=\"email-header-success\">\n        <h2 class=\"email-title\">New member in {{ chapter_name|e }}</h2>\n        <p class=\"email-subtitle\">{{ (organization_name or company or \"Our Organization\")|e }}</p>\n    </div>\n    <div class=\"email-content\">\n        <p>Dear Board Member,</p>\n        <p><strong>{{ member_name|e }}</strong> just joined <strong>{{ chapter_name|e }}</strong>.</p>\n        <div class=\"email-content-box\">\n            <table class=\"email-data-table\"><tbody>\n                <tr><td><strong>Member:</strong></td><td>{{ member_name|e }}</td></tr>\n                <tr><td><strong>Member ID:</strong></td><td><a href=\"{{ member_link|e }}\">{{ member_id|e }}</a></td></tr>\n                <tr><td><strong>Joined:</strong></td><td>{{ effective_date|e }}</td></tr>\n            </tbody></table>\n        </div>\n        <hr><div class=\"email-footer\">Automated notification from the chapter management system.<br>{{ chapter_name|e }} \u00b7 {{ current_year }}</div>\n    </div>\n</div>",
    "subject": "New member in {{ chapter_name|e }}: {{ member_name|e }}",
    "use_html": 1
  },
  {
    "docstatus": 0,
    "doctype": "Email Template",
    "enabled": 1,
    "modified": "2026-04-20 12:00:00",
    "name": "chapter_board_member_left",
    "reference_doctype": null,
    "response": null,
    "response_html": "<div class=\"email-container\">\n    <div class=\"email-header-warning\">\n        <h2 class=\"email-title\">Member left {{ chapter_name|e }}</h2>\n        <p class=\"email-subtitle\">{{ (organization_name or company or \"Our Organization\")|e }}</p>\n    </div>\n    <div class=\"email-content\">\n        <p>Dear Board Member,</p>\n        <p><strong>{{ member_name|e }}</strong> has left <strong>{{ chapter_name|e }}</strong>.</p>\n        <div class=\"email-content-box\">\n            <table class=\"email-data-table\"><tbody>\n                <tr><td><strong>Member:</strong></td><td>{{ member_name|e }}</td></tr>\n                <tr><td><strong>Member ID:</strong></td><td><a href=\"{{ member_link|e }}\">{{ member_id|e }}</a></td></tr>\n                <tr><td><strong>Effective date:</strong></td><td>{{ effective_date|e }}</td></tr>\n                {% if leave_reason %}<tr><td><strong>Reason:</strong></td><td>{{ leave_reason|e }}</td></tr>{% endif %}\n            </tbody></table>\n        </div>\n        <hr><div class=\"email-footer\">Automated notification from the chapter management system.<br>{{ chapter_name|e }} \u00b7 {{ current_year }}</div>\n    </div>\n</div>",
    "subject": "Member left {{ chapter_name|e }}: {{ member_name|e }}",
    "use_html": 1
  },
  {
    "docstatus": 0,
    "doctype": "Email Template",
    "enabled": 1,
    "modified": "2026-04-20 12:00:00",
    "name": "chapter_board_member_transferred_in",
    "reference_doctype": null,
    "response": null,
    "response_html": "<div class=\"email-container\">\n    <div class=\"email-header-info\">\n        <h2 class=\"email-title\">Member transferred to {{ chapter_name|e }}</h2>\n        <p class=\"email-subtitle\">{{ (organization_name or company or \"Our Organization\")|e }}</p>\n    </div>\n    <div class=\"email-content\">\n        <p>Dear Board Member,</p>\n        <p><strong>{{ member_name|e }}</strong> transferred into <strong>{{ chapter_name|e }}</strong> from <strong>{{ other_chapter|e }}</strong>.</p>\n        <div class=\"email-content-box\">\n            <table class=\"email-data-table\"><tbody>\n                <tr><td><strong>Member:</strong></td><td>{{ member_name|e }}</td></tr>\n                <tr><td><strong>Member ID:</strong></td><td><a href=\"{{ member_link|e }}\">{{ member_id|e }}</a></td></tr>\n                <tr><td><strong>From chapter:</strong></td><td>{{ other_chapter|e }}</td></tr>\n                <tr><td><strong>Effective date:</strong></td><td>{{ effective_date|e }}</td></tr>\n            </tbody></table>\n        </div>\n        <hr><div class=\"email-footer\">Automated notification from the chapter management system.<br>{{ chapter_name|e }} \u00b7 {{ current_year }}</div>\n    </div>\n</div>",
    "subject": "{{ member_name|e }} transferred to {{ chapter_name|e }}",
    "use_html": 1
  },
  {
    "docstatus": 0,
    "doctype": "Email Template",
    "enabled": 1,
    "modified": "2026-04-20 12:00:00",
    "name": "chapter_board_member_transferred_out",
    "reference_doctype": null,
    "response": null,
    "response_html": "<div class=\"email-container\">\n    <div class=\"email-header-info\">\n        <h2 class=\"email-title\">Member transferred from {{ chapter_name|e }}</h2>\n        <p class=\"email-subtitle\">{{ (organization_name or company or \"Our Organization\")|e }}</p>\n    </div>\n    <div class=\"email-content\">\n        <p>Dear Board Member,</p>\n        <p><strong>{{ member_name|e }}</strong> transferred from <strong>{{ chapter_name|e }}</strong> to <strong>{{ other_chapter|e }}</strong>.</p>\n        <div class=\"email-content-box\">\n            <table class=\"email-data-table\"><tbody>\n                <tr><td><strong>Member:</strong></td><td>{{ member_name|e }}</td></tr>\n                <tr><td><strong>Member ID:</strong></td><td><a href=\"{{ member_link|e }}\">{{ member_id|e }}</a></td></tr>\n                <tr><td><strong>To chapter:</strong></td><td>{{ other_chapter|e }}</td></tr>\n                <tr><td><strong>Effective date:</strong></td><td>{{ effective_date|e }}</td></tr>\n            </tbody></table>\n        </div>\n        <hr><div class=\"email-footer\">Automated notification from the chapter management system.<br>{{ chapter_name|e }} \u00b7 {{ current_year }}</div>\n    </div>\n</div>",
    "subject": "{{ member_name|e }} transferred from {{ chapter_name|e }}",
    "use_html": 1
  }
```

- [ ] **Step 2: Validate JSON syntax**

Run:
```bash
cd ~/frappe-bench/apps/verenigingen && python -c "import json; json.load(open('verenigingen/fixtures/email_template.json'))"
```
Expected: no output (silent success). A `JSONDecodeError` means the comma placement is wrong — recheck that every object except the last has a trailing comma.

- [ ] **Step 3: Install fixtures into the site**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
```
Expected: migration completes; new Email Template records are created. Verify:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute frappe.client.get_list --kwargs '{"doctype": "Email Template", "filters": {"name": ["like", "chapter_board_member_%"]}, "pluck": "name"}'
```
Expected: list contains all four template names.

- [ ] **Step 4: Commit**

```bash
git add verenigingen/fixtures/email_template.json
git commit -m "feat(email): add chapter board member-lifecycle email templates"
```

---

## Task 3: Transfer-flag plumbing in ChapterMembershipManager

Wrap `transfer_member_between_chapters()` body in a try/finally that sets and clears `frappe.flags.chapter_transfer`. Hooks on `ChapterMember` will read this flag.

**Files:**
- Modify: `verenigingen/services/chapter/chapter_membership_manager.py:244-326`
- Test: `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py` (new file, begun here)

- [ ] **Step 1: Create test file skeleton with a failing test**

Create `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py`:

```python
"""Integration tests for chapter board member-lifecycle notifications."""

import frappe
from frappe.tests.utils import FrappeTestCase

from verenigingen.services.chapter.chapter_membership_manager import ChapterMembershipManager
from verenigingen.tests.fixtures.core_test_data_factory import CoreTestDataFactory


class TestChapterBoardLifecycleNotifications(FrappeTestCase):
    """Verify chapter boards get notified on member join/leave/transfer."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.factory = CoreTestDataFactory(seed="board-lifecycle-notifications")

    def setUp(self):
        super().setUp()
        # Ensure the feature setting is on for tests
        frappe.db.set_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications", 1
        )
        # Clear any stale flags from other tests
        frappe.flags.chapter_transfer = None
        frappe.flags.is_bulk_import = False
        frappe.flags.suppress_chapter_notifications = False
        # Clear the Email Queue so assertions only see this test's emails
        frappe.db.delete("Email Queue")
        frappe.db.commit()

    def tearDown(self):
        frappe.flags.chapter_transfer = None
        super().tearDown()

    def test_transfer_sets_and_clears_flag(self):
        """transfer_member_between_chapters sets chapter_transfer flag and clears it after."""
        member = self.factory.create_member()
        chapter_a = self.factory.create_chapter()
        chapter_b = self.factory.create_chapter()
        # Pre-assign to chapter A (bypass notifications during setup)
        frappe.flags.suppress_chapter_notifications = True
        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter_a.name)
        frappe.flags.suppress_chapter_notifications = False

        captured = {}

        def spy(*args, **kwargs):
            captured["flag_during"] = dict(frappe.flags.get("chapter_transfer") or {})

        # Monkey-patch assign_member_to_chapter to capture the flag mid-call
        original = ChapterMembershipManager.assign_member_to_chapter

        def wrapped(member_id, chapter_name, **kw):
            spy()
            return original(member_id, chapter_name, **kw)

        ChapterMembershipManager.assign_member_to_chapter = staticmethod(wrapped)
        try:
            ChapterMembershipManager.transfer_member_between_chapters(
                member.name, chapter_a.name, chapter_b.name
            )
        finally:
            ChapterMembershipManager.assign_member_to_chapter = staticmethod(original)

        self.assertEqual(captured["flag_during"].get("member"), member.name)
        self.assertEqual(captured["flag_during"].get("from"), chapter_a.name)
        self.assertEqual(captured["flag_during"].get("to"), chapter_b.name)
        # Flag cleared afterwards
        self.assertIsNone(frappe.flags.get("chapter_transfer"))

    def test_transfer_clears_flag_on_failure(self):
        """Flag is cleared even when transfer raises mid-way."""
        member = self.factory.create_member()
        chapter_a = self.factory.create_chapter()

        frappe.flags.chapter_transfer = None
        # Calling with a nonexistent destination triggers the error path inside
        # leave_chapter / assign_member_to_chapter; the wrapper's finally must
        # still clear the flag.
        ChapterMembershipManager.transfer_member_between_chapters(
            member.name, chapter_a.name, "Nonexistent-Chapter-" + frappe.generate_hash(length=6)
        )
        self.assertIsNone(frappe.flags.get("chapter_transfer"))
```

- [ ] **Step 2: Run the tests, verify they fail**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: both tests fail. `test_transfer_sets_and_clears_flag` fails because the flag is never set. `test_transfer_clears_flag_on_failure` passes vacuously only if the flag is `None` (it may or may not be; either way the key assertion to lock in is that the flag plumbing exists).

- [ ] **Step 3: Add the flag plumbing**

In `verenigingen/services/chapter/chapter_membership_manager.py`, replace the body of `transfer_member_between_chapters` (starting at line 261 `try:`) with:

```python
        frappe.flags.chapter_transfer = {
            "member": member_id,
            "from": from_chapter,
            "to": to_chapter,
        }
        try:
            # First, leave the old chapter
            leave_result = ChapterMembershipManager.leave_chapter(
                member_id=member_id,
                chapter_name=from_chapter,
                leave_reason=reason or f"Transferred to {to_chapter}",
                permanent=False,
            )

            if not leave_result.get("success"):
                return {
                    "success": False,
                    "error": f"Failed to leave {from_chapter}: {leave_result.get('error')}",
                }

            # Then, join the new chapter
            join_result = ChapterMembershipManager.assign_member_to_chapter(
                member_id=member_id,
                chapter_name=to_chapter,
                reason=reason or f"Transferred from {from_chapter}",
                assigned_by=assigned_by,
            )

            if not join_result.get("success"):
                return {"success": False, "error": f"Failed to join {to_chapter}: {join_result.get('error')}"}

            # Log the transfer
            transfer_comment = frappe.get_doc(
                {
                    "doctype": "Comment",
                    "comment_type": "Info",
                    "reference_doctype": "Member",
                    "reference_name": member_id,
                    "content": _("Transferred from {0} to {1}. Reason: {2}").format(
                        from_chapter, to_chapter, reason or "Administrative transfer"
                    ),
                }
            )

            # CORRECTED SECURE VERSION: Use proper secure operations with explicit permission validation
            result = secure_document_operation(
                operation="insert",
                doc=transfer_comment,
                justification=f"Log chapter transfer for member {member_id} from {from_chapter} to {to_chapter} - administrative audit trail for member organization",
                required_permissions=["Comment:create"],
            )

            if not result.success:
                frappe.log_error(
                    f"Failed to log chapter transfer comment: {'; '.join(result.errors)}",
                    "Chapter Transfer Security",
                )

            return {
                "success": True,
                "message": _("Successfully transferred member from {0} to {1}").format(
                    from_chapter, to_chapter
                ),
                "action": "transferred",
            }

        except Exception as e:
            frappe.log_error(
                f"Error in transfer_member_between_chapters: {str(e)}", "ChapterMembershipManager"
            )
            return {"success": False, "error": str(e)}
        finally:
            frappe.flags.chapter_transfer = None
```

Note: this is the same body as before, but wrapped so the flag is set at the top and cleared in a `finally`. The inner `try/except` for logging stays unchanged.

- [ ] **Step 4: Run the tests, verify they pass**

Run:
```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/services/chapter/chapter_membership_manager.py verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py
git commit -m "feat(chapter): set chapter_transfer flag during transfer for hook disambiguation"
```

---

## Task 4: Board notification helpers on ChapterMember

Add `_notify_board_of_member_joined` and `_notify_board_of_member_left` methods to the `ChapterMember` controller, and call them from `after_insert` / `on_trash` respectively. Each helper handles transfer-aware branching internally by reading `frappe.flags.chapter_transfer`. Suppression rules (setting + bulk flag + suppress flag) gate whether the email is actually sent.

**Files:**
- Modify: `verenigingen/verenigingen/doctype/chapter_member/chapter_member.py`
- Test: `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py`

- [ ] **Step 1: Add failing tests for joined/left notifications**

Append to `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py` (inside the existing class):

```python
    def _emails_sent_to(self, recipient_email):
        """Return list of Email Queue subjects sent to the given recipient, newest first."""
        rows = frappe.db.sql(
            """
            SELECT eq.subject FROM `tabEmail Queue` eq
            JOIN `tabEmail Queue Recipient` eqr ON eqr.parent = eq.name
            WHERE eqr.recipient = %s
            ORDER BY eq.creation DESC
            """,
            recipient_email,
            as_dict=True,
        )
        return [r["subject"] for r in rows]

    def _ensure_chapter_role(self):
        """Ensure a basic Chapter Role exists for board-member rows."""
        name = "Test Board Role"
        if not frappe.db.exists("Chapter Role", name):
            frappe.get_doc({
                "doctype": "Chapter Role",
                "role_name": name,
                "permissions_level": "Basic",
                "is_chair": 0,
                "is_unique": 0,
            }).insert(ignore_permissions=True)
        return name

    def _make_chapter_with_board(self, member_emails):
        """Create a chapter with active board members. Each entry in member_emails
        creates one member with that email and adds them as an active board row.
        Returns (chapter, [board_member_records])."""
        chapter = self.factory.create_chapter()
        role = self._ensure_chapter_role()
        board_members = []
        for email in member_emails:
            bm_member = self.factory.create_member(email=email)
            chapter.append(
                "board_members",
                {
                    "member": bm_member.name,
                    "is_active": 1,
                    "chapter_role": role,
                    "from_date": frappe.utils.today(),
                },
            )
            board_members.append(bm_member)
        chapter.save()
        return chapter, board_members

    def test_plain_join_notifies_board(self):
        """Adding a ChapterMember (no transfer flag) sends chapter_board_member_joined to the board."""
        chapter, board = self._make_chapter_with_board(["board1@example.com", "board2@example.com"])
        member = self.factory.create_member()

        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)

        subjects = self._emails_sent_to("board1@example.com")
        self.assertTrue(
            any(f"New member in {chapter.name}" in s for s in subjects),
            f"Expected 'joined' email in {subjects}",
        )
        subjects2 = self._emails_sent_to("board2@example.com")
        self.assertTrue(any(f"New member in {chapter.name}" in s for s in subjects2))

    def test_plain_leave_notifies_board(self):
        """Removing a ChapterMember (no transfer flag) sends chapter_board_member_left to the board."""
        chapter, board = self._make_chapter_with_board(["bleft@example.com"])
        member = self.factory.create_member()
        frappe.flags.suppress_chapter_notifications = True
        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name)
        frappe.flags.suppress_chapter_notifications = False
        frappe.db.delete("Email Queue")
        frappe.db.commit()

        ChapterMembershipManager.leave_chapter(member.name, chapter.name, leave_reason="Moving away")

        subjects = self._emails_sent_to("bleft@example.com")
        self.assertTrue(
            any(f"Member left {chapter.name}" in s for s in subjects),
            f"Expected 'left' email in {subjects}",
        )

    def test_setting_disabled_blocks_notification(self):
        """send_chapter_assignment_notifications=0 blocks emails even when notify=True."""
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 0)
        chapter, board = self._make_chapter_with_board(["setting@example.com"])
        member = self.factory.create_member()

        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)

        self.assertEqual(self._emails_sent_to("setting@example.com"), [])

    def test_bulk_import_flag_blocks_notification(self):
        """frappe.flags.is_bulk_import=True blocks board emails."""
        chapter, board = self._make_chapter_with_board(["bulk@example.com"])
        member = self.factory.create_member()

        frappe.flags.is_bulk_import = True
        try:
            ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)
        finally:
            frappe.flags.is_bulk_import = False

        self.assertEqual(self._emails_sent_to("bulk@example.com"), [])

    def test_suppress_flag_blocks_notification(self):
        """frappe.flags.suppress_chapter_notifications=True blocks board emails."""
        chapter, board = self._make_chapter_with_board(["supp@example.com"])
        member = self.factory.create_member()

        frappe.flags.suppress_chapter_notifications = True
        try:
            ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name)
        finally:
            frappe.flags.suppress_chapter_notifications = False

        self.assertEqual(self._emails_sent_to("supp@example.com"), [])

    def test_inactive_board_members_not_notified(self):
        """Only is_active=1 board rows receive the email."""
        chapter = self.factory.create_chapter()
        role = self._ensure_chapter_role()
        active_bm = self.factory.create_member(email="active-bm@example.com")
        inactive_bm = self.factory.create_member(email="inactive-bm@example.com")
        chapter.append("board_members", {
            "member": active_bm.name, "is_active": 1,
            "chapter_role": role,
            "from_date": frappe.utils.today(),
        })
        chapter.append("board_members", {
            "member": inactive_bm.name, "is_active": 0,
            "chapter_role": role,
            "from_date": frappe.utils.today(),
        })
        chapter.save()
        member = self.factory.create_member()

        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter.name, notify=True)

        self.assertTrue(self._emails_sent_to("active-bm@example.com"))
        self.assertFalse(self._emails_sent_to("inactive-bm@example.com"))
```

**Factory compatibility note:** The tests assume `CoreTestDataFactory.create_member(email=...)` and `CoreTestDataFactory.create_chapter()` exist. If either signature differs, adjust the test helpers by creating Members/Chapters directly via `frappe.get_doc({...}).insert(ignore_permissions=True)` — the rest of the test logic is factory-agnostic.

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: The 6 new tests fail because no board notification is being sent. `test_setting_disabled_blocks_notification`, `test_bulk_import_flag_blocks_notification`, `test_suppress_flag_blocks_notification`, `test_inactive_board_members_not_notified` may "pass" trivially (no emails expected, none sent) — that's fine; the positive tests will drive the implementation.

- [ ] **Step 3: Add the helpers to ChapterMember**

In `verenigingen/verenigingen/doctype/chapter_member/chapter_member.py`, replace the `after_insert` and `on_trash` methods (lines 12-18) and add the two new helpers plus a shared gate function. Full replacement:

```python
    def after_insert(self):
        """Handle new chapter member creation"""
        self._send_chapter_welcome_notification()
        self._notify_board_of_member_joined()

    def on_trash(self):
        """Handle chapter member removal"""
        self._send_chapter_farewell_notification()
        self._notify_board_of_member_left()
```

Then add the following two new methods anywhere in the class (e.g., directly after `_send_chapter_farewell_notification`):

```python
    def _notify_board_of_member_joined(self):
        """Notify the chapter board that a member joined (or transferred in)."""
        if not self._board_lifecycle_notifications_enabled():
            return

        transfer = frappe.flags.get("chapter_transfer") or {}
        is_transfer_in = (
            transfer.get("member") == self.member and transfer.get("to") == self.parent
        )
        template = (
            "chapter_board_member_transferred_in"
            if is_transfer_in
            else "chapter_board_member_joined"
        )
        notification_key = (
            "chapter_member_transferred_in" if is_transfer_in else "chapter_member_joined"
        )
        other_chapter = transfer.get("from") if is_transfer_in else None

        self._dispatch_board_notification(
            template_name=template,
            notification_key=notification_key,
            other_chapter=other_chapter,
            effective_date=self.chapter_join_date or frappe.utils.today(),
        )

    def _notify_board_of_member_left(self):
        """Notify the chapter board that a member left (or transferred out)."""
        if not self._board_lifecycle_notifications_enabled():
            return

        transfer = frappe.flags.get("chapter_transfer") or {}
        is_transfer_out = (
            transfer.get("member") == self.member and transfer.get("from") == self.parent
        )
        template = (
            "chapter_board_member_transferred_out"
            if is_transfer_out
            else "chapter_board_member_left"
        )
        notification_key = (
            "chapter_member_transferred_out" if is_transfer_out else "chapter_member_left"
        )
        other_chapter = transfer.get("to") if is_transfer_out else None

        self._dispatch_board_notification(
            template_name=template,
            notification_key=notification_key,
            other_chapter=other_chapter,
            effective_date=frappe.utils.today(),
        )

    def _board_lifecycle_notifications_enabled(self):
        """Gate: returns True only if all suppression rules pass."""
        if not self.member or not self.parent:
            return False
        if getattr(frappe.flags, "is_bulk_import", False):
            return False
        if getattr(frappe.flags, "suppress_chapter_notifications", False):
            return False
        setting_value = frappe.db.get_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications"
        )
        return bool(setting_value)

    def _dispatch_board_notification(self, template_name, notification_key, other_chapter, effective_date):
        """Send the given template to all active board members of self.parent."""
        try:
            chapter_doc = frappe.get_cached_doc("Chapter", self.parent)
        except frappe.DoesNotExistError:
            return

        recipients = []
        seen = set()
        for board_row in chapter_doc.board_members:
            if not board_row.is_active or not board_row.member:
                continue
            email = frappe.db.get_value("Member", board_row.member, "email")
            if email and email not in seen:
                recipients.append(email)
                seen.add(email)

        if not recipients:
            return

        member_doc = frappe.get_cached_doc("Member", self.member)
        member_name = member_doc.full_name or (
            f"{member_doc.first_name or ''} {member_doc.last_name or ''}".strip() or self.member
        )

        from verenigingen.services.communication.email_service import get_email_service

        context = {
            "member_name": member_name,
            "member_id": self.member,
            "member_link": frappe.utils.get_url(f"/app/member/{self.member}"),
            "chapter_name": self.parent,
            "other_chapter": other_chapter,
            "effective_date": frappe.utils.formatdate(effective_date),
            "leave_reason": getattr(self, "leave_reason", None),
        }

        get_email_service().send_templated_email(
            template_name=template_name,
            recipients=recipients,
            context=context,
            reference_doctype="Chapter",
            reference_name=self.parent,
            notification_key=notification_key,
        )
```

Add `from frappe.utils import today` is not required — we already use `frappe.utils.today()` via the module reference.

- [ ] **Step 4: Run tests, verify they pass**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: all 6 tests from this task + the 2 from Task 3 pass.

If a test fails because `frappe.db.delete("Email Queue")` doesn't clear rows between tests, insert `frappe.db.commit()` after the delete. If it fails because Email Templates aren't found, re-run `bench migrate` to load the fixtures from Task 2.

- [ ] **Step 5: Commit**

```bash
git add verenigingen/verenigingen/doctype/chapter_member/chapter_member.py verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py
git commit -m "feat(chapter): notify board on member join/leave via ChapterMember hooks"
```

---

## Task 5: Transfer-aware notifications

With the flag plumbing from Task 3 and the helpers from Task 4, transfers should already emit the correct templates. Add the integration test that proves both boards get the right template.

**Files:**
- Test: `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py`

- [ ] **Step 1: Add failing test for transfer**

Append to the test class:

```python
    def test_transfer_notifies_both_boards_with_distinct_templates(self):
        """Transfer: old board gets 'transferred_out', new board gets 'transferred_in', neither gets plain."""
        chapter_a, _ = self._make_chapter_with_board(["a-board@example.com"])
        chapter_b, _ = self._make_chapter_with_board(["b-board@example.com"])
        member = self.factory.create_member()

        # Seed member into chapter A silently
        frappe.flags.suppress_chapter_notifications = True
        ChapterMembershipManager.assign_member_to_chapter(member.name, chapter_a.name)
        frappe.flags.suppress_chapter_notifications = False
        frappe.db.delete("Email Queue")
        frappe.db.commit()

        ChapterMembershipManager.transfer_member_between_chapters(
            member.name, chapter_a.name, chapter_b.name
        )

        a_subjects = self._emails_sent_to("a-board@example.com")
        b_subjects = self._emails_sent_to("b-board@example.com")

        # Old board: transferred_out, not plain "left"
        self.assertTrue(
            any("transferred from" in s for s in a_subjects),
            f"Expected transferred_out email on old board, got: {a_subjects}",
        )
        self.assertFalse(any(s.startswith("Member left") for s in a_subjects))

        # New board: transferred_in, not plain "joined"
        self.assertTrue(
            any("transferred to" in s for s in b_subjects),
            f"Expected transferred_in email on new board, got: {b_subjects}",
        )
        self.assertFalse(any(s.startswith("New member in") for s in b_subjects))
```

- [ ] **Step 2: Run the test, verify it passes**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: the new test passes (the flag plumbing + helpers from Tasks 3+4 already handle this case). If it fails, most likely the flag isn't being read correctly — inspect `frappe.flags.chapter_transfer` mid-test with a debug print and compare the `member`/`from`/`to` values against what the hook sees in `self.member`/`self.parent`.

- [ ] **Step 3: Commit**

```bash
git add verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py
git commit -m "test(chapter): verify transfers emit distinct board templates to both chapters"
```

---

## Task 6: Flip default and add migration patch

Change the DocType JSON default for `send_chapter_assignment_notifications` from 0 to 1. Add a migration patch that applies the new default only to sites where the field has never been saved (preserving explicit 0 values).

**Files:**
- Modify: `verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json:366`
- Create: `verenigingen/patches/v2_1/enable_chapter_notifications_default_for_new_installs.py`
- Modify: `verenigingen/patches.txt`
- Test: `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py`

- [ ] **Step 1: Flip the DocType default**

In `verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json` at line ~366, change:

```json
  {
   "default": "0",
   "description": "Send email notifications when members are added to chapters (can be overridden per-operation)",
   "fieldname": "send_chapter_assignment_notifications",
```

to:

```json
  {
   "default": "1",
   "description": "Send email notifications when members are added to, leave, or transfer between chapters (can be overridden per-operation or via frappe.flags.suppress_chapter_notifications)",
   "fieldname": "send_chapter_assignment_notifications",
```

- [ ] **Step 2: Create the migration patch**

Create `verenigingen/patches/v2_1/enable_chapter_notifications_default_for_new_installs.py`:

```python
"""
Migration: Apply new chapter assignment notification default to sites that never saved the field.

The default for `Verenigingen Settings.send_chapter_assignment_notifications` has
flipped from 0 to 1. Sites that never explicitly saved a value should pick up the
new default; sites that explicitly set 0 or 1 are preserved as-is.

We detect "never saved" by checking the tabSingles row. If no row exists for this
field on Verenigingen Settings, we create one with value=1. If a row already
exists, we leave it alone.
"""

import frappe


def execute():
    try:
        existing = frappe.db.sql(
            """
            SELECT value FROM `tabSingles`
            WHERE doctype = %s AND field = %s
            """,
            ("Verenigingen Settings", "send_chapter_assignment_notifications"),
            as_dict=True,
        )

        if existing:
            frappe.logger().info(
                "send_chapter_assignment_notifications already has a saved value "
                f"({existing[0]['value']!r}); leaving it untouched."
            )
            return

        frappe.db.set_single_value(
            "Verenigingen Settings", "send_chapter_assignment_notifications", 1
        )
        frappe.db.commit()
        frappe.logger().info(
            "Applied new default (1) for send_chapter_assignment_notifications."
        )

    except Exception as e:
        frappe.log_error(
            f"Error in chapter notifications default migration: {str(e)}",
            "Chapter Notifications Default Migration",
        )
        frappe.logger().warning(
            f"Could not apply chapter notification default: {str(e)}"
        )
```

- [ ] **Step 3: Register the patch in patches.txt**

Append to `verenigingen/patches.txt` (at the end):

```
verenigingen.patches.v2_1.enable_chapter_notifications_default_for_new_installs
```

- [ ] **Step 4: Add a test that verifies the patch is idempotent and respects explicit values**

Append to the test class in `test_chapter_board_lifecycle_notifications.py`:

```python
    def test_migration_applies_new_default_when_unset(self):
        """Migration sets value to 1 when tabSingles row is missing, leaves it alone otherwise."""
        from verenigingen.patches.v2_1.enable_chapter_notifications_default_for_new_installs import (
            execute as run_patch,
        )

        # Case 1: field was explicitly set to 0 → patch preserves it
        frappe.db.set_single_value("Verenigingen Settings", "send_chapter_assignment_notifications", 0)
        run_patch()
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "send_chapter_assignment_notifications"),
            0,
        )

        # Case 2: field row is deleted → patch creates it with default 1
        frappe.db.sql(
            """DELETE FROM `tabSingles`
            WHERE doctype = %s AND field = %s""",
            ("Verenigingen Settings", "send_chapter_assignment_notifications"),
        )
        frappe.db.commit()
        run_patch()
        self.assertEqual(
            frappe.db.get_single_value("Verenigingen Settings", "send_chapter_assignment_notifications"),
            1,
        )
```

- [ ] **Step 5: Run migration and tests**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org migrate
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: migration logs "already has a saved value" (since our setUp() wrote 1); all tests pass.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json verenigingen/patches/v2_1/enable_chapter_notifications_default_for_new_installs.py verenigingen/patches.txt verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py
git commit -m "feat(settings): default chapter board notifications to ON

Flips send_chapter_assignment_notifications default 0→1 and adds a migration
that applies the new default only to sites where the field has never been
saved, preserving explicit opt-outs."
```

---

## Task 7: Approval-path notification (Pending → Active status flip)

`approve_member_request` in `member_manager.py` flips an existing ChapterMember's status from "Pending" to "Active" via `self.chapter_doc.save()` — no new row is inserted, so `after_insert` does NOT fire. This task adds an explicit trigger for the approval path, which is the core gap the feature closes (Scenario 2).

**Files:**
- Modify: `verenigingen/verenigingen/doctype/chapter_member/chapter_member.py` (expose public method)
- Modify: `verenigingen/verenigingen/doctype/chapter/managers/member_manager.py:440` (call it after approval)
- Test: `verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py`

- [ ] **Step 1: Add the failing approval-path test**

Append to the test class:

```python
    def test_approval_path_notifies_board(self):
        """Approval via Chapter.approve_member_request triggers board notification.

        This is the core gap the feature closes: Scenario 2 from the design.
        approve_member_request flips an existing Pending row to Active (no insert),
        so an explicit notify call is required.
        """
        chapter, _ = self._make_chapter_with_board(["approve-board@example.com"])
        member = self.factory.create_member()

        # Simulate the "pending request" state by adding the member directly in Pending status.
        chapter_doc = frappe.get_doc("Chapter", chapter.name)
        chapter_doc.append(
            "members",
            {
                "member": member.name,
                "status": "Pending",
                "enabled": 0,
                "chapter_join_date": frappe.utils.today(),
            },
        )
        chapter_doc.save()
        frappe.db.delete("Email Queue")
        frappe.db.commit()

        # Approve
        chapter_doc = frappe.get_doc("Chapter", chapter.name)  # reload
        result = chapter_doc.member_manager.approve_member_request(  # ast-skip: @property not field
            member_id=member.name, approved_by="Administrator"
        )
        self.assertTrue(result.get("success"), result)

        subjects = self._emails_sent_to("approve-board@example.com")
        self.assertTrue(
            any(f"New member in {chapter.name}" in s for s in subjects),
            f"Expected 'joined' board notification after approval, got: {subjects}",
        )
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: `test_approval_path_notifies_board` fails — approval only flips status, so no hook fires and no board email is sent.

- [ ] **Step 3: Expose a public trigger on ChapterMember**

In `verenigingen/verenigingen/doctype/chapter_member/chapter_member.py`, add this method inside the `ChapterMember` class (e.g., right after `_notify_board_of_member_joined`):

```python
    def notify_board_of_joined_now(self):
        """Public entry point for status transitions (e.g. Pending → Active on approval).

        Identical to the after_insert path but callable explicitly because a status
        flip doesn't trigger after_insert.
        """
        self._notify_board_of_member_joined()
```

- [ ] **Step 4: Wire approve_member_request to call it**

In `verenigingen/verenigingen/doctype/chapter/managers/member_manager.py`, find `approve_member_request` (line 392). After the existing line `self._notify_member_approved(member_id)` (around line 440), add:

```python
            # Notify the board that the approved member is now active.
            # approve_member_request flips status on an existing row rather than
            # inserting, so after_insert does not fire — trigger explicitly.
            try:
                existing_member.notify_board_of_joined_now()
            except Exception as e:
                frappe.log_error(
                    f"Board notification on approval failed for {member_id}: {e}",
                    "Chapter Approval Board Notification",
                )
```

- [ ] **Step 5: Run the test, verify it passes**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org clear-cache
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: all tests pass, including `test_approval_path_notifies_board`.

- [ ] **Step 6: Commit**

```bash
git add verenigingen/verenigingen/doctype/chapter_member/chapter_member.py verenigingen/verenigingen/doctype/chapter/managers/member_manager.py verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py
git commit -m "feat(chapter): notify board when pending member is approved

approve_member_request flips Pending→Active on an existing ChapterMember row
without inserting, so after_insert doesn't fire. Add an explicit trigger to
close the Scenario 2 gap from the design."
```

---

## Task 8: Final verification

- [ ] **Step 1: Run the full lifecycle test module**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter.test_chapter_board_lifecycle_notifications
```
Expected: all ~10 tests pass.

- [ ] **Step 2: Run the broader chapter test suite to check for regressions**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org run-tests --app verenigingen --module verenigingen.tests.chapter
```
Expected: no new failures. Pre-existing failures documented in memory are acceptable (e.g., Jest hook failures don't apply here — Python only).

- [ ] **Step 3: Run pre-commit on touched files**

```bash
cd ~/frappe-bench/apps/verenigingen && SKIP=whitelist-type-safety,javascript-doctype-validator pre-commit run --files \
    verenigingen/notification_registry.py \
    verenigingen/fixtures/email_template.json \
    verenigingen/services/chapter/chapter_membership_manager.py \
    verenigingen/verenigingen/doctype/chapter_member/chapter_member.py \
    verenigingen/verenigingen/doctype/verenigingen_settings/verenigingen_settings.json \
    verenigingen/verenigingen/doctype/chapter/managers/member_manager.py \
    verenigingen/patches/v2_1/enable_chapter_notifications_default_for_new_installs.py \
    verenigingen/patches.txt \
    verenigingen/tests/chapter/test_chapter_board_lifecycle_notifications.py
```
Expected: all hooks pass. If ruff auto-fixes anything, stage the changes with:
```bash
git add -u && git commit -m "style: ruff auto-fix after chapter board notifications"
```

- [ ] **Step 4: Smoke-check the email template names resolve**

```bash
cd ~/frappe-bench && bench --site veg11.veganisme.org execute frappe.client.get_value --kwargs '{"doctype": "Email Template", "filters": {"name": "chapter_board_member_transferred_in"}, "fieldname": "subject"}'
```
Expected: returns the transferred_in subject line.
