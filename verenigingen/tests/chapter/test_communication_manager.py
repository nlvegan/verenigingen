"""
Real-integration tests for the chapter ``CommunicationManager``
``verenigingen/verenigingen/doctype/chapter/managers/communication_manager.py``.

The manager owns all chapter communications and notifications (board/member
lifecycle notifications, bulk notifications, newsletters, statutory mailings,
Communication-record creation, history queries). It is reached in production via
``chapter_doc.communication_manager`` (a lazily-built ``CommunicationManager(self)``),
so every test resolves the manager that way to mirror the real call path rather
than instantiating the class directly.

EmailService is a no-op in the test environment, so the email send itself is not
asserted on -- instead the tests exercise the real branching (template lookup,
recipient resolution, opt-in/statutory filtering, guard clauses) and assert on
observable outputs: returned dicts, recipient lists, created Communication rows
and Comment audit trails. All Chapters/Members/Volunteers/Email Templates are
created via the real test factory (no business-logic mocking) and the suite runs
as Administrator.
"""

import frappe

from verenigingen.tests.utils.base import VereningingenTestCase


class TestCommunicationManager(VereningingenTestCase):
    """Exercise the chapter CommunicationManager via chapter.communication_manager."""

    def setUp(self):
        super().setUp()
        self.chapter = self.create_test_chapter(
            chapter_name=f"CommMgr Chapter {frappe.generate_hash(length=6)}",
            postal_codes="1000-9999",
            published=1,
        )
        self.member = self.create_test_member(
            first_name="CommMgr",
            last_name="Primary",
            email=f"commmgr.primary.{frappe.generate_hash(length=6)}@test.invalid",
            status="Active",
        )

    # ------------------------------------------------------------------ helpers

    @property
    def manager(self):
        """Resolve the manager the same way production does."""
        return self.chapter.communication_manager

    def _reload_chapter(self):
        self.chapter = frappe.get_doc("Chapter", self.chapter.name)
        # Managers are cached per-doc; resolving from the fresh doc gives a fresh manager.
        return self.chapter

    def _make_member(self, first="Extra", status="Active", email=True):
        return self.create_test_member(
            first_name=first,
            last_name="CommMgr",
            email=(f"commmgr.{first.lower()}.{frappe.generate_hash(length=6)}@test.invalid" if email else None),
            status=status,
        )

    def _make_volunteer(self, first="Vol"):
        member = self._make_member(first=first)
        volunteer = self.create_test_volunteer(member=member.name)
        return member, volunteer

    def _make_email_template(self, name=None, subject="Test Subject", response="<p>Hi</p>"):
        name = name or f"comm_tmpl_{frappe.generate_hash(length=6)}"
        tmpl = frappe.get_doc(
            {
                "doctype": "Email Template",
                "name": name,
                "subject": subject,
                "response": response,
                "use_html": 1,
            }
        ).insert()
        self.track_doc("Email Template", tmpl.name)
        return tmpl

    def _add_member_row(self, member, enabled=1):
        self.chapter.append(
            "members",
            {"member": member.name, "chapter_join_date": frappe.utils.today(), "enabled": enabled, "status": "Active"},
        )
        self.chapter.save()
        self._reload_chapter()

    def _add_board_row(self, volunteer, email):
        role_name = f"Role{frappe.generate_hash(length=6)}"
        frappe.get_doc(
            {"doctype": "Chapter Role", "role_name": role_name, "permissions_level": "Basic"}
        ).insert()
        self.track_doc("Chapter Role", role_name)
        self.add_board_member_to_chapter(self.chapter, volunteer, role_name, email=email)
        self._reload_chapter()

    # ===================================================== _get_email_template

    def test_get_email_template_returns_doc_when_present(self):
        tmpl = self._make_email_template()
        got = self.manager._get_email_template(tmpl.name)
        self.assertIsNotNone(got)
        self.assertEqual(got.name, tmpl.name)

    def test_get_email_template_caches_none_when_missing(self):
        mgr = self.manager
        self.assertIsNone(mgr._get_email_template("no_such_template_xyz"))
        # Second call hits the cache (still None) without raising.
        self.assertIsNone(mgr._get_email_template("no_such_template_xyz"))
        self.assertIn("no_such_template_xyz", mgr.template_cache)

    # ===================================================== notify_board_member_added

    def test_notify_board_member_added_missing_template_returns_false(self):
        _member, volunteer = self._make_volunteer(first="NotifyAddNoTmpl")
        # Without a 'board_member_added' Email Template, the method returns False.
        self.assertFalse(self.manager.notify_board_member_added(volunteer.name, "Some Role"))

    def test_notify_board_member_added_with_template(self):
        self._make_email_template(name="board_member_added")
        _member, volunteer = self._make_volunteer(first="NotifyAddTmpl")
        # EmailService is a no-op in tests; the send path executes and reports a bool.
        result = self.manager.notify_board_member_added(volunteer.name, "Some Role")
        self.assertIsInstance(result, bool)

    def test_notify_board_member_added_volunteer_without_member_returns_false(self):
        # A volunteer with no linked member cannot be notified.
        volunteer = frappe.get_doc(
            {
                "doctype": "Volunteer",
                "volunteer_name": f"Orphan {frappe.generate_hash(length=6)}",
                "email": f"orphan.{frappe.generate_hash(length=6)}@test.invalid",
                "status": "Active",
            }
        ).insert()
        self.track_doc("Volunteer", volunteer.name)
        self.assertFalse(self.manager.notify_board_member_added(volunteer.name, "Some Role"))

    # ===================================================== notify_board_member_removed

    def test_notify_board_member_removed_missing_template_returns_false(self):
        _member, volunteer = self._make_volunteer(first="NotifyRem")
        self.assertFalse(self.manager.notify_board_member_removed(volunteer.name, reason="left"))

    def test_notify_board_member_removed_with_template(self):
        self._make_email_template(name="board_member_removed")
        _member, volunteer = self._make_volunteer(first="NotifyRemTmpl")
        self.assertIsInstance(self.manager.notify_board_member_removed(volunteer.name), bool)

    # ===================================================== notify_role_transition

    def test_notify_role_transition_falls_back_to_added_template(self):
        # No 'board_role_transition' template, but 'board_member_added' exists ->
        # the fallback path is taken (no exception, bool returned).
        self._make_email_template(name="board_member_added")
        _member, volunteer = self._make_volunteer(first="NotifyTrans")
        self.assertIsInstance(
            self.manager.notify_role_transition(volunteer.name, "Old", "New"), bool
        )

    def test_notify_role_transition_no_templates_returns_false(self):
        _member, volunteer = self._make_volunteer(first="NotifyTransNo")
        self.assertFalse(self.manager.notify_role_transition(volunteer.name, "Old", "New"))

    # ===================================================== notify_member_added/removed

    def test_notify_member_added_missing_template_returns_false(self):
        self.assertFalse(self.manager.notify_member_added(self.member.name))

    def test_notify_member_added_with_template(self):
        self._make_email_template(name="member_added_to_chapter")
        self.assertIsInstance(self.manager.notify_member_added(self.member.name), bool)

    def test_notify_member_added_member_without_email_returns_false(self):
        no_email = self._make_member(first="NoEmail", email=False)
        # Member created without an email cannot be notified.
        self.assertFalse(self.manager.notify_member_added(no_email.name))

    def test_notify_member_removed_missing_template_returns_false(self):
        self.assertFalse(self.manager.notify_member_removed(self.member.name, reason="moved"))

    def test_notify_member_removed_with_template(self):
        self._make_email_template(name="member_removed_from_chapter")
        self.assertIsInstance(self.manager.notify_member_removed(self.member.name), bool)

    # ===================================================== send_bulk_notification

    def test_send_bulk_notification_no_recipients(self):
        result = self.manager.send_bulk_notification(
            template_name="any", recipients=[], subject="S", context={}
        )
        self.assertFalse(result["success"])
        self.assertIn("No recipients", result["error"])

    def test_send_bulk_notification_missing_template(self):
        result = self.manager.send_bulk_notification(
            template_name="no_such_template_xyz",
            recipients=["a@test.invalid"],
            subject="S",
            context={},
        )
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_send_bulk_notification_batches(self):
        tmpl = self._make_email_template()
        recipients = [f"bulk{i}.{frappe.generate_hash(length=4)}@test.invalid" for i in range(5)]
        result = self.manager.send_bulk_notification(
            template_name=tmpl.name, recipients=recipients, subject="Bulk", context={}, batch_size=2
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["total_recipients"], 5)
        self.assertIn("sent_count", result)

    # ===================================================== _get_newsletter_recipients

    def test_get_newsletter_recipients_all(self):
        self._add_member_row(self.member)
        _bm, volunteer = self._make_volunteer(first="NewsBoard")
        board_member_email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        self._add_board_row(volunteer, board_member_email)

        recipients = self.chapter.communication_manager._get_newsletter_recipients("all")
        self.assertIn(self.member.email, recipients)
        self.assertIn(board_member_email, recipients)

    def test_get_newsletter_recipients_board_only(self):
        self._add_member_row(self.member)
        _bm, volunteer = self._make_volunteer(first="NewsBoardOnly")
        board_member_email = frappe.db.get_value("Volunteer", volunteer.name, "email")
        self._add_board_row(volunteer, board_member_email)

        recipients = self.chapter.communication_manager._get_newsletter_recipients("board")
        self.assertIn(board_member_email, recipients)
        self.assertNotIn(self.member.email, recipients)

    def test_get_newsletter_recipients_members_only(self):
        self._add_member_row(self.member)
        recipients = self.chapter.communication_manager._get_newsletter_recipients("members")
        self.assertIn(self.member.email, recipients)

    def test_get_newsletter_recipients_excludes_disabled_member(self):
        self._add_member_row(self.member, enabled=0)
        recipients = self.chapter.communication_manager._get_newsletter_recipients("members")
        self.assertNotIn(self.member.email, recipients)

    def test_get_newsletter_recipients_respects_opt_out(self):
        frappe.db.set_value("Member", self.member.name, "accepts_optional_communications", 0)
        self._add_member_row(self.member)
        recipients = self.chapter.communication_manager._get_newsletter_recipients("members")
        self.assertNotIn(self.member.email, recipients)

    # ===================================================== send_chapter_newsletter

    def test_send_chapter_newsletter_no_recipients(self):
        result = self.manager.send_chapter_newsletter("Subject", "Body", recipient_filter="all")
        self.assertFalse(result["success"])
        self.assertIn("No recipients", result["error"])

    def test_send_chapter_newsletter_happy_path_creates_comment(self):
        self._make_email_template(name="chapter_newsletter")
        self._add_member_row(self.member)
        comments_before = frappe.db.count(
            "Comment", {"reference_doctype": "Chapter", "reference_name": self.chapter.name}
        )
        result = self.chapter.communication_manager.send_chapter_newsletter(
            "News Subject", "News body", recipient_filter="members"
        )
        self.assertTrue(result["success"])
        # A newsletter activity Comment is created on the chapter.
        comments_after = frappe.db.count(
            "Comment", {"reference_doctype": "Chapter", "reference_name": self.chapter.name}
        )
        self.assertGreater(comments_after, comments_before)

    # ===================================================== create_email_communication

    def test_create_email_communication_creates_record(self):
        # NOTE: the Communication doctype validates `recipients` as a real
        # comma-separated email list, so use deliverable-looking addresses
        # (@example.com), not the @test.invalid TLD which the validator rejects.
        first = f"alice.{frappe.generate_hash(length=6)}@example.com"
        name = self.manager.create_email_communication(
            recipients=[first, f"bob.{frappe.generate_hash(length=6)}@example.com"],
            subject=f"Comm {frappe.generate_hash(length=6)}",
            content="hello",
        )
        self.assertIsNotNone(name)
        self.track_doc("Communication", name)
        comm = frappe.get_doc("Communication", name)
        self.assertEqual(comm.reference_doctype, "Chapter")
        self.assertEqual(comm.reference_name, self.chapter.name)
        # NOTE: Communication auto-sets status to "Linked" when it has a reference
        # doc, overriding the requested "Sent"; assert the record exists + carries
        # both recipients rather than the (framework-managed) status value.
        self.assertIn(first, comm.recipients)

    def test_create_email_communication_uses_valid_type(self):
        # Regression: communication_type must be a valid Select value
        # ("Communication"), not "Email" (which belongs to communication_medium).
        name = self.manager.create_email_communication(
            recipients=[f"eve.{frappe.generate_hash(length=6)}@example.com"],
            subject=f"Type {frappe.generate_hash(length=6)}",
            content="x",
        )
        self.assertIsNotNone(name)
        self.track_doc("Communication", name)
        comm = frappe.get_doc("Communication", name)
        self.assertEqual(comm.communication_type, "Communication")
        self.assertEqual(comm.communication_medium, "Email")

    # ===================================================== get_communication_history

    def test_get_communication_history_returns_created_record(self):
        subject = f"Hist {frappe.generate_hash(length=6)}"
        name = self.manager.create_email_communication(
            recipients=[f"carol.{frappe.generate_hash(length=6)}@example.com"], subject=subject, content="x"
        )
        self.track_doc("Communication", name)
        history = self.manager.get_communication_history(limit=50)
        self.assertTrue(any(h["name"] == name and h["subject"] == subject for h in history))

    def test_get_communication_history_empty_chapter(self):
        history = self.manager.get_communication_history()
        self.assertIsInstance(history, list)

    # ===================================================== get_summary

    def test_get_summary_shape(self):
        name = self.manager.create_email_communication(
            recipients=[f"dave.{frappe.generate_hash(length=6)}@example.com"],
            subject=f"Sum {frappe.generate_hash(length=6)}",
            content="x",
        )
        self.track_doc("Communication", name)
        summary = self.chapter.communication_manager.get_summary()
        for key in (
            "recent_communications",
            "communication_types",
            "pending_notifications",
            "email_settings_valid",
            "last_communication",
        ):
            self.assertIn(key, summary)
        self.assertGreaterEqual(summary["recent_communications"], 1)

    # ===================================================== send_statutory_communication

    def test_send_statutory_communication_no_recipients(self):
        result = self.manager.send_statutory_communication("AGM", "body", communication_type="agm")
        self.assertFalse(result["success"])
        self.assertIn("No recipients", result["error"])

    def test_send_statutory_communication_ignores_opt_out(self):
        # Statutory communications go to ALL members regardless of opt-out.
        frappe.db.set_value("Member", self.member.name, "accepts_optional_communications", 0)
        self._add_member_row(self.member)
        # default_statutory template won't exist, so send_bulk_notification reports
        # "not found" but the recipient resolution (the statutory logic under test)
        # already included the opted-out member.
        result = self.chapter.communication_manager.send_statutory_communication(
            "AGM Notice", "body", communication_type="agm"
        )
        # Recipients were found (opt-out ignored); only the missing template fails.
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_send_statutory_communication_with_template(self):
        self._make_email_template(name="statutory_agm")
        self._add_member_row(self.member)
        result = self.chapter.communication_manager.send_statutory_communication(
            "AGM Notice", "body", communication_type="agm"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["total_recipients"], 1)

    # ===================================================== _send_templated_email (direct)

    def test_send_templated_email_returns_bool(self):
        tmpl = self._make_email_template()
        result = self.manager._send_templated_email(
            template=tmpl,
            recipients=[self.member.email],
            subject="Direct",
            context={"chapter_name": self.chapter.name},
            reference_doctype="Chapter",
            reference_name=self.chapter.name,
            notification_key="chapter_generic_notification",
        )
        self.assertIsInstance(result, bool)

    # ============================ regression: chapter emails silently failed
    #
    # Two stacked defects made EVERY chapter notification email return False:
    #   1. _send_templated_email forwarded reference_doctype/reference_name into
    #      send_chapter_email, which then splatted them onto
    #      email_service.send_templated_email(reference_doctype="Chapter", ...) ->
    #      TypeError: multiple values for keyword argument 'reference_doctype'.
    #   2. The caller read send_chapter_email's OperationResult via .get("success")
    #      / .get("errors") -> AttributeError (OperationResult has no .get()).
    # Both were swallowed by the outer try/except, so the method always returned
    # False. The assertions below assert the method now returns TRUE on the happy
    # path (a real bool True, not just "isinstance bool" which the buggy code also
    # satisfied), and that the collision path no longer raises.

    def test_send_templated_email_succeeds_with_reference_kwargs(self):
        # The focused collision regression: passing reference_doctype/reference_name
        # (exactly what every notify_* method passes) must NOT raise and must
        # return True now that the keys are no longer double-forwarded.
        tmpl = self._make_email_template()
        result = self.manager._send_templated_email(
            template=tmpl,
            recipients=[self.member.email],
            subject="Collision regression",
            context={"chapter_name": self.chapter.name},
            reference_doctype="Chapter",
            reference_name=self.chapter.name,
            notification_key="chapter_generic_notification",
        )
        self.assertTrue(
            result,
            "chapter email must succeed; previously returned False due to a "
            "reference_doctype kwargs collision (TypeError) + OperationResult.get() "
            "AttributeError swallowed by the outer except",
        )

    def test_send_chapter_email_returns_operation_result_success(self):
        # Boundary assertion: the compatibility wrapper the manager calls returns a
        # real OperationResult with .success truthy (not a dict, not raising).
        from verenigingen.services.communication.compatibility import send_chapter_email
        from verenigingen.utils.operation_result import OperationResult

        tmpl = self._make_email_template()
        result = send_chapter_email(
            chapter_name=self.chapter.name,
            recipients=[self.member.email],
            subject="Wrapper boundary",
            template=tmpl.name,
            context={"chapter_name": self.chapter.name},
            communication_type="Email",
            notification_key="chapter_generic_notification",
        )
        self.assertIsInstance(result, OperationResult)
        self.assertTrue(result.success, f"send_chapter_email failed: {result.errors}")

    def test_notify_board_member_added_returns_true(self):
        # End-to-end regression through a real notify_* method: with the template
        # present and a real volunteer/member, this routed through the broken
        # _send_templated_email and returned False. It must now return True.
        self._make_email_template(name="board_member_added")
        _member, volunteer = self._make_volunteer(first="NotifyAddTrue")
        result = self.manager.notify_board_member_added(volunteer.name, "Some Role")
        self.assertIs(result, True)

    def test_notify_member_added_returns_true(self):
        # Member-facing notification path through _send_templated_email.
        self._make_email_template(name="member_added_to_chapter")
        result = self.manager.notify_member_added(self.member.name)
        self.assertIs(result, True)

    # ===================================================== _validate_email_settings

    def test_validate_email_settings_returns_bool(self):
        self.assertIsInstance(self.manager._validate_email_settings(), bool)

    def test_generate_unsubscribe_url_includes_chapter(self):
        url = self.manager._generate_unsubscribe_url()
        self.assertIn(self.chapter.name, url)
